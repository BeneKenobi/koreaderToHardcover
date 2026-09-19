import duckdb
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_PATH", str(tmp_path / "app.log"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "web.duckdb"))
    monkeypatch.setenv("SYNC_INTERVAL_MINUTES", "1440")
    from koreadertohardcover import web

    monkeypatch.setattr(web.scheduler, "add_job", lambda *a, **k: None)
    with TestClient(web.app, base_url="http://test") as c:
        yield c, web


def test_dashboard_returns_503_on_corrupt_db(client, monkeypatch):
    c, web = client

    def boom(*args, **kwargs):
        raise duckdb.SerializationException("field id mismatch")

    monkeypatch.setattr(web.engine.db, "get_local_books", boom)

    response = c.get("/", auth=("admin", "admin"))

    assert response.status_code == 503
    assert "Database unavailable" in response.text
