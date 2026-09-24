import sqlite3
from pathlib import Path

import pytest

from koreadertohardcover.database import DatabaseManager


def _make_koreader_db(path: Path, books: list[tuple]) -> None:
    """Creates a minimal KOReader statistics DB with the given book rows."""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE book (id INTEGER PRIMARY KEY, title TEXT, authors TEXT, "
        "notes INTEGER, last_open INTEGER, highlights INTEGER, pages INTEGER, "
        "series TEXT, language TEXT, md5 TEXT, total_read_time INTEGER, "
        "total_read_pages INTEGER)"
    )
    conn.execute(
        "CREATE TABLE page_stat_data (id_book INTEGER, page INTEGER, "
        "start_time INTEGER, duration INTEGER, total_pages INTEGER)"
    )
    conn.executemany(
        "INSERT INTO book (id, title, authors, last_open, pages, md5, "
        "total_read_pages) VALUES (?, ?, 'Author', ?, ?, ?, ?)",
        books,
    )
    conn.executemany(
        "INSERT INTO page_stat_data VALUES (?, 1, 1700000000, 30, 100)",
        [(b[0],) for b in books],
    )
    conn.commit()
    conn.close()


@pytest.fixture
def db(tmp_path: Path) -> DatabaseManager:
    return DatabaseManager(str(tmp_path / "import.duckdb"))


def _import(db: DatabaseManager, sqlite_path: Path) -> None:
    db.import_books(str(sqlite_path))
    db.import_sessions(str(sqlite_path))


def test_duplicate_md5_rows_import_once(db: DatabaseManager, tmp_path: Path) -> None:
    sqlite_path = tmp_path / "stats.sqlite3"
    _make_koreader_db(
        sqlite_path,
        [
            (1, "Old Title", 1700000000, 100, "same", 10),
            (2, "New Title", 1700009999, 100, "same", 20),
        ],
    )

    _import(db, sqlite_path)
    _import(db, sqlite_path)

    with db.get_connection() as conn:
        assert conn.execute("SELECT id, title FROM books").fetchall() == [
            ("same", "New Title")
        ]
        assert conn.execute("SELECT count(*) FROM reading_sessions").fetchone() == (1,)


@pytest.mark.parametrize(
    ("pages", "read", "expected"),
    [
        (10, 1, "reading"),  # short book, just opened
        (100, 85, "reading"),  # 15 left but only 85% read
        (300, 285, "finished"),  # 15 left of back matter, 95% read
        (100, 98, "finished"),
        (0, 0, "reading"),
    ],
)
def test_finished_rule(
    db: DatabaseManager, tmp_path: Path, pages: int, read: int, expected: str
) -> None:
    sqlite_path = tmp_path / "stats.sqlite3"
    _make_koreader_db(sqlite_path, [(1, "Book", 1700000000, pages, "md5", read)])

    _import(db, sqlite_path)

    with db.get_connection() as conn:
        assert conn.execute("SELECT status FROM books").fetchone() == (expected,)


def test_path_with_quote_attaches(db: DatabaseManager, tmp_path: Path) -> None:
    sqlite_path = tmp_path / "it's stats.sqlite3"
    _make_koreader_db(sqlite_path, [(1, "Book", 1700000000, 100, "md5", 10)])

    _import(db, sqlite_path)

    with db.get_connection() as conn:
        assert conn.execute("SELECT count(*) FROM books").fetchone() == (1,)
