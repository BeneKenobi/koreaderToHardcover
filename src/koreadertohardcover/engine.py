import os
import tempfile
import logging
import math
from typing import Any, Dict, List, Optional, Tuple
from koreadertohardcover.database import DatabaseManager
from koreadertohardcover.config import Config
from koreadertohardcover.webdav_client import fetch_koreader_db
from koreadertohardcover.hardcover_client import HardcoverClient

logger = logging.getLogger(__name__)


def progress_percentage(
    read_pages: Optional[int], max_page: Optional[int], total_pages: Optional[int]
) -> int:
    """
    Reading progress as a ceiled integer percentage.
    Uses the furthest page reached if it is ahead of the read-page count, which
    matches KOReader's UI (99% position vs 97% count).
    """
    read_pages = read_pages or 0
    total_pages = total_pages or 0
    if total_pages <= 0:
        return 0
    current = max_page if max_page and max_page > read_pages else read_pages
    return math.ceil(current / total_pages * 100)


def effective_status(status: Optional[str], percentage: int) -> str:
    """The status sent to Hardcover: 'finished' from 98% on, else the local status."""
    if percentage >= 98:
        return "finished"
    return status or "reading"


def _date_key(value: Any) -> str:
    """Date part of a timestamp, as a string, for comparing sync state."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value[:10]
    return value.strftime("%Y-%m-%d")


def _fingerprint(
    hardcover_id: str,
    edition_id: Optional[str],
    percentage: int,
    status: str,
    seconds: int,
    start_date: Any,
    last_read_date: Any,
) -> str:
    """
    Everything that decides what gets sent to Hardcover, as one comparable string.
    Reading time is rounded to whole minutes, because HardcoverClient treats a
    smaller difference as unchanged anyway.
    """
    return "|".join(
        [
            str(hardcover_id),
            str(edition_id or ""),
            str(percentage),
            status,
            str((seconds or 0) // 60),
            _date_key(start_date),
            _date_key(last_read_date) if status == "finished" else "",
        ]
    )


class SyncEngine:
    def __init__(
        self, db_path: str = "reading_stats.duckdb", config: Optional[Config] = None
    ):
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
            self.db.import_books(tmp_path)
            self.db.import_sessions(tmp_path)
            self.db.checkpoint()
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
            self.db.import_books(sqlite_path)
            self.db.import_sessions(sqlite_path)
            self.db.checkpoint()
            logger.info("Ingestion complete.")
            return True
        except Exception as e:
            logger.error(f"Failed to ingest database: {e}")
            return False

    def sync_progress(
        self, limit: int = 10, force: bool = False
    ) -> Optional[List[Tuple[str, bool]]]:
        """
        Syncs the reading progress of recently read, mapped books to Hardcover.
        Returns a list of (book_title, success_boolean) tuples, or None if the
        sync could not run at all.
        """
        if not self.config.HARDCOVER_BEARER_TOKEN:
            logger.warning("HARDCOVER_BEARER_TOKEN not set. Skipping Hardcover sync.")
            return []

        results = []
        hc = HardcoverClient(self.config)

        try:
            with self.db.get_connection() as conn:
                # Fetch recent books that are mapped
                # We select books, verify they have a mapping, and then sync
                sql = """
                    SELECT 
                        b.id, b.title, b.authors, b.total_read_pages, b.total_pages, 
                        b.status, b.total_read_time, b.last_open,
                        m.hardcover_id, m.edition_id, s.fingerprint,
                        (SELECT MIN(start_time) FROM reading_sessions rs WHERE rs.book_id = b.id) as start_date,
                        (SELECT MAX(start_time) FROM reading_sessions rs WHERE rs.book_id = b.id) as last_session_date,
                        (SELECT MAX(page) FROM reading_sessions rs WHERE rs.book_id = b.id) as max_page
                    FROM books b
                    JOIN book_mappings m ON b.id = m.local_book_id
                    LEFT JOIN sync_state s ON b.id = s.local_book_id
                    ORDER BY b.last_open DESC
                    LIMIT ?
                """

                cursor = conn.execute(sql, [limit])
                columns = [col[0] for col in cursor.description]
                recent_books = [dict(zip(columns, row)) for row in cursor.fetchall()]
                logger.info(
                    f"Found {len(recent_books)} mapped books to check for sync."
                )

                for book in recent_books:
                    title = book["title"]
                    try:
                        success = self._sync_book(hc, conn, book, force)
                    except Exception as e:
                        # One broken book must not stop the others from syncing.
                        logger.error(
                            f"Failed to sync '{title}' (ID: {book['hardcover_id']}): {e}"
                        )
                        success = False

                    results.append((title, success))

        except Exception as e:
            logger.error(f"Error during sync: {e}")
            return None
        else:
            self._backfill_covers(hc)
        finally:
            hc.close()

        return results

    def _backfill_covers(self, hc: HardcoverClient) -> None:
        """
        Looks up cover URLs for mappings that have none yet, in one request.
        Prefers the edition's cover and falls back to the book's.
        """
        try:
            missing = self.db.get_mappings_without_cover()
            if not missing:
                return
            book_ids = sorted({int(hc_id) for _, hc_id, _ in missing})
            edition_ids = sorted({int(ed_id) for _, _, ed_id in missing if ed_id})
            book_urls, edition_urls = hc.get_cover_urls(book_ids, edition_ids)

            covers = {}
            for local_id, hc_id, edition_id in missing:
                url = edition_urls.get(int(edition_id)) if edition_id else None
                # '' marks "no cover on Hardcover", so the book is not asked again.
                covers[local_id] = url or book_urls.get(int(hc_id)) or ""
            self.db.save_cover_urls(covers)
            logger.info(f"Fetched cover URLs for {len(covers)} mapped books.")
        except Exception as e:
            # Covers are cosmetic; never fail the sync because of them.
            logger.error(f"Failed to fetch cover URLs: {e}")

    def _sync_book(
        self, hc: HardcoverClient, conn: Any, book: Dict[str, Any], force: bool
    ) -> bool:
        """Syncs one book. Returns True if Hardcover holds the local state."""
        b_id = book["id"]
        title = book["title"]
        hc_id = book["hardcover_id"]
        edition_id = book["edition_id"]
        start_date = book["start_date"]
        percentage = progress_percentage(
            book["total_read_pages"], book["max_page"], book["total_pages"]
        )
        status = effective_status(book["status"], percentage)
        read_time = book["total_read_time"] or 0

        # Use last_session_date if available, otherwise fallback to last_open
        # This ensures we use the actual reading time instead of just file open time
        effective_last_read = book["last_session_date"] or book["last_open"]

        fingerprint = _fingerprint(
            hc_id,
            edition_id,
            percentage,
            status,
            read_time,
            start_date,
            effective_last_read,
        )

        # Nothing changed since the last successful sync, so Hardcover
        # already holds this state. Asking it again costs two API calls.
        if not force and book["fingerprint"] == fingerprint:
            logger.info(
                f"Skipping '{title}' (ID: {hc_id}) - unchanged since last sync."
            )
            return True

        logger.info(
            f"Syncing '{title}' (ID: {hc_id}) - Status: {status} - {percentage}%"
        )

        success = hc.update_progress(
            hc_id,
            percentage,
            status,
            seconds=read_time,
            last_read_date=effective_last_read,
            start_date=start_date,
            force=force,
            edition_id=edition_id,
        )

        if success:
            conn.execute(
                "UPDATE books SET sync_status = 'synced', updated_at = now() "
                "WHERE id = ? AND sync_status IS DISTINCT FROM 'synced'",
                [b_id],
            )
            conn.execute(
                "INSERT INTO sync_state (local_book_id, fingerprint, synced_at) "
                "VALUES (?, ?, now()) ON CONFLICT (local_book_id) DO UPDATE "
                "SET fingerprint = excluded.fingerprint, synced_at = excluded.synced_at",
                [b_id, fingerprint],
            )
        return success
