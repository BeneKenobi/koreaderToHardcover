import duckdb
from typing import Optional


class DatabaseManager:
    def __init__(self, db_path: str = "reading_stats.duckdb"):
        self.db_path = db_path
        self.create_schema()

    def get_connection(self):
        """Returns a new DuckDB connection."""
        return duckdb.connect(self.db_path)

    def create_schema(self):
        """Creates the necessary database tables if they don't exist."""
        with self.get_connection() as conn:
            # Create books table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS books (
                    id VARCHAR PRIMARY KEY, -- MD5 hash
                    koreader_id INTEGER,
                    title VARCHAR,
                    authors VARCHAR,
                    series VARCHAR,
                    language VARCHAR,
                    isbn VARCHAR,
                    total_pages INTEGER,
                    total_read_pages INTEGER,
                    total_read_time INTEGER,
                    highlights INTEGER,
                    notes INTEGER,
                    last_open TIMESTAMP,
                    status VARCHAR,
                    start_date DATE,
                    finish_date DATE,
                    rating INTEGER,
                    sync_status VARCHAR DEFAULT 'pending',
                    sync_error TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create reading_sessions table
            conn.execute("""
                CREATE SEQUENCE IF NOT EXISTS seq_reading_sessions_id
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS reading_sessions (
                    id BIGINT PRIMARY KEY DEFAULT nextval('seq_reading_sessions_id'),
                    book_id VARCHAR,
                    page INTEGER,
                    start_time TIMESTAMP,
                    duration INTEGER, -- Seconds
                    total_pages INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create book_mappings table (Hardcover specific adaptation)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS book_mappings (
                    local_book_id VARCHAR PRIMARY KEY,
                    hardcover_id VARCHAR,
                    edition_id VARCHAR,
                    hardcover_slug VARCHAR,
                    book_title VARCHAR,
                    author VARCHAR,
                    isbn VARCHAR,
                    mapping_method VARCHAR,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Indexes
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_books_updated_at ON books(updated_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reading_sessions_book_id ON reading_sessions(book_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reading_sessions_start_time ON reading_sessions(start_time)"
            )

    def get_local_books(
        self, query: Optional[str] = None, limit: int = 10, offset: int = 0
    ) -> tuple[list[tuple], int]:
        """
        Fetches local books with optional search, pagination, and mapping status.
        Returns (books, total_count).
        """
        with self.get_connection() as conn:
            # Base query
            where_clause = ""
            params = []
            if query:
                where_clause = "WHERE b.title ILIKE ? OR b.authors ILIKE ?"
                search_term = f"%{query}%"
                params = [search_term, search_term]

            # Get total count first
            count_query = f"SELECT COUNT(*) FROM books b {where_clause}"
            total = conn.execute(count_query, params).fetchone()[0]

            # Get paginated results with mapping status
            # We perform a LEFT JOIN on book_mappings to check if it's already mapped
            sql = f"""
                SELECT 
                    b.id,
                    b.title,
                    b.authors,
                    b.last_open,
                    CASE WHEN m.local_book_id IS NOT NULL THEN 1 ELSE 0 END as is_mapped,
                    m.hardcover_slug,
                    m.hardcover_id
                FROM books b
                LEFT JOIN book_mappings m ON b.id = m.local_book_id
                {where_clause}
                ORDER BY b.last_open DESC NULLS LAST
                LIMIT ? OFFSET ?
            """

            books = conn.execute(sql, params + [limit, offset]).fetchall()
            return books, total

    def import_books(self, sqlite_path: str):
        """Imports books from a KOReader SQLite database."""
        with self.get_connection() as conn:
            self._attach_koreader(conn, sqlite_path)
            try:
                # 1. Update existing books
                conn.execute("""
                    UPDATE books
                    SET
                        koreader_id = k.id,
                        title = k.title,
                        authors = k.authors,
                        series = k.series,
                        language = k.language,
                        total_pages = k.pages,
                        total_read_pages = k.total_read_pages,
                        total_read_time = k.total_read_time,
                        highlights = k.highlights,
                        notes = k.notes,
                        last_open = to_timestamp(k.last_open),
                        status = CASE 
                            WHEN k.pages > 0 AND (
                                (CAST(k.total_read_pages AS FLOAT) / CAST(pages AS FLOAT)) >= 0.98 OR
                                (k.pages - k.total_read_pages) <= 15
                            ) THEN 'finished'
                            ELSE 'reading'
                        END,
                        updated_at = now()
                    FROM koreader.book k
                    WHERE books.id = k.md5
                    AND k.md5 IS NOT NULL AND k.md5 != ''
                """)

                # 2. Insert new books
                conn.execute("""
                    INSERT INTO books (
                        id, koreader_id, title, authors, series, language, 
                        total_pages, total_read_pages, total_read_time, highlights, notes,
                        last_open, status, sync_status, created_at, updated_at
                    )
                    SELECT 
                        k.md5,
                        k.id,
                        k.title,
                        k.authors,
                        k.series,
                        k.language,
                        k.pages,
                        k.total_read_pages,
                        k.total_read_time,
                        k.highlights,
                        k.notes,
                        to_timestamp(k.last_open),
                        CASE 
                            WHEN k.pages > 0 AND (
                                (CAST(k.total_read_pages AS FLOAT) / CAST(k.pages AS FLOAT)) >= 0.98 OR
                                (k.pages - k.total_read_pages) <= 15
                            ) THEN 'finished'
                            ELSE 'reading'
                        END,
                        'pending',
                        now(),
                        now()
                    FROM koreader.book k
                    WHERE k.md5 IS NOT NULL AND k.md5 != ''
                    AND NOT EXISTS (SELECT 1 FROM books b WHERE b.id = k.md5)
                """)
            finally:
                self._detach_koreader(conn)

    def import_sessions(self, sqlite_path: str):
        """Imports reading sessions from a KOReader SQLite database."""
        with self.get_connection() as conn:
            self._attach_koreader(conn, sqlite_path)
            try:
                conn.execute("""
                    INSERT INTO reading_sessions (
                        book_id, page, start_time, duration, total_pages
                    )
                    SELECT 
                        b.md5 as book_id,
                        psd.page,
                        to_timestamp(psd.start_time) as start_time,
                        psd.duration,
                        psd.total_pages
                    FROM koreader.page_stat_data psd
                    JOIN koreader.book b ON psd.id_book = b.id
                    WHERE b.md5 IS NOT NULL AND b.md5 != ''
                    AND NOT EXISTS (
                        SELECT 1 FROM reading_sessions rs 
                        WHERE rs.book_id = b.md5 
                        AND rs.start_time = to_timestamp(psd.start_time)
                    )
                """)
            finally:
                self._detach_koreader(conn)

    def _attach_koreader(self, conn, sqlite_path: str):
        try:
            conn.execute("INSTALL sqlite;")
            conn.execute("LOAD sqlite;")
        except Exception:
            pass
        try:
            conn.execute(f"ATTACH '{sqlite_path}' AS koreader (TYPE SQLITE)")
        except Exception as e:
            raise RuntimeError(
                f"Failed to attach SQLite database at {sqlite_path}: {e}"
            )

    def _detach_koreader(self, conn):
        try:
            conn.execute("DETACH koreader")
        except Exception:
            pass

    def get_book_mapping(self, local_id: str) -> Optional[tuple[str, Optional[str]]]:
        """Returns the (hardcover_id, edition_id) for a given local book ID (MD5)."""
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT hardcover_id, edition_id FROM book_mappings WHERE local_book_id = ?",
                [local_id],
            ).fetchone()
            return (row[0], row[1]) if row else None

    def save_book_mapping(
        self,
        local_id: str,
        hardcover_id: str,
        edition_id: str = None,
        title: str = None,
        author: str = None,
    ):
        """Saves a mapping between a local book and Hardcover."""
        with self.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO book_mappings (local_book_id, hardcover_id, edition_id, book_title, author, mapping_method)
                VALUES (?, ?, ?, ?, ?, 'manual')
                ON CONFLICT (local_book_id) DO UPDATE SET
                    hardcover_id = excluded.hardcover_id,
                    edition_id = excluded.edition_id,
                    book_title = excluded.book_title,
                    author = excluded.author,
                    updated_at = now()
            """,
                [local_id, hardcover_id, edition_id, title, author],
            )
