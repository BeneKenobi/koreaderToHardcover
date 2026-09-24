from pathlib import Path
from unittest.mock import MagicMock, patch

import duckdb

from koreadertohardcover.config import Config
from koreadertohardcover.database import DatabaseManager
from koreadertohardcover.engine import SyncEngine


def _covers(db: DatabaseManager) -> dict:
    with db.get_connection() as conn:
        return dict(
            conn.execute(
                "SELECT local_book_id, image_url FROM book_mappings"
            ).fetchall()
        )


def test_existing_database_gets_image_url_column(tmp_path: Path) -> None:
    db_path = str(tmp_path / "old.duckdb")
    with duckdb.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE book_mappings (local_book_id VARCHAR PRIMARY KEY, "
            "hardcover_id VARCHAR, edition_id VARCHAR)"
        )
        conn.execute("INSERT INTO book_mappings VALUES ('a', '1', NULL)")

    db = DatabaseManager(db_path)

    assert db.init_error is None
    assert db.get_mappings_without_cover() == [("a", "1", None)]


def test_remap_without_cover_is_looked_up_again(tmp_path: Path) -> None:
    db = DatabaseManager(str(tmp_path / "remap.duckdb"))
    db.save_book_mapping("a", "1", image_url="https://assets.hardcover.app/x.jpg")

    db.save_book_mapping("a", "2")

    assert db.get_mappings_without_cover() == [("a", "2", None)]


@patch("koreadertohardcover.engine.HardcoverClient")
def test_sync_backfills_missing_covers(MockHC: MagicMock, tmp_path: Path) -> None:
    config = Config()
    config.HARDCOVER_BEARER_TOKEN = "token"
    engine = SyncEngine(db_path=str(tmp_path / "sync.duckdb"), config=config)
    engine.db.save_book_mapping("with-edition", "1", "10")
    engine.db.save_book_mapping("edition-no-cover", "2", "20")
    engine.db.save_book_mapping("no-cover", "3")
    engine.db.save_book_mapping(
        "known", "4", image_url="https://assets.hardcover.app/known.jpg"
    )
    hc = MockHC.return_value
    hc.get_cover_urls.return_value = (
        {
            1: "https://assets.hardcover.app/book1.jpg",
            2: "https://assets.hardcover.app/book2.jpg",
        },
        {10: "https://assets.hardcover.app/edition10.jpg"},
    )

    engine.sync_progress()

    hc.get_cover_urls.assert_called_once_with([1, 2, 3], [10, 20])
    assert _covers(engine.db) == {
        "with-edition": "https://assets.hardcover.app/edition10.jpg",
        "edition-no-cover": "https://assets.hardcover.app/book2.jpg",
        "no-cover": "",
        "known": "https://assets.hardcover.app/known.jpg",
    }

    engine.sync_progress()

    assert hc.get_cover_urls.call_count == 1


@patch("koreadertohardcover.engine.HardcoverClient")
def test_cover_errors_do_not_fail_the_sync(MockHC: MagicMock, tmp_path: Path) -> None:
    config = Config()
    config.HARDCOVER_BEARER_TOKEN = "token"
    engine = SyncEngine(db_path=str(tmp_path / "err.duckdb"), config=config)
    engine.db.save_book_mapping("a", "1")
    MockHC.return_value.get_cover_urls.side_effect = RuntimeError("down")

    assert engine.sync_progress() == []
    assert engine.db.get_mappings_without_cover() == [("a", "1", None)]
