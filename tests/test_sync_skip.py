from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from koreadertohardcover.config import Config
from koreadertohardcover.engine import SyncEngine


@pytest.fixture
def config() -> Config:
    conf = Config()
    conf.HARDCOVER_BEARER_TOKEN = "test_token"
    return conf


@pytest.fixture
def engine(tmp_path: Path, config: Config) -> SyncEngine:
    engine = SyncEngine(db_path=str(tmp_path / "sync.duckdb"), config=config)
    with engine.db.get_connection() as conn:
        conn.execute(
            "INSERT INTO books (id, title, authors, total_read_pages, total_pages, "
            "total_read_time, status, last_open) VALUES "
            "('md5_1', 'Book One', 'Author A', 50, 100, 3600, 'reading', '2023-01-01')"
        )
        conn.execute(
            "INSERT INTO book_mappings (local_book_id, hardcover_id, edition_id) "
            "VALUES ('md5_1', '1001', NULL)"
        )
    return engine


def _set_read_pages(engine: SyncEngine, pages: int) -> None:
    with engine.db.get_connection() as conn:
        conn.execute(
            "UPDATE books SET total_read_pages = ? WHERE id = 'md5_1'", [pages]
        )


def _fingerprints(engine: SyncEngine) -> list[tuple]:
    with engine.db.get_connection() as conn:
        return conn.execute(
            "SELECT local_book_id, fingerprint FROM sync_state"
        ).fetchall()


@patch("koreadertohardcover.engine.HardcoverClient")
def test_first_sync_calls_hardcover_and_stores_fingerprint(
    MockHC: MagicMock, engine: SyncEngine
) -> None:
    MockHC.return_value.update_progress.return_value = True

    results = engine.sync_progress()

    assert results == [("Book One", True)]
    assert MockHC.return_value.update_progress.call_count == 1
    assert len(_fingerprints(engine)) == 1


@patch("koreadertohardcover.engine.HardcoverClient")
def test_unchanged_book_is_skipped_without_network_call(
    MockHC: MagicMock, engine: SyncEngine
) -> None:
    hc = MockHC.return_value
    hc.update_progress.return_value = True
    engine.sync_progress()

    results = engine.sync_progress()

    assert results == [("Book One", True)]
    assert hc.update_progress.call_count == 1


@patch("koreadertohardcover.engine.HardcoverClient")
def test_changed_progress_is_synced_again(
    MockHC: MagicMock, engine: SyncEngine
) -> None:
    hc = MockHC.return_value
    hc.update_progress.return_value = True
    engine.sync_progress()

    _set_read_pages(engine, 80)
    engine.sync_progress()

    assert hc.update_progress.call_count == 2


@patch("koreadertohardcover.engine.HardcoverClient")
def test_force_ignores_the_fingerprint(MockHC: MagicMock, engine: SyncEngine) -> None:
    hc = MockHC.return_value
    hc.update_progress.return_value = True
    engine.sync_progress()

    engine.sync_progress(force=True)

    assert hc.update_progress.call_count == 2


@patch("koreadertohardcover.engine.HardcoverClient")
def test_failed_sync_is_retried_next_run(MockHC: MagicMock, engine: SyncEngine) -> None:
    hc = MockHC.return_value
    hc.update_progress.return_value = False

    results = engine.sync_progress()

    assert results == [("Book One", False)]
    assert _fingerprints(engine) == []

    engine.sync_progress()

    assert hc.update_progress.call_count == 2
