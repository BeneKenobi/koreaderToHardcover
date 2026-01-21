import pytest
import os
from koreadertohardcover.database import DatabaseManager


@pytest.fixture
def db_manager(tmp_path):
    """Fixture to create a temporary database manager."""
    db_path = tmp_path / "test_ingest.duckdb"
    manager = DatabaseManager(str(db_path))
    yield manager
    # manager.close()  <-- Removed


def test_ingestion_from_example(db_manager):
    """Tests ingestion from the known example SQLite file."""
    # Resolve path relative to this test file or project root
    # Assuming running from project root
    sqlite_path = os.path.abspath("../koreaderToStorygraph/example/statistics.sqlite3")

    if not os.path.exists(sqlite_path):
        pytest.skip(f"Example file not found at {sqlite_path}")

    # Run Import
    db_manager.import_books(sqlite_path)
    db_manager.import_sessions(sqlite_path)

    with db_manager.get_connection() as conn:
        # Verify Books
        total_books = conn.execute("SELECT count(*) FROM books").fetchone()[0]
        assert total_books > 0, "No books were imported"

        # Check for a known title if possible, or just structure
        titles = [row[0] for row in conn.execute("SELECT title FROM books").fetchall()]
        print(f"Imported titles: {titles}")
        assert len(titles) == total_books

        # Verify Sessions
        total_sessions = conn.execute(
            "SELECT count(*) FROM reading_sessions"
        ).fetchone()[0]
        assert total_sessions > 0, "No reading sessions were imported"

        # Check Referential Integrity (basic)
        orphaned_sessions = conn.execute("""
            SELECT count(*) FROM reading_sessions rs
            LEFT JOIN books b ON rs.book_id = b.id
            WHERE b.id IS NULL
        """).fetchone()[0]
        assert orphaned_sessions == 0, "Found reading sessions without associated books"
