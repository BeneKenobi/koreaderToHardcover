from fastapi import (
    FastAPI,
    Request,
    Form,
    BackgroundTasks,
    Depends,
    HTTPException,
    status,
)
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
import os
import logging
from logging.handlers import RotatingFileHandler
import datetime
import secrets
import threading
import time

import duckdb

from koreadertohardcover.engine import (
    SyncEngine,
    effective_status,
    progress_percentage,
)
from koreadertohardcover.ranking import (
    FORMAT_GROUPS,
    rank_editions,
    rank_search_results,
)
from koreadertohardcover.config import Config
from koreadertohardcover.hardcover_client import HardcoverClient

# Ensure DB path is absolute if not already, or relative to cwd
db_path = os.getenv("DB_PATH", "reading_stats.duckdb")

# Configure Logging
# The log lives next to the database by default: the working directory may not be
# writable (the Docker image runs as an unprivileged user in a root-owned /app).
log_path = os.getenv("LOG_PATH") or str(Path(db_path).resolve().parent / "app.log")
file_handler = RotatingFileHandler(log_path, maxBytes=5 * 1024 * 1024, backupCount=3)
file_handler.setFormatter(
    logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
)

logging.basicConfig(
    level=logging.INFO,
    handlers=[logging.StreamHandler(), file_handler],
)
logger = logging.getLogger("web")
# httpx logs every request at INFO, which buries the sync output.
logging.getLogger("httpx").setLevel(logging.WARNING)

# Attach file handler to Uvicorn loggers to capture server logs in the file
logging.getLogger("uvicorn").addHandler(file_handler)
logging.getLogger("uvicorn.access").addHandler(file_handler)

# Globals
config = Config()
engine = SyncEngine(db_path=db_path, config=config)
templates = Jinja2Templates(
    directory=os.path.join(os.path.dirname(__file__), "templates")
)

# Hardcover username for the Profile link. Failed lookups are retried after a pause,
# so a Hardcover outage does not add an API call to every page view.
USERNAME_RETRY_SECONDS = 300
_username_cache: dict = {"value": None, "failed_at": None}


def hardcover_username() -> Optional[str]:
    if _username_cache["value"] or not config.HARDCOVER_BEARER_TOKEN:
        return _username_cache["value"]
    failed_at = _username_cache["failed_at"]
    if failed_at and time.monotonic() - failed_at < USERNAME_RETRY_SECONDS:
        return None

    hc = None
    try:
        hc = HardcoverClient(config)
        _username_cache["value"] = hc.get_me().get("username")
    except Exception as e:
        logger.error(f"Failed to fetch user info: {e}")
    finally:
        if hc:
            hc.close()
    if not _username_cache["value"]:
        _username_cache["failed_at"] = time.monotonic()
    return _username_cache["value"]


templates.env.globals["hardcover_username"] = hardcover_username

# Global Sync Status
sync_status = {
    "state": "idle",  # idle, running
    "last_run": None,
    "last_result": None,
}

# Held while a sync runs, so the scheduler and "Sync Now" never overlap.
sync_lock = threading.Lock()

# Scheduler
scheduler = BackgroundScheduler()

# Security
security = HTTPBasic()


