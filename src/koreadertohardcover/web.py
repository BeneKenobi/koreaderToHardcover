from fastapi import FastAPI, Request, Form, BackgroundTasks
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from apscheduler.schedulers.background import BackgroundScheduler
from contextlib import asynccontextmanager
import os
import logging
import datetime

from koreadertohardcover.engine import SyncEngine
from koreadertohardcover.config import Config
from koreadertohardcover.hardcover_client import HardcoverClient

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("web")

# Globals
config = Config()
# Ensure DB path is absolute if not already, or relative to cwd
db_path = os.getenv("DB_PATH", "reading_stats.duckdb")
engine = SyncEngine(db_path=db_path, config=config)
templates = Jinja2Templates(
    directory=os.path.join(os.path.dirname(__file__), "templates")
)

# Global Sync Status
sync_status = {
    "state": "idle",  # idle, running
    "last_run": None,
    "last_result": None,
}

# Scheduler
scheduler = BackgroundScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    sync_interval = int(os.getenv("SYNC_INTERVAL_MINUTES", "60"))
    logger.info(f"Starting scheduler with interval: {sync_interval} minutes")

    # Schedule periodic sync
    scheduler.add_job(scheduled_sync, "interval", minutes=sync_interval)
    scheduler.start()

    # Initial Ingest (if configured)
    if config.WEBDAV_URL:
        logger.info("Triggering initial ingestion...")
        scheduler.add_job(engine.ingest_from_webdav)

    yield

    # Shutdown
    scheduler.shutdown()


app = FastAPI(lifespan=lifespan)

# --- Helpers ---


def scheduled_sync():
    """Background task to ingest and sync."""
    global sync_status
    sync_status["state"] = "running"

    logger.info("Running scheduled sync...")
    try:
        if config.WEBDAV_URL:
            engine.ingest_from_webdav()
        engine.sync_progress(limit=20)
        sync_status["last_result"] = "Success"
    except Exception as e:
        logger.error(f"Sync failed: {e}")
        sync_status["last_result"] = f"Error: {str(e)}"
    finally:
        sync_status["state"] = "idle"
        sync_status["last_run"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    logger.info("Scheduled sync complete.")


# --- Routes ---


@app.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request, page: int = 1, message: str = None, message_type: str = None
):
    """Main Dashboard."""
    limit = 10
    offset = (page - 1) * limit

    books, total_count = engine.db.get_local_books(limit=limit, offset=offset)

    # Prepare book objects for template
    book_list = []
    for b in books:
        # b = (id, title, authors, last_open, is_mapped)
        book_list.append(
            {
                "id": b[0],
                "title": b[1],
                "author": b[2],
                # We need to fetch read pages / total pages for the progress bar
                # This requires a separate query or updating get_local_books to return more data
                # For now, let's just do a quick fetch or update the DB query later.
                # To keep it simple, I'll update get_local_books in database.py to return full objects
                # Or just fetch detail here.
                "last_read": b[3],
                "is_mapped": bool(b[4]),
                # Hack: We need read/total pages.
                # Let's just fetch it individually for now or update the main query.
                # Updating the main query is better but let's stick to existing for a sec.
            }
        )

    # Re-fetch with details for display (Efficiency improvement needed later)
    # Actually, let's just update the query in database.py to return what we need.
    # But I can't modify database.py right now in this step easily without context.
    # So I will fetch details manually.

    detailed_books = []
    conn = engine.db.get_connection()
    for b in book_list:
        row = conn.execute(
            "SELECT total_read_pages, total_pages, sync_status FROM books WHERE id = ?",
            [b["id"]],
        ).fetchone()
        if row:
            b["read_pages"] = row[0]
            b["total_pages"] = row[1]
            b["sync_status"] = row[2]
        else:
            b["read_pages"] = 0
            b["total_pages"] = 0
            b["sync_status"] = "unknown"
        detailed_books.append(b)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "books": detailed_books,
            "page": page,
            "limit": limit,
            "total_count": total_count,
            "message": message,
            "message_type": message_type,
            "sync_status": sync_status,
        },
    )


@app.post("/sync")
async def trigger_sync(background_tasks: BackgroundTasks):
    """Manual Sync Trigger."""
    background_tasks.add_task(scheduled_sync)
    return RedirectResponse(
        url="/?message=Sync+started+in+background&message_type=success", status_code=303
    )


@app.get("/map/{book_id}", response_class=HTMLResponse)
async def map_book_ui(request: Request, book_id: str):
    """Mapping Interface - Search."""
    conn = engine.db.get_connection()
    book = conn.execute(
        "SELECT title, authors, total_pages FROM books WHERE id = ?", [book_id]
    ).fetchone()

    if not book:
        return RedirectResponse(
            url="/?message=Book+not+found&message_type=error", status_code=303
        )

    book_obj = {
        "id": book_id,
        "title": book[0],
        "author": book[1],
        "total_pages": book[2],
    }

    return templates.TemplateResponse(
        "mapping.html", {"request": request, "book": book_obj, "query": None}
    )


@app.post("/map/{book_id}/search", response_class=HTMLResponse)
async def map_book_search(request: Request, book_id: str, query: str = Form(...)):
    """Handle Search."""
    conn = engine.db.get_connection()
    book = conn.execute(
        "SELECT title, authors, total_pages FROM books WHERE id = ?", [book_id]
    ).fetchone()
    book_obj = {
        "id": book_id,
        "title": book[0],
        "author": book[1],
        "total_pages": book[2],
    }

    hc = HardcoverClient(config)

    # 1. Search Shelf (if query matches title roughly) - Optional optimization
    # 2. Global Search
    results = hc.search_books(query)

    return templates.TemplateResponse(
        "mapping.html",
        {
            "request": request,
            "book": book_obj,
            "query": query,
            "search_results": results,
        },
    )


@app.post("/map/{book_id}/select", response_class=HTMLResponse)
async def map_book_select(
    request: Request,
    book_id: str,
    hardcover_id: str = Form(...),
    title: str = Form(...),
    author: str = Form(...),
):
    """Handle Book Selection -> Show Editions."""
    hc = HardcoverClient(config)

    conn = engine.db.get_connection()
    local_book = conn.execute(
        "SELECT total_pages FROM books WHERE id = ?", [book_id]
    ).fetchone()
    local_pages = local_book[0] if local_book else 0

    editions = hc.get_editions(int(hardcover_id))

    return templates.TemplateResponse(
        "editions.html",
        {
            "request": request,
            "book_id": book_id,
            "hardcover_id": hardcover_id,
            "title": title,
            "author": author,
            "local_pages": local_pages,
            "editions": editions,
        },
    )


@app.post("/map/{book_id}/confirm")
async def map_book_confirm(
    book_id: str,
    hardcover_id: str = Form(...),
    title: str = Form(...),
    author: str = Form(...),
    edition_id: str = Form(None),
):
    """Save the mapping."""
    engine.db.save_book_mapping(book_id, hardcover_id, edition_id, title, author)
    return RedirectResponse(
        url="/?message=Book+mapped+successfully&message_type=success", status_code=303
    )
