# Environment & WebDAV Support Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** implement secure environment variable loading and WebDAV file downloading to fetch remote KOReader databases.

**Architecture:** Use `python-dotenv` to load configuration from `.env`. Create a `Config` class to centralize settings. Add a `WebDAVClient` class using `webdav4` (modern, typed) or `webdavclient3` to handle file downloads. Update `main.py` to use these.

**Tech Stack:** python-dotenv, webdav4, pytest

---

### Task 1: Add Dependencies

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add dependencies to pyproject.toml**
Add `python-dotenv` and `webdav4` to dependencies.

**Step 2: Install dependencies**
Run: `uv sync`

**Step 3: Verify installation**
Run: `uv pip list | grep -E "python-dotenv|webdav4"`

**Step 4: Commit**
```bash
git add pyproject.toml uv.lock
git commit -m "chore: add python-dotenv and webdav4 dependencies"
```

---

### Task 2: Implement Configuration Management

**Files:**
- Create: `src/koreadertohardcover/config.py`
- Create: `tests/test_config.py`
- Modify: `src/koreadertohardcover/__init__.py` (export Config)

**Step 1: Write failing test for Config**
Create `tests/test_config.py`:
```python
import os
from koreadertohardcover.config import Config

def test_load_env_vars():
    os.environ["WEBDAV_URL"] = "https://example.com/dav"
    os.environ["WEBDAV_USERNAME"] = "user"
    os.environ["WEBDAV_PASSWORD"] = "pass"
    
    config = Config()
    assert config.WEBDAV_URL == "https://example.com/dav"
    assert config.WEBDAV_USERNAME == "user"
    assert config.WEBDAV_PASSWORD == "pass"

def test_missing_env_vars():
    # Clear env vars if set
    if "WEBDAV_URL" in os.environ: del os.environ["WEBDAV_URL"]
    
    config = Config()
    assert config.WEBDAV_URL is None
```

**Step 2: Run test (fail)**
Run: `uv run pytest tests/test_config.py -v`

**Step 3: Implement Config class**
Create `src/koreadertohardcover/config.py`:
```python
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    def __init__(self):
        self.WEBDAV_URL = os.getenv("WEBDAV_URL")
        self.WEBDAV_USERNAME = os.getenv("WEBDAV_USERNAME")
        self.WEBDAV_PASSWORD = os.getenv("WEBDAV_PASSWORD")
        self.KOREADER_DB_PATH = os.getenv("KOREADER_DB_PATH", "metadata.sqlite3")
```

**Step 4: Run test (pass)**
Run: `uv run pytest tests/test_config.py -v`

**Step 5: Commit**
```bash
git add src/koreadertohardcover/config.py tests/test_config.py
git commit -m "feat: implement Config class with dotenv support"
```

---

### Task 3: Implement WebDAV Client

**Files:**
- Create: `src/koreadertohardcover/webdav_client.py`
- Create: `tests/test_webdav.py`

**Step 1: Write failing test for WebDAV download**
Create `tests/test_webdav.py`. We'll mock the actual network call.
```python
import pytest
from unittest.mock import patch, MagicMock
from koreadertohardcover.webdav_client import fetch_koreader_db
from koreadertohardcover.config import Config

@patch("koreadertohardcover.webdav_client.Client")
def test_fetch_koreader_db(mock_client_cls, tmp_path):
    # Setup mock
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    
    # Setup config
    config = Config()
    config.WEBDAV_URL = "https://dav.example.com"
    config.WEBDAV_USERNAME = "user"
    config.WEBDAV_PASSWORD = "pass"
    
    remote_path = "metadata.sqlite3"
    local_path = tmp_path / "downloaded.sqlite3"
    
    # Execute
    fetch_koreader_db(config, str(local_path), remote_path)
    
    # Verify
    mock_client_cls.assert_called_with(
        base_url="https://dav.example.com",
        auth=("user", "pass")
    )
    mock_client.download_file.assert_called_with(
        from_path=remote_path,
        to_path=str(local_path)
    )
```

**Step 2: Run test (fail)**
Run: `uv run pytest tests/test_webdav.py -v`

**Step 3: Implement WebDAV fetcher**
Create `src/koreadertohardcover/webdav_client.py`:
```python
from webdav4.client import Client
from koreadertohardcover.config import Config

def fetch_koreader_db(config: Config, local_path: str, remote_path: str = None) -> None:
    """
    Downloads the KOReader database from WebDAV.
    """
    if not config.WEBDAV_URL:
        raise ValueError("WEBDAV_URL is not set in configuration")
        
    remote_path = remote_path or config.KOREADER_DB_PATH
    
    client = Client(
        base_url=config.WEBDAV_URL,
        auth=(config.WEBDAV_USERNAME, config.WEBDAV_PASSWORD)
    )
    
    client.download_file(from_path=remote_path, to_path=local_path)
```

**Step 4: Run test (pass)**
Run: `uv run pytest tests/test_webdav.py -v`

**Step 5: Commit**
```bash
git add src/koreadertohardcover/webdav_client.py tests/test_webdav.py
git commit -m "feat: implement WebDAV database fetcher"
```

---

### Task 4: Integrate into CLI

**Files:**
- Modify: `src/koreadertohardcover/main.py`

**Step 1: Update sync command**
Modify `src/koreadertohardcover/main.py` to:
1. Initialize `Config`
2. Add a `--webdav/--local` flag (defaulting to local if no env vars, or explicit choice)
3. If WebDAV is used, download to a temp file first
4. Use that temp file for ingestion

We will modify the signature to make `sqlite_path` optional if `--webdav` is used.

**Step 2: Manual Verification (Dry Run)**
Since testing CLI side-effects is heavier, we'll verify by running help:
Run: `uv run koreadertohardcover --help`

**Step 3: Commit**
```bash
git add src/koreadertohardcover/main.py
git commit -m "feat: integrate WebDAV sync into CLI"
```
