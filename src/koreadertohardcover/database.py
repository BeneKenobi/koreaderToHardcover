import duckdb


class DatabaseManager:
    def __init__(self, db_path: str = "reading_stats.duckdb"):
        self.db_path = db_path
        self.conn = None

    def connect(self):
        """Establishes connection to the DuckDB database."""
        self.conn = duckdb.connect(self.db_path)
        self.create_schema()

    def close(self):
        """Closes the database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None

    def create_schema(self):
        """Creates the necessary database tables if they don't exist."""
        if not self.conn:
            raise RuntimeError("Database not connected")

        # Create books table
        self.conn.execute("""
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
        self.conn.execute("""
            CREATE SEQUENCE IF NOT EXISTS seq_reading_sessions_id
        """)

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS reading_sessions (
                id BIGINT PRIMARY KEY DEFAULT nextval('seq_reading_sessions_id'),
                book_id VARCHAR,
                page INTEGER,
                start_time TIMESTAMP,
                duration INTEGER, -- Seconds
                total_pages INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (book_id) REFERENCES books(id)
            )
        """)

        # Create book_mappings table (Hardcover specific adaptation)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS book_mappings (
                local_book_id VARCHAR PRIMARY KEY,
                hardcover_id VARCHAR,
                hardcover_slug VARCHAR,
                book_title VARCHAR,
                author VARCHAR,
                isbn VARCHAR,
                mapping_method VARCHAR,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (local_book_id) REFERENCES books(id)
            )
        """)

        # Indexes
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_books_updated_at ON books(updated_at)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_reading_sessions_book_id ON reading_sessions(book_id)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_reading_sessions_start_time ON reading_sessions(start_time)"
        )

    def get_connection(self):
        if not self.conn:
            self.connect()
        return self.conn

    def import_books(self, sqlite_path: str):
        """Imports books from a KOReader SQLite database."""
        if not self.conn:
            self.connect()

        self._attach_koreader(sqlite_path)
        try:
            self.conn.execute("""
                INSERT INTO books (
                    id, koreader_id, title, authors, series, language, 
                    total_pages, total_read_pages, total_read_time, highlights, notes,
                    last_open, status, sync_status, created_at, updated_at
                )
                SELECT 
                    md5 as id,
                    id as koreader_id,
                    title,
                    authors,
                    series,
                    language,
                    pages as total_pages,
                    total_read_pages,
                    total_read_time,
                    highlights,
                    notes,
                    to_timestamp(last_open) as last_open,
                    CASE 
                        WHEN pages > 0 AND (
                            (CAST(total_read_pages AS FLOAT) / CAST(pages AS FLOAT)) >= 0.98 OR
                            (pages - total_read_pages) <= 15
                        ) THEN 'finished'
                        ELSE 'reading'
                    END as status,
                    'pending' as sync_status,
                    now() as created_at,
                    now() as updated_at
                FROM koreader.book
                WHERE md5 IS NOT NULL AND md5 != ''
                ON CONFLICT (id) DO UPDATE SET
                    koreader_id = excluded.koreader_id,
                    title = excluded.title,
                    authors = excluded.authors,
                    series = excluded.series,
                    language = excluded.language,
                    total_pages = excluded.total_pages,
                    total_read_pages = excluded.total_read_pages,
                    total_read_time = excluded.total_read_time,
                    highlights = excluded.highlights,
                    notes = excluded.notes,
                    last_open = excluded.last_open,
                    status = excluded.status,
                    updated_at = now()
            """)
        finally:
            self._detach_koreader()

    def import_sessions(self, sqlite_path: str):
        """Imports reading sessions from a KOReader SQLite database."""
        if not self.conn:
            self.connect()

        self._attach_koreader(sqlite_path)
        try:
            self.conn.execute("""
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
            self._detach_koreader()

    def _attach_koreader(self, sqlite_path: str):
        try:
            self.conn.execute("INSTALL sqlite;")
            self.conn.execute("LOAD sqlite;")
        except Exception:
            pass
        try:
            self.conn.execute(f"ATTACH '{sqlite_path}' AS koreader (TYPE SQLITE)")
        except Exception as e:
            raise RuntimeError(f"Failed to attach SQLite database at {sqlite_path}: {e}")

    def _detach_koreader(self):
        try:
            self.conn.execute("DETACH koreader")
        except Exception:
            pass

    def get_book_mapping(self, local_id: str) -> Optional[str]:
        """Returns the hardcover_id for a given local book ID (MD5)."""
        if not self.conn:
            self.connect()
        row = self.conn.execute(
            "SELECT hardcover_id FROM book_mappings WHERE local_book_id = ?",
            [local_id]
        ).fetchone()
        return row[0] if row else None

    def save_book_mapping(self, local_id: str, hardcover_id: str, title: str = None, author: str = None):
        """Saves a mapping between a local book and Hardcover."""
        if not self.conn:
            self.connect()
        self.conn.execute("""
            INSERT INTO book_mappings (local_book_id, hardcover_id, book_title, author, mapping_method)
            VALUES (?, ?, ?, ?, 'manual')
            ON CONFLICT (local_book_id) DO UPDATE SET
                hardcover_id = excluded.hardcover_id,
                book_title = excluded.book_title,
                author = excluded.author,
                updated_at = now()
        """, [local_id, hardcover_id, title, author])