def get_current_username(credentials: HTTPBasicCredentials = Depends(security)):
    """Verify Basic Auth credentials."""
    current_username_bytes = credentials.username.encode("utf8")
    correct_username_bytes = os.getenv("APP_USERNAME", "admin").encode("utf8")
    is_correct_username = secrets.compare_digest(
        current_username_bytes, correct_username_bytes
    )

    current_password_bytes = credentials.password.encode("utf8")
    correct_password_bytes = os.getenv("APP_PASSWORD", "admin").encode("utf8")
    is_correct_password = secrets.compare_digest(
        current_password_bytes, correct_password_bytes
    )

    if not (is_correct_username and is_correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    sync_interval = int(os.getenv("SYNC_INTERVAL_MINUTES", "60"))

    if sync_interval < 5:
        logger.warning(
            f"Configured sync interval ({sync_interval} min) is too low. Enforcing minimum of 5 minutes."
        )
        sync_interval = 5

    logger.info(f"Starting scheduler with interval: {sync_interval} minutes")

    # Calculate misfire grace time (interval - 1 minute) in seconds
    # Ensure strictly positive grace time
    grace_time_seconds = max((sync_interval - 1) * 60, 60)

    # Schedule periodic sync (run first one immediately)
    scheduler.add_job(
        scheduled_sync,
        "interval",
        minutes=sync_interval,
        id="scheduled_sync",
        next_run_time=datetime.datetime.now(),
        coalesce=True,
        misfire_grace_time=grace_time_seconds,
    )
    scheduler.start()

    db_error = engine.db.check_health()
    if db_error:
        logger.error(
            f"Database {db_path} is unreadable ({db_error}). "
            "Restore it from a backup or rebuild it from KOReader's statistics."
        )

    yield

    # Shutdown
    scheduler.shutdown()


def load_secret_key() -> str:
    """
    Returns SECRET_KEY from the environment. Without one, a key is generated once and
    stored next to the database, so sessions survive restarts.
    """
    env_key = os.getenv("SECRET_KEY")
    if env_key:
        return env_key

    key_path = Path(db_path).resolve().parent / "secret_key"
    try:
        if key_path.exists():
            return key_path.read_text().strip()
        key = secrets.token_hex(32)
        key_path.touch(mode=0o600)
        key_path.write_text(key)
        return key
    except OSError as e:
        logger.error(f"Could not persist secret key at {key_path}: {e}")
        return secrets.token_hex(32)


app = FastAPI(lifespan=lifespan, dependencies=[Depends(get_current_username)])
app.add_middleware(SessionMiddleware, secret_key=load_secret_key())


@app.middleware("http")
async def reject_cross_site_posts(request: Request, call_next):
    """
    Browsers send Basic Auth credentials with cross-site form posts, so a foreign
    page could trigger syncs or remap books. Reject POSTs whose Origin (or Referer)
    names a different host. Requests without either header are non-browser clients.
    """
    if request.method == "POST":
        source = request.headers.get("origin") or request.headers.get("referer")
        if source:
            expected_host = request.headers.get(
                "x-forwarded-host", request.headers.get("host")
            )
            if urlparse(source).netloc != expected_host:
                logger.warning(f"Rejected cross-site POST to {request.url.path}")
                return HTMLResponse("Cross-site request rejected", status_code=403)
    return await call_next(request)


@app.exception_handler(duckdb.Error)
async def database_error_handler(request: Request, exc: duckdb.Error):
    """Shows a readable 503 instead of a stack trace when the DuckDB file is damaged."""
    logger.error(f"Database error on {request.url.path}: {exc}")
    return HTMLResponse(
        "<h1>Database unavailable</h1>"
        "<p>The reading-stats database could not be read. Check the application log, "
        "then restore it from a backup or rebuild it.</p>",
        status_code=503,
    )


# --- Helpers ---


def summarize_sync(
    ingest_ok: Optional[bool], results: Optional[list[tuple[str, bool]]]
) -> str:
    """Builds the dashboard result text. Anything that failed starts with 'Error'."""
    errors = []
    if ingest_ok is False:
        errors.append("WebDAV ingestion failed")
    if results is None:
        errors.append("Hardcover sync failed")
    else:
        failed = [title for title, ok in results if not ok]
        if failed:
            errors.append(f"{len(failed)} of {len(results)} books failed to sync")
    if errors:
        return "Error: " + "; ".join(errors) + " (see logs)"
    return f"Success ({len(results or [])} books checked)"


def scheduled_sync():
    """Background task to ingest and sync."""
    if not sync_lock.acquire(blocking=False):
        logger.info("Sync already running, skipping this run.")
        return

    sync_status["state"] = "running"
    logger.info("Running scheduled sync...")
    try:
        ingest_ok = engine.ingest_from_webdav() if config.WEBDAV_URL else None
        results = engine.sync_progress(limit=20)
        sync_status["last_result"] = summarize_sync(ingest_ok, results)
    except Exception as e:
        logger.error(f"Sync failed: {e}")
        sync_status["last_result"] = f"Error: {str(e)}"
    finally:
        sync_status["state"] = "idle"
        sync_status["last_run"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sync_lock.release()

    logger.info(f"Scheduled sync complete: {sync_status['last_result']}")


def fetch_book(book_id: str) -> Optional[dict]:
    with engine.db.get_connection() as conn:
        row = conn.execute(
            "SELECT title, authors, total_pages, language FROM books WHERE id = ?",
            [book_id],
        ).fetchone()
    if not row:
        return None
    # KOReader separates several authors with newlines.
    first_author = (row[1] or "").split("\n")[0].strip()
    return {
        "id": book_id,
        "title": row[0],
        "author": row[1],
        "total_pages": row[2],
        "language": row[3],
        "default_query": f"{row[0]} {first_author}".strip(),
    }


def parse_page(value: Optional[str]) -> int:
    try:
        return max(int(value or 1), 1)
    except ValueError:
        return 1


# --- Routes ---


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, page: Optional[str] = None, q: Optional[str] = None):
    """Main Dashboard."""
    message = request.session.pop("message", None)
    message_type = request.session.pop("message_type", None)
    sync_started = request.session.pop("sync_started", False)

    page_number = parse_page(page)
    query = (q or "").strip() or None
    limit = 10
    offset = (page_number - 1) * limit

    books, total_count = engine.db.get_local_books(
        query=query, limit=limit, offset=offset
    )

    book_list = []
    for b in books:
        # Same numbers the sync sends to Hardcover.
        progress = progress_percentage(b[7], b[10], b[8])
        book_list.append(
            {
                "id": b[0],
                "title": b[1],
                "author": b[2],
                "last_read": b[3],
                "is_mapped": bool(b[4]),
                "hardcover_slug": b[5],
                "hardcover_id": b[6],
                "progress": progress,
                "sync_status": b[9],
                "status": effective_status(b[11], progress),
            }
        )

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "books": book_list,
            "page": page_number,
            "limit": limit,
            "total_count": total_count,
            "query": query,
            "message": message,
            "message_type": message_type,
            "sync_status": sync_status,
            "sync_started": sync_started,
        },
    )


