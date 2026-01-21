import pytest
from koreadertohardcover.database import DatabaseManager


class TestDatabaseManager:
    @pytest.fixture
    def db(self, tmp_path):
        db_path = tmp_path / "test_map.duckdb"
        db = DatabaseManager(str(db_path))
        # Seed test data
        with db.get_connection() as conn:
            conn.execute(
                "INSERT INTO books (id, title, authors, last_open) VALUES ('1', 'Book A', 'Author A', '2023-01-01')"
            )
            conn.execute(
                "INSERT INTO books (id, title, authors, last_open) VALUES ('2', 'Book B', 'Author B', '2023-01-02')"
            )
            conn.execute(
                "INSERT INTO books (id, title, authors, last_open) VALUES ('3', 'Book C', 'Author C', '2023-01-03')"
            )
        return db

    def test_get_local_books_all(self, db):
        books, count = db.get_local_books()
        assert count == 3
        assert len(books) == 3
        # Verify sort order (newest first)
        assert books[0][1] == "Book C"
        assert books[1][1] == "Book B"
        assert books[2][1] == "Book A"

    def test_get_local_books_query(self, db):
        books, count = db.get_local_books(query="Book B")
        assert count == 1
        assert len(books) == 1
        assert books[0][1] == "Book B"

    def test_get_local_books_pagination(self, db):
        books, count = db.get_local_books(limit=1, offset=0)
        assert count == 3
        assert len(books) == 1
        assert books[0][1] == "Book C"

        books, count = db.get_local_books(limit=1, offset=1)
        assert len(books) == 1
        assert books[0][1] == "Book B"

    def test_get_local_books_mapped_status(self, db):
        # Create mapping for Book A
        with db.get_connection() as conn:
            conn.execute("INSERT INTO book_mappings (local_book_id) VALUES ('1')")

        books, _ = db.get_local_books()

        # Book C (Newest) - Unmapped
        assert books[0][4] == 0
        # Book A (Oldest) - Mapped
        assert books[2][4] == 1
