# Plan: Interactive Map Command with Book Browser

## Goal
Implement a `map` CLI command that allows users to manually map local KOReader books to Hardcover editions. The command supports searching and a paginated "browser" view for local books, sorted by most recently read.

## Dependencies
- [x] Add `rich` for terminal UI (tables, colored status).

## Components

### 1. Database (`src/koreadertohardcover/database.py`)
- [x] **Method**: `get_local_books(query: str = None, limit: int = 10, offset: int = 0)`
    - **Query**: Optional `ILIKE` filter on title.
    - **Sort**: `ORDER BY last_open DESC NULLS LAST` (newest/most recently read first).
    - **Join**: `LEFT JOIN book_mappings` to get mapping status (mapped/unmapped).
    - **Return**: List of books (with status) and total count.

### 2. Interactive Mapper (`src/koreadertohardcover/mapping.py`)
- [x] **Update `map_book`**:
    - Add `force: bool = False` parameter.
    - If `force` is True, skip "already mapped" check and allow re-mapping.
    - Use `rich` for output consistency.

### 3. CLI (`src/koreadertohardcover/main.py`)
- [x] **Command**: `map [QUERY]`
- [x] **Logic**:
    - If `QUERY` is provided and yields 1 exact match (and not forcing browser), jump to mapping.
    - Otherwise (or if no query), enter **Browser Mode**.
- [x] **Browser Mode**:
    - Use `rich.table.Table` to display 10 books.
    - **Columns**: Index (1-10), Title, Author, Last Read, Status (Mapped/Unmapped).
    - **Pagination**: Handle `limit`/`offset`.
    - **Prompt**:
        - `1-10`: Select book -> Call `map_book(..., force=True)`.
        - `n`: Next page.
        - `p`: Previous page.
        - `q`: Quit.

## Tests
- [x] **Unit Tests**:
    - Test `get_local_books` with and without query, with pagination, and sorting.
    - Test `map_book` honors `force=True`.
- [ ] **Manual Verification**:
    - `koreadertohardcover map` -> Verify browser lists books, sorted by date, with correct status.
    - `koreadertohardcover map "dune"` -> Verify search filtering.
    - Select a book -> Verify mapping flow starts and updates database.
