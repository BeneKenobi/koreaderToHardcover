import sqlite3
from pathlib import Path

import duckdb
import pytest

from koreadertohardcover.database import DatabaseManager


def _make_koreader_db(path: Path, last_open: int = 1_700_000_000) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE book (
            id INTEGER PRIMARY KEY, title TEXT, authors TEXT, notes INTEGER,
            last_open INTEGER, highlights INTEGER, pages INTEGER, series TEXT,
            language TEXT, md5 TEXT, total_read_time INTEGER, total_read_pages INTEGER
        );
        CREATE TABLE page_stat_data (
            id_book INTEGER, page INTEGER, start_time INTEGER, duration INTEGER,
            total_pages INTEGER
        );
        """
    )
    for i in range(24):
        conn.execute(
            "INSERT INTO book VALUES (?, ?, 'A', 0, ?, 0, 300, '', 'en', ?, 100, 10)",
            (i, f"Book {i}", last_open, f"md5-{i}"),
        )
    conn.commit()
    conn.close()


@pytest.fixture
def koreader_db(tmp_path: Path) -> Path:
    path = tmp_path / "statistics.sqlite3"
    _make_koreader_db(path)
    return path


@pytest.fixture
def db_manager(tmp_path: Path) -> DatabaseManager:
    return DatabaseManager(str(tmp_path / "test.duckdb"))


def _row_group_count(manager: DatabaseManager) -> int:
    with manager.get_connection() as conn:
        return conn.execute(
            "SELECT count(DISTINCT row_group_id) FROM pragma_storage_info('books')"
        ).fetchone()[0]


def _index_names(manager: DatabaseManager) -> set[str]:
    with manager.get_connection() as conn:
        return {
            r[0]
            for r in conn.execute("SELECT index_name FROM duckdb_indexes()").fetchall()
        }


def test_books_updated_at_index_not_created(db_manager: DatabaseManager) -> None:
    assert "idx_books_updated_at" not in _index_names(db_manager)


def test_legacy_updated_at_index_is_dropped(tmp_path: Path) -> None:
    path = str(tmp_path / "legacy.duckdb")
    DatabaseManager(path)
    with duckdb.connect(path) as conn:
        conn.execute("CREATE INDEX idx_books_updated_at ON books(updated_at)")

    manager = DatabaseManager(path)

    assert "idx_books_updated_at" not in _index_names(manager)


def test_repeated_import_does_not_fragment_books(
    db_manager: DatabaseManager, koreader_db: Path
) -> None:
    for _ in range(30):
        db_manager.import_books(str(koreader_db))

    assert _row_group_count(db_manager) <= 2


def test_unchanged_import_keeps_updated_at(
    db_manager: DatabaseManager, koreader_db: Path
) -> None:
    db_manager.import_books(str(koreader_db))
    with db_manager.get_connection() as conn:
        before = conn.execute("SELECT id, updated_at FROM books ORDER BY id").fetchall()

    db_manager.import_books(str(koreader_db))

    with db_manager.get_connection() as conn:
        after = conn.execute("SELECT id, updated_at FROM books ORDER BY id").fetchall()
    assert before == after


def test_changed_book_is_updated(
    db_manager: DatabaseManager, koreader_db: Path
) -> None:
    db_manager.import_books(str(koreader_db))
    conn = sqlite3.connect(koreader_db)
    conn.execute("UPDATE book SET total_read_pages = 50 WHERE md5 = 'md5-3'")
    conn.commit()
    conn.close()

    db_manager.import_books(str(koreader_db))

    with db_manager.get_connection() as conn:
        pages = conn.execute(
            "SELECT total_read_pages FROM books WHERE id = 'md5-3'"
        ).fetchone()[0]
    assert pages == 50


def test_check_health_ok(db_manager: DatabaseManager) -> None:
    assert db_manager.check_health() is None


def test_check_health_reports_corruption(
    db_manager: DatabaseManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom() -> None:
        raise duckdb.SerializationException("field id mismatch")

    monkeypatch.setattr(db_manager, "get_connection", boom)

    error = db_manager.check_health()

    assert error is not None and "field id mismatch" in error


def test_checkpoint_runs(db_manager: DatabaseManager) -> None:
    assert db_manager.checkpoint() is True


def test_import_sessions_survives_lagging_sequence(
    db_manager: DatabaseManager, koreader_db: Path
) -> None:
    conn = sqlite3.connect(koreader_db)
    conn.executemany(
        "INSERT INTO page_stat_data VALUES (0, ?, ?, 10, 300)",
        [(i, 1_700_000_000 + i) for i in range(5)],
    )
    conn.commit()
    conn.close()
    db_manager.import_books(str(koreader_db))
    with db_manager.get_connection() as conn:
        # Rows exist with ids the sequence has never handed out.
        conn.execute(
            "INSERT INTO reading_sessions (id, book_id, start_time) "
            "VALUES (1, 'old', '2020-01-01'), (2, 'old', '2020-01-02')"
        )

    db_manager.import_sessions(str(koreader_db))

    with db_manager.get_connection() as conn:
        total, distinct = conn.execute(
            "SELECT count(*), count(DISTINCT id) FROM reading_sessions"
        ).fetchone()
    assert total == 7 and distinct == 7
