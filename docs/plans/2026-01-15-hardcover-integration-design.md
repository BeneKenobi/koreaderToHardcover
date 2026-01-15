# Hardcover Integration Design

**Goal:** Synchronize reading progress and status from local KOReader data to Hardcover.app via their GraphQL API.

## Architecture

The integration follows a client-server pattern where the local CLI acts as a coordinator between the DuckDB cache and the Hardcover GraphQL API.

### Components
- **`HardcoverClient`**: A new class in `src/koreadertohardcover/hardcover_client.py` using `httpx` to handle all API communication.
- **`MappingManager`**: Logic to handle book discovery and persistent mapping between KOReader MD5s and Hardcover IDs.
- **`SyncCoordinator`**: Integrated into `main.py`, manages the selection of books (via `--past` parameter) and orchestrates the mapping/sync flow.

## Data Flow

1. **Selection**: Query `books` table for the top `N` books (default 2, configurable via `--past`) sorted by `last_open` DESC.
2. **Mapping**: 
   - Check `book_mappings` for an existing entry.
   - If missing:
     - Search Hardcover API for "Title Author".
     - Present matches to user via `click.prompt`.
     - Save selection to `book_mappings`.
3. **Sync**:
   - Calculate percentage: `(total_read_pages / total_pages) * 100`.
   - Determine status: `finished` (mapped to `Read`) or `reading` (mapped to `Currently Reading`).
   - Execute GraphQL mutation to update status and progress.
   - Update `sync_status` and `updated_at` in local DB.

## API Integration Detail

- **Authentication**: Bearer token via `HARDCOVER_API_KEY` in `.env`.
- **Progress**: Always sent as a **percentage** to ensure compatibility across different editions.
- **Status**: 
    - `reading` -> `Currently Reading`
    - `finished` -> `Read`
- **Re-reads**: Not explicitly handled in V1; syncing a previously read book will update the current status/progress.

## Schema Updates
- The `books` table already has `sync_status` and `sync_error`.
- The `book_mappings` table already exists to store persistence.

## Error Handling
- **API Errors**: Logged to `sync_error` column; CLI reports failure but continues with the next book.
- **Non-interactive**: If mapping is required but no TTY is available, skip the book.

## Testing Strategy
- Mock `httpx` responses for search and mutation calls.
- Verify mapping persistence in a temporary DuckDB.
- Unit tests for percentage calculation and status mapping.
