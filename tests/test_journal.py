import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import respx
from httpx import Response

from koreadertohardcover.config import Config
from koreadertohardcover.engine import SyncEngine, daily_progress
from koreadertohardcover.hardcover_client import HardcoverClient


def test_daily_progress_keeps_days_that_move_forward() -> None:
    rows = [
        ("2026-11-01", 0.10),
        ("2026-11-02", 0.05),  # paged back: no progress
        ("2026-11-03", 0.25),
        ("2026-11-04", 1.20),  # page count changed: capped
    ]

    assert daily_progress(rows) == [
        ("2026-11-01", 0.1),
        ("2026-11-03", 0.25),
        ("2026-11-04", 1.0),
    ]


@pytest.fixture
def engine(tmp_path: Path) -> SyncEngine:
    config = Config()
    config.HARDCOVER_BEARER_TOKEN = "test_token"
    engine = SyncEngine(db_path=str(tmp_path / "journal.duckdb"), config=config)
    with engine.db.get_connection() as conn:
        conn.execute(
            "INSERT INTO books (id, title, total_read_pages, total_pages, last_open) "
            "VALUES ('md5_1', 'Book One', 30, 200, '2026-11-02')"
        )
        conn.execute(
            "INSERT INTO book_mappings (local_book_id, hardcover_id, edition_id) "
            "VALUES ('md5_1', '1001', '55')"
        )
        # KOReader's page count changes with the font size, so each row
        # counts against its own total.
        conn.execute(
            "INSERT INTO reading_sessions (id, book_id, page, start_time, duration, total_pages) "
            "VALUES (1, 'md5_1', 10, '2026-11-01 20:00', 60, 100), "
            "(2, 'md5_1', 20, '2026-11-01 21:00', 60, 100), "
            "(3, 'md5_1', 60, '2026-11-02 20:00', 60, 200)"
        )
    return engine


@patch("koreadertohardcover.engine.HardcoverClient")
def test_sync_writes_journal_once_per_change(
    MockHC: MagicMock, engine: SyncEngine
) -> None:
    hc = MockHC.return_value
    hc.update_progress.return_value = True
    hc.sync_progress_journal.return_value = True

    engine.sync_progress()
    engine.sync_progress()

    hc.sync_progress_journal.assert_called_once_with(
        "1001", "55", [("2026-11-01", 0.2), ("2026-11-02", 0.3)]
    )

    engine.sync_progress(force=True)
    assert hc.sync_progress_journal.call_count == 2


@patch("koreadertohardcover.engine.HardcoverClient")
def test_failed_journal_is_retried_and_keeps_sync_ok(
    MockHC: MagicMock, engine: SyncEngine
) -> None:
    hc = MockHC.return_value
    hc.update_progress.return_value = True
    hc.sync_progress_journal.side_effect = [False, True]

    assert engine.sync_progress() == [("Book One", True)]
    engine.sync_progress()

    assert hc.sync_progress_journal.call_count == 2


@respx.mock
def test_journal_merges_existing_entries() -> None:
    config = Config()
    config.HARDCOVER_BEARER_TOKEN = "test_token"
    client = HardcoverClient(config)
    existing = [
        # Written by hand before KOReader tracked the book: kept.
        {"id": 1, "journal_date": "2026-10-01", "metadata": {"progress_pages": 5}},
        # Hardcover's own entry on a reading day: rewritten.
        {
            "id": 2,
            "journal_date": "2026-11-01",
            "metadata": {"progress_pages": 99, "user_book_read_id": 7},
        },
        # Already right: untouched. The duplicate on that day goes.
        {
            "id": 3,
            "journal_date": "2026-11-02",
            "metadata": {
                "progress": 30,
                "progress_was": 20,
                "percent_delta": 10,
                "progress_pages": 30,
                "progress_pages_was": 20,
                "pages_delta": 10,
            },
        },
        {"id": 4, "journal_date": "2026-11-02", "metadata": {"progress_pages": 30}},
        # Hardcover's entry from a sync after midnight: removed.
        {
            "id": 5,
            "journal_date": "2026-11-04",
            "metadata": {"progress_pages": 30, "user_book_read_id": 7},
        },
    ]
    calls = []

    def handler(request):
        body = json.loads(request.read())
        query, variables = body["query"], body.get("variables") or {}
        if "GetMe" in query:
            return Response(200, json={"data": {"me": [{"id": 42}]}})
        if "GetEditionPages" in query:
            return Response(200, json={"data": {"editions_by_pk": {"pages": 100}}})
        if "ProgressJournals" in query:
            return Response(200, json={"data": {"reading_journals": existing}})
        for name in ("InsertJournal", "UpdateJournal", "DeleteJournal"):
            if name in query:
                calls.append((name, variables))
                return Response(
                    200, json={"data": {"insert_reading_journal": {"id": 9}}}
                )
        return Response(404)

    respx.post("https://api.hardcover.app/v1/graphql").mock(side_effect=handler)

    days = [("2026-11-01", 0.2), ("2026-11-02", 0.3), ("2026-11-03", 0.45)]
    assert client.sync_progress_journal("1001", "55", days) is True

    assert [(name, v.get("id")) for name, v in calls] == [
        ("UpdateJournal", 2),
        ("DeleteJournal", 4),
        ("InsertJournal", None),
        # Inserts drop some metadata keys, so they are written again.
        ("UpdateJournal", 9),
        ("DeleteJournal", 5),
    ]
    assert calls[0][1]["object"]["metadata"]["progress_pages"] == 20
    inserted = calls[2][1]["object"]
    assert inserted["action_at"] == "2026-11-03"
    assert inserted["metadata"]["progress_pages"] == 45
    assert inserted["metadata"]["pages_delta"] == 15
    assert inserted["privacy_setting_id"] == 1
    assert calls[3][1]["object"]["metadata"] == inserted["metadata"]


@patch("koreadertohardcover.engine.HardcoverClient")
def test_last_day_matches_synced_progress(
    MockHC: MagicMock, engine: SyncEngine
) -> None:
    hc = MockHC.return_value
    hc.update_progress.return_value = True
    with engine.db.get_connection() as conn:
        conn.execute("UPDATE books SET total_read_pages = 70 WHERE id = 'md5_1'")

    engine.sync_progress()

    days = hc.sync_progress_journal.call_args.args[2]
    assert days == [("2026-11-01", 0.2), ("2026-11-02", 0.35)]
