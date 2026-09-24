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
