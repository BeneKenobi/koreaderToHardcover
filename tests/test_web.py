import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

AUTH = ("admin", "admin")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_PATH", str(tmp_path / "app.log"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "web.duckdb"))
    monkeypatch.setenv("SYNC_INTERVAL_MINUTES", "1440")
    from koreadertohardcover import web

    monkeypatch.setattr(web.scheduler, "add_job", lambda *a, **k: None)
    monkeypatch.setattr(web.config, "HARDCOVER_BEARER_TOKEN", None)
    with TestClient(web.app, base_url="http://test") as c:
        yield c, web


def test_summarize_sync_reports_failures(client) -> None:
    _, web = client
    summarize_sync = web.summarize_sync

    assert summarize_sync(True, [("A", True)]) == "Success (1 books checked)"
    assert summarize_sync(False, []).startswith("Error: WebDAV ingestion failed")
    assert summarize_sync(None, None).startswith("Error: Hardcover sync failed")
    assert "1 of 2 books failed" in summarize_sync(True, [("A", True), ("B", False)])


def test_scheduled_sync_skips_while_running(client, monkeypatch) -> None:
    _, web = client
    calls = []
    monkeypatch.setattr(web.engine, "sync_progress", lambda **k: calls.append(1))

    with web.sync_lock:
        web.scheduled_sync()

    assert calls == []


def test_manual_sync_rejected_while_running(client, monkeypatch) -> None:
    c, web = client
    calls = []
    monkeypatch.setattr(web, "scheduled_sync", lambda: calls.append(1))

    with web.sync_lock:
        c.post("/sync", auth=AUTH)

    assert calls == []


def test_cross_site_post_is_rejected(client) -> None:
    c, _ = client

    response = c.post("/sync", auth=AUTH, headers={"Origin": "https://evil.example"})

    assert response.status_code == 403


def test_same_site_post_is_allowed(client, monkeypatch) -> None:
    c, web = client
    monkeypatch.setattr(web, "scheduled_sync", lambda: None)

    response = c.post(
        "/sync",
        auth=AUTH,
        headers={"Origin": "http://test"},
        follow_redirects=False,
    )

    assert response.status_code == 303


def test_dashboard_clamps_invalid_page(client) -> None:
    c, _ = client

    assert c.get("/?page=0", auth=AUTH).status_code == 200


def test_confirm_unknown_book_is_404(client) -> None:
    c, _ = client

    response = c.post(
        "/map/missing/confirm",
        auth=AUTH,
        data={"hardcover_id": "1", "title": "T", "author": "A"},
    )

    assert response.status_code == 404


def _seed(web) -> None:
    with web.engine.db.get_connection() as conn:
        conn.execute("DELETE FROM books")
        conn.execute(
            "INSERT INTO books (id, title, authors, total_read_pages, total_pages, "
            "status, last_open) VALUES "
            "('a', 'Dune', 'Frank Herbert', 99, 100, 'reading', '2024-01-02'), "
            "('b', 'Emma', 'Jane Austen', 10, 100, 'reading', '2024-01-01')"
        )


def test_dashboard_filters_by_query(client) -> None:
    c, web = client
    _seed(web)

    response = c.get("/?q=austen", auth=AUTH)

    assert "Emma" in response.text
    assert "Dune" not in response.text


def test_dashboard_shows_effective_status(client) -> None:
    c, web = client
    _seed(web)

    response = c.get("/?q=dune", auth=AUTH)

    assert "Finished" in response.text


def test_dashboard_ignores_bad_page(client) -> None:
    c, _ = client

    assert c.get("/?page=abc", auth=AUTH).status_code == 200


def test_status_endpoint(client) -> None:
    c, web = client

    response = c.get("/status", auth=AUTH)

    assert response.json()["state"] == web.sync_status["state"]


def test_username_failure_is_not_retried_immediately(client, monkeypatch) -> None:
    _, web = client
    calls = []

    class FailingClient:
        def __init__(self, config):
            calls.append(1)
            raise RuntimeError("down")

    monkeypatch.setattr(web.config, "HARDCOVER_BEARER_TOKEN", "token")
    monkeypatch.setattr(web, "HardcoverClient", FailingClient)
    monkeypatch.setitem(web._username_cache, "value", None)
    monkeypatch.setitem(web._username_cache, "failed_at", None)

    assert web.hardcover_username() is None
    assert web.hardcover_username() is None
    assert len(calls) == 1


def test_log_defaults_to_database_directory(tmp_path) -> None:
    """Without LOG_PATH the app must not write into the (read-only) working dir."""
    env = {k: v for k, v in os.environ.items() if k != "LOG_PATH"}
    env["DB_PATH"] = str(tmp_path / "db" / "stats.duckdb")
    (tmp_path / "db").mkdir()
    workdir = tmp_path / "readonly"
    workdir.mkdir(mode=0o555)

    subprocess.run(
        [sys.executable, "-c", "import koreadertohardcover.web"],
        cwd=workdir,
        env=env,
        check=True,
    )

    assert (tmp_path / "db" / "app.log").exists()
