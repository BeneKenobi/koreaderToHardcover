import logging
from typing import Optional

import duckdb

logger = logging.getLogger(__name__)

TABLES = ("books", "reading_sessions", "book_mappings", "sync_state")

# A book counts as finished once almost every page was read. Up to 15 unread pages
# are tolerated for back matter, but only when at least 90% was read, so short or
# skimmed books are not marked finished right after opening them.
FINISHED_CASE_SQL = """
    CASE
        WHEN pages > 0 AND (
            CAST(total_read_pages AS DOUBLE) / pages >= 0.98 OR (
                pages - total_read_pages <= 15
                AND CAST(total_read_pages AS DOUBLE) / pages >= 0.9
            )
        ) THEN 'finished'
        ELSE 'reading'
    END
"""

# KOReader keys its book table on (title, authors, md5), so one file can have
# several rows, e.g. after a metadata edit. Keep the most recently opened one.
KOREADER_BOOKS_SQL = f"""
    SELECT *, {FINISHED_CASE_SQL} AS new_status
    FROM koreader.book
    WHERE md5 IS NOT NULL AND md5 != ''
    QUALIFY row_number() OVER (
        PARTITION BY md5 ORDER BY last_open DESC NULLS LAST, id DESC
    ) = 1
"""


class DatabaseManager:
    def __init__(self, db_path: str = "reading_stats.duckdb"):
        self.db_path = db_path
        self.init_error: Optional[str] = None
        try:
            self.create_schema()
        except duckdb.Error as e:
            # A damaged file must not take the whole app down; check_health() reports it.
            self.init_error = str(e)
            logger.error(f"Failed to initialize database {db_path}: {e}")

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

            # What was last sent to Hardcover, so unchanged books can be skipped
            # without querying the API.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sync_state (
                    local_book_id VARCHAR PRIMARY KEY,
                    fingerprint VARCHAR,
                    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Indexes
            # An index on books.updated_at turns every UPDATE into DELETE+INSERT, which
            # appends a new row group per sync and bloats the file. Drop it from old DBs.
            conn.execute("DROP INDEX IF EXISTS idx_books_updated_at")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reading_sessions_book_id ON reading_sessions(book_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reading_sessions_start_time ON reading_sessions(start_time)"
            )

    def check_health(self) -> Optional[str]:
        """Returns None if all tables are readable, otherwise an error description."""
        if self.init_error:
            return self.init_error
        try:
            with self.get_connection() as conn:
                for table in TABLES:
                    # Reads the column metadata of every segment, which is what breaks
                    # when the checkpointed file is damaged.
                    conn.execute(
                        f"SELECT count(*) FROM pragma_storage_info('{table}')"
                    ).fetchone()
                    conn.execute(f"SELECT count(*) FROM {table}").fetchone()
            return None
        except duckdb.Error as e:
            logger.error(f"Database health check failed: {e}")
            return str(e)

    def checkpoint(self) -> bool:
        """Flushes the WAL into the main database file."""
        try:
            with self.get_connection() as conn:
                conn.execute("CHECKPOINT")
            return True
        except duckdb.Error as e:
            logger.error(f"Checkpoint failed: {e}")
            return False

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
                    m.hardcover_id,
                    b.total_read_pages,
                    b.total_pages,
                    b.sync_status,
                    (SELECT MAX(page) FROM reading_sessions rs WHERE rs.book_id = b.id) AS max_page
                FROM books b
                LEFT JOIN book_mappings m ON b.id = m.local_book_id
                {where_clause}
                ORDER BY b.last_open DESC NULLS LAST
                LIMIT ? OFFSET ?
            """

            books = conn.execute(sql, params + [limit, max(offset, 0)]).fetchall()
            return books, total

    def import_books(self, sqlite_path: str):
        """Imports books from a KOReader SQLite database."""
        with self.get_connection() as conn:
            self._attach_koreader(conn, sqlite_path)
            try:
                # 1. Update existing books, but only rows whose values actually changed.
                # Rewriting unchanged rows every sync bloats the file (see create_schema).
                conn.execute(f"""
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
                        status = k.new_status,
                        updated_at = now()
                    FROM ({KOREADER_BOOKS_SQL}) k
                    WHERE books.id = k.md5
                    AND (
                        books.koreader_id IS DISTINCT FROM k.id OR
                        books.title IS DISTINCT FROM k.title OR
                        books.authors IS DISTINCT FROM k.authors OR
                        books.series IS DISTINCT FROM k.series OR
                        books.language IS DISTINCT FROM k.language OR
                        books.total_pages IS DISTINCT FROM k.pages OR
                        books.total_read_pages IS DISTINCT FROM k.total_read_pages OR
                        books.total_read_time IS DISTINCT FROM k.total_read_time OR
                        books.highlights IS DISTINCT FROM k.highlights OR
                        books.notes IS DISTINCT FROM k.notes OR
                        books.last_open IS DISTINCT FROM to_timestamp(k.last_open) OR
                        books.status IS DISTINCT FROM k.new_status
                    )
                """)

                # 2. Insert new books
                conn.execute(f"""
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
                        k.new_status,
                        'pending',
                        now(),
                        now()
                    FROM ({KOREADER_BOOKS_SQL}) k
                    WHERE NOT EXISTS (SELECT 1 FROM books b WHERE b.id = k.md5)
                """)
            finally:
                self._detach_koreader(conn)

    def import_sessions(self, sqlite_path: str):
        """Imports reading sessions from a KOReader SQLite database."""
        with self.get_connection() as conn:
            self._attach_koreader(conn, sqlite_path)
            try:
                # IDs are assigned explicitly: the sequence state is not reliably
                # persisted across short-lived connections and can lag behind max(id).
                conn.execute("""
                    INSERT INTO reading_sessions (
                        id, book_id, page, start_time, duration, total_pages
                    )
                    SELECT 
                        (SELECT coalesce(max(id), 0) FROM reading_sessions)
                            + row_number() OVER (ORDER BY b.md5, psd.start_time),
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
                    -- Duplicate book rows for one md5 can carry the same session.
                    QUALIFY row_number() OVER (
                        PARTITION BY b.md5, psd.start_time ORDER BY psd.page DESC
                    ) = 1
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
            escaped_path = sqlite_path.replace("'", "''")
            conn.execute(f"ATTACH '{escaped_path}' AS koreader (TYPE SQLITE)")
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
        slug: str = None,
    ):
        """Saves a mapping between a local book and Hardcover."""
        with self.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO book_mappings (local_book_id, hardcover_id, edition_id, book_title, author, hardcover_slug, mapping_method)
                VALUES (?, ?, ?, ?, ?, ?, 'manual')
                ON CONFLICT (local_book_id) DO UPDATE SET
                    hardcover_id = excluded.hardcover_id,
                    edition_id = excluded.edition_id,
                    book_title = excluded.book_title,
                    author = excluded.author,
                    hardcover_slug = excluded.hardcover_slug,
                    updated_at = now()
            """,
                [local_id, hardcover_id, edition_id, title, author, slug],
            )
