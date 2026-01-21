import os
import tempfile
import logging
from typing import Optional, List, Tuple
from koreadertohardcover.database import DatabaseManager
from koreadertohardcover.config import Config
from koreadertohardcover.webdav_client import fetch_koreader_db
from koreadertohardcover.hardcover_client import HardcoverClient

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class SyncEngine:
    def __init__(self, db_path: str = "reading_stats.duckdb", config: Config = None):
        self.db_path = db_path
        self.db = DatabaseManager(db_path)
        self.config = config or Config()

    def ingest_from_webdav(self) -> bool:
        """
        Fetches the SQLite database from WebDAV and ingests it into DuckDB.
        Returns True if successful, False otherwise.
        """
        if not self.config.WEBDAV_URL:
            logger.error("WEBDAV_URL is not set.")
            return False

        # Create a temp file to download the database to
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(tmp_fd)

        try:
            logger.info(f"Fetching database from WebDAV: {self.config.WEBDAV_URL}...")
            fetch_koreader_db(self.config, tmp_path)

            logger.info("Ingesting data from fetched SQLite DB...")
            self.db.connect()
            self.db.import_books(tmp_path)
            self.db.import_sessions(tmp_path)
            logger.info("Ingestion complete.")
            return True
        except Exception as e:
            logger.error(f"Failed to fetch or ingest database: {e}")
            return False
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

    def ingest_from_local(self, sqlite_path: str) -> bool:
        """
        Ingests data from a local SQLite database file.
        """
        if not os.path.exists(sqlite_path):
            logger.error(f"Local file not found: {sqlite_path}")
            return False

        try:
            logger.info(f"Ingesting data from local file: {sqlite_path}...")
            self.db.connect()
            self.db.import_books(sqlite_path)
            self.db.import_sessions(sqlite_path)
            logger.info("Ingestion complete.")
            return True
        except Exception as e:
            logger.error(f"Failed to ingest database: {e}")
            return False

    def sync_progress(
        self, limit: int = 10, force: bool = False
    ) -> List[Tuple[str, bool]]:
        """
        Syncs the reading progress of recently read, mapped books to Hardcover.
        Returns a list of (book_title, success_boolean) tuples.
        """
        if not self.config.HARDCOVER_BEARER_TOKEN:
            logger.warning("HARDCOVER_BEARER_TOKEN not set. Skipping Hardcover sync.")
            return []

        results = []
        hc = HardcoverClient(self.config)

        try:
            self.db.connect()
            conn = self.db.get_connection()

            # Fetch recent books that are mapped
            # We select books, verify they have a mapping, and then sync
            sql = """
                SELECT 
                    b.id, b.title, b.authors, b.total_read_pages, b.total_pages, 
                    b.status, b.total_read_time, b.last_open,
                    m.hardcover_id, m.edition_id,
                    (SELECT MIN(start_time) FROM reading_sessions rs WHERE rs.book_id = b.id) as start_date
                FROM books b
                JOIN book_mappings m ON b.id = m.local_book_id
                ORDER BY b.last_open DESC
                LIMIT ?
            """

            recent_books = conn.execute(sql, [limit]).fetchall()
            logger.info(f"Found {len(recent_books)} mapped books to check for sync.")

            for (
                b_id,
                title,
                authors,
                read_pg,
                total_pg,
                status,
                read_time,
                last_open,
                hc_id,
                edition_id,
                start_date,
            ) in recent_books:
                percentage = (read_pg / total_pg * 100) if total_pg > 0 else 0
                logger.info(f"Syncing '{title}' (ID: {hc_id}) - {percentage:.1f}%")

                success = hc.update_progress(
                    hc_id,
                    percentage,
                    status,
                    seconds=read_time,
                    last_read_date=last_open,
                    start_date=start_date,
                    force=force,
                    edition_id=edition_id,
                )

                if success:
                    conn.execute(
                        "UPDATE books SET sync_status = 'synced', updated_at = now() WHERE id = ?",
                        [b_id],
                    )

                results.append((title, success))

        except Exception as e:
            logger.error(f"Error during sync: {e}")

        return results
