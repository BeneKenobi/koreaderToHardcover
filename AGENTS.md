# Project Context

This repository is a Dockerized web application and CLI tool that synchronizes reading progress from KOReader (via `statistics.sqlite3` fetched over WebDAV) to Hardcover.app.

## Development Environment & Commands

- **Package Manager:** `uv`
- **Language:** Python >= 3.11

### Setup & Installation
```bash
# Sync dependencies
uv sync
```

### Build & Run (Docker)
Always use `--build` to ensure code changes are picked up if not using watch mode.
```bash
# Production mode
docker compose up --build

# Development mode (Hot Reload)
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build --watch
```

### Linting & Formatting
We use `ruff` for both linting and formatting.
```bash
# Run checks and fix auto-fixable issues
uv run ruff check --fix .

# Format code
uv run ruff format .
```

### Testing
We use `pytest`. All tests are located in `tests/`.
```bash
# Run all tests
uv run pytest

# Run a single test file
uv run pytest tests/test_engine.py

# Run a specific test case (e.g., 'test_sync_logic' inside 'tests/test_engine.py')
uv run pytest tests/test_engine.py::test_sync_logic

# Run with verbose output
uv run pytest -v
```

## Code Style & Conventions

### General
- **Frameworks:** FastAPI (Web), Click (CLI), DuckDB (Data).
- **Architecture:** `SyncEngine` handles business logic; `web.py` and `main.py` are entry points.
- **Thread Safety:** DuckDB connections are **not** thread-safe. Always use transient connections via the context manager pattern (see Database section below).

### Formatting & Imports
- Follow PEP 8 guidelines.
- Use absolute imports for internal modules (e.g., `from koreadertohardcover.engine import SyncEngine`).
- Group imports: Standard Library, Third-party, Local Application.

### Naming
- **Variables/Functions:** snake_case (e.g., `fetch_koreader_db`, `sync_status`).
- **Classes:** PascalCase (e.g., `SyncEngine`, `DatabaseManager`).
- **Constants:** UPPER_CASE (e.g., `WEBDAV_URL`).

### Typing
- Use type hints for function arguments and return values.
- Import types from `typing` (e.g., `List`, `Tuple`, `Optional`, `Dict`).
```python
def sync_progress(self, limit: int = 10) -> List[Tuple[str, bool]]:
    ...
```

### Database Usage (DuckDB)
- **Pattern:** Never hold a persistent `self.conn` in class instances shared across threads (like `SyncEngine`).
- **Usage:** Use the `get_connection()` context manager.
```python
# CORRECT
with self.db.get_connection() as conn:
    conn.execute("SELECT * FROM books")

# INCORRECT
self.db.connect()
self.db.conn.execute(...)
```

### Logging
- **Configuration:** Only configure `logging.basicConfig` in entry point files (`web.py`, `main.py`). Do NOT configure it in library modules (`engine.py`, `database.py`).
- **Loggers:** In library files, use module-level loggers:
```python
logger = logging.getLogger(__name__)
```
- **Web App:** The web app uses `RotatingFileHandler` writing to `/data/app.log` (max 5MB, 3 backups) to prevent disk filling.

### Error Handling
- Use `try...except` blocks for external operations (WebDAV, Hardcover API, Database).
- Log errors with `logger.error(f"Context: {e}")`.
- Do not crash the application on sync failures; catch exceptions, log them, and return a failure status/boolean.

## Hardcover API
https://docs.hardcover.app/api/getting-started/
- **Testing:** Always test every change to the Hardcover API with `curl` using the bearer token from the `.env` file before implementing complex logic.
- **Rate Limits:** Be mindful of API rate limits; the `SyncEngine` processes books in batches (default limit=20).