@app.get("/status")
def get_sync_status() -> JSONResponse:
    """Sync state for the dashboard's live status badge."""
    return JSONResponse(sync_status)


@app.post("/sync")
async def trigger_sync(request: Request, background_tasks: BackgroundTasks):
    """Manual Sync Trigger."""
    if sync_lock.locked():
        request.session["message"] = "A sync is already running"
        request.session["message_type"] = "error"
    else:
        background_tasks.add_task(scheduled_sync)
        request.session["sync_started"] = True
        request.session["message"] = "Sync started in background"
        request.session["message_type"] = "success"
    return RedirectResponse(url="/", status_code=303)


@app.get("/logs", response_class=HTMLResponse)
def view_logs(request: Request):
    """View application logs."""
    if os.path.exists(log_path):
        with open(log_path, "r") as f:
            # Efficiently read last lines would be better for huge files,
            # but for now standard readlines is okay for a simple tool
            lines = f.readlines()
            recent_logs = "".join(reversed(lines[-1000:]))
    else:
        recent_logs = "No logs found."

    return templates.TemplateResponse(request, "logs.html", {"logs": recent_logs})


def render_search(request: Request, book_obj: dict, query: str) -> HTMLResponse:
    hc = HardcoverClient(config)
    error = None
    results: list = []
    try:
        results = hc.search_books(query)
        shelf_ids = hc.shelf_book_ids([int(r["id"]) for r in results])
        results = rank_search_results(results, shelf_ids)
    except Exception as e:
        logger.error(f"Hardcover search for '{query}' failed: {e}")
        error = "Hardcover search failed. Check the logs."
    finally:
        hc.close()

    return templates.TemplateResponse(
        request,
        "mapping.html",
        {
            "book": book_obj,
            "query": query,
            "search_results": results,
            "error": error,
        },
    )


@app.get("/map/{book_id}", response_class=HTMLResponse)
def map_book_ui(request: Request, book_id: str):
    """Mapping Interface - searches for the book right away."""
    book_obj = fetch_book(book_id)
    if not book_obj:
        request.session["message"] = "Book not found"
        request.session["message_type"] = "error"
        return RedirectResponse(url="/", status_code=303)

    return render_search(request, book_obj, book_obj["default_query"])


@app.post("/map/{book_id}/search", response_class=HTMLResponse)
def map_book_search(request: Request, book_id: str, query: str = Form(...)):
    """Handle Search."""
    book_obj = fetch_book(book_id)
    if not book_obj:
        raise HTTPException(status_code=404, detail="Book not found")

    return render_search(request, book_obj, query)


@app.post("/map/{book_id}/select", response_class=HTMLResponse)
def map_book_select(
    request: Request,
    book_id: str,
    hardcover_id: int = Form(...),
    title: str = Form(...),
    author: str = Form(...),
    slug: str = Form(None),
):
    """Handle Book Selection -> Show Editions."""
    book_obj = fetch_book(book_id)
    if not book_obj:
        raise HTTPException(status_code=404, detail="Book not found")

    hc = HardcoverClient(config)
    try:
        editions = hc.get_editions(hardcover_id)
    finally:
        hc.close()
    editions = rank_editions(editions, book_obj["language"], book_obj["total_pages"])

    return templates.TemplateResponse(
        request,
        "editions.html",
        {
            "book": book_obj,
            "book_id": book_id,
            "hardcover_id": hardcover_id,
            "title": title,
            "author": author,
            "slug": slug,
            "local_pages": book_obj["total_pages"] or 0,
            "editions": editions,
            "languages": sorted({e["language"] for e in editions}),
            "facets": [
                {"language": e["language"], "group": e["format_group"]}
                for e in editions
            ],
            "format_groups": [
                {"name": group, "count": count}
                for group in FORMAT_GROUPS
                if (count := sum(e["format_group"] == group for e in editions))
            ],
        },
    )


@app.post("/map/{book_id}/confirm")
def map_book_confirm(
    request: Request,
    book_id: str,
    hardcover_id: int = Form(...),
    title: str = Form(...),
    author: str = Form(...),
    slug: str = Form(None),
    edition_id: Optional[int] = Form(None),
):
    """Save the mapping."""
    if not fetch_book(book_id):
        raise HTTPException(status_code=404, detail="Book not found")

    engine.db.save_book_mapping(
        book_id,
        str(hardcover_id),
        str(edition_id) if edition_id is not None else None,
        title,
        author,
        slug,
    )
    request.session["message"] = "Book mapped successfully"
    request.session["message_type"] = "success"
    return RedirectResponse(url="/", status_code=303)
