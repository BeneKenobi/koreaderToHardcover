# Dockerized Web Dashboard & Sync Server Plan

## 1. Project Dependencies
Update `pyproject.toml` to include the web stack:
*   **Web Framework:** `fastapi`, `uvicorn[standard]`
*   **Templating:** `jinja2`
*   **Forms/Data:** `python-multipart`
*   **Scheduling:** `apscheduler` (for background syncing)

## 2. Refactoring: `SyncEngine`
Extract core logic from `main.py` into a reusable `SyncEngine` class in `src/koreadertohardcover/engine.py`.
*   **Capabilities:**
    *   `ingest_from_webdav()`: Downloads DB (WebDAV) and imports to DuckDB.
    *   `ingest_from_local(path)`: Imports from local SQLite.
    *   `sync_progress()`: Pushes progress to Hardcover for *already mapped* books.
*   **Why:** Allows both CLI and Web Scheduler to use the same logic without duplication.

## 3. Web Server (`src/koreadertohardcover/web.py`)
Implement a FastAPI application:
*   **Dashboard (`/`)**: 
    *   Displays recent local books with status (Mapped/Unmapped, Last Read).
    *   Shows last sync time and status.
*   **Sync Endpoint (`POST /sync`)**: Manually triggers `SyncEngine`.
*   **Mapping Interface (`/map/{book_id}`)**:
    *   Search Hardcover API (using `HardcoverClient`).
    *   Select Book & Edition.
    *   Save mapping to local DuckDB.
*   **Background Scheduler**: 
    *   Uses `APScheduler` to run `SyncEngine` jobs.
    *   Configurable interval (env var `SYNC_INTERVAL_MINUTES`).
*   **UI/UX**:
    *   CSS Framework: **Milligram**.
    *   Color Palette: **Rosé Pine Moon** (https://rosepinetheme.com/palette/).

## 4. Dockerization
*   **`Dockerfile`**: Multi-stage build using `uv` (python:3.11-slim).
*   **`docker-compose.yml`**:
    *   Service: `koreadertohardcover`
    *   Volumes: Mount `reading_stats.duckdb` for persistence.
    *   Ports: Expose `8000`.
    *   Environment: `WEBDAV_URL`, `HARDCOVER_BEARER_TOKEN`, etc.

## 5. Integration
*   Refactor `main.py` (CLI) to use `SyncEngine`.
*   The web server will be the primary entry point for the Docker container.
