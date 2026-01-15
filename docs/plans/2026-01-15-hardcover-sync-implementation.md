# Hardcover Sync Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement the GraphQL integration with Hardcover.app to sync book progress and status.

**Architecture:** Extend `Config`, create a `HardcoverClient` using `httpx`, implement interactive mapping logic, and update the CLI `sync` command.

**Tech Stack:** httpx, click, pytest, duckdb

---

### Task 1: Configuration & Dependencies

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/koreadertohardcover/config.py`
- Modify: `tests/test_config.py`

**Step 1: Add httpx**
Run: `uv add httpx`

**Step 2: Update Config class**
Add `HARDCOVER_BEARER_TOKEN` to `src/koreadertohardcover/config.py`:
```python
class Config:
    def __init__(self):
        # ... existing ...
        self.HARDCOVER_BEARER_TOKEN = os.getenv("HARDCOVER_BEARER_TOKEN")
```

**Step 3: Update tests**
Verify `HARDCOVER_BEARER_TOKEN` is loaded in `tests/test_config.py`.

**Step 4: Commit**
```bash
git add pyproject.toml uv.lock src/koreadertohardcover/config.py tests/test_config.py
git commit -m "chore: add httpx and Hardcover config"
```

---

### Task 2: Implement Hardcover Client (Search & Update)

**Files:**
- Create: `src/koreadertohardcover/hardcover_client.py`
- Create: `tests/test_hardcover_client.py`

**Step 1: Write tests for Search and Mutation**
Create `tests/test_hardcover_client.py` with mocked `httpx` responses.

**Step 2: Implement HardcoverClient**
Create `src/koreadertohardcover/hardcover_client.py`:
- `search_books(query: str)`: GraphQL search.
- `update_progress(book_id: str, percentage: float, status: str)`: GraphQL mutation.

**Step 3: Verify tests pass**
Run: `uv run pytest tests/test_hardcover_client.py -v`

**Step 4: Commit**
```bash
git add src/koreadertohardcover/hardcover_client.py tests/test_hardcover_client.py
git commit -m "feat: implement Hardcover GraphQL client"
```

---

### Task 3: Interactive Mapping Logic

**Files:**
- Modify: `src/koreadertohardcover/database.py`
- Create: `src/koreadertohardcover/mapping.py`

**Step 1: Add mapping persistence**
In `database.py`, add `get_mapping(local_id)` and `save_mapping(local_id, remote_id)`.

**Step 2: Implement Interactive Mapper**
In `src/koreadertohardcover/mapping.py`, implement a function that:
- Calls `hardcover_client.search_books`.
- Uses `click.prompt` and `click.echo` to let the user select a result.

**Step 3: Commit**
```bash
git add src/koreadertohardcover/database.py src/koreadertohardcover/mapping.py
git commit -m "feat: implement interactive book mapping"
```

---

### Task 4: CLI Integration & Selection Logic

**Files:**
- Modify: `src/koreadertohardcover/main.py`

**Step 1: Add --past parameter**
Add `--past` (default 2) to the `sync` command.

**Step 2: Implement Selection & Sync Loop**
Update `sync` command:
1. Fetch top `N` books from DuckDB.
2. For each:
   - Check/Perform Mapping.
   - Calculate percentage.
   - Call `hardcover_client.update_progress`.
   - Update local `sync_status`.

**Step 3: Manual Verification**
Run `uv run koreadertohardcover sync --past 1` and verify interactive flow.

**Step 4: Commit**
```bash
git add src/koreadertohardcover/main.py
git commit -m "feat: integrate Hardcover sync into CLI"
```
