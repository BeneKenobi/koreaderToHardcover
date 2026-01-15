import pytest
import respx
from httpx import Response
from koreadertohardcover.hardcover_client import HardcoverClient
from koreadertohardcover.config import Config

@pytest.fixture
def config():
    conf = Config()
    conf.HARDCOVER_BEARER_TOKEN = "test_token"
    return conf

@pytest.fixture
def client(config):
    return HardcoverClient(config)

@respx.mock
def test_search_books(client):
    respx.post("https://api.hardcover.app/v1/graphql").mock(return_value=Response(200, json={
        "data": {
            "books": [
                {"id": "123", "title": "Project Hail Mary", "author_name": "Andy Weir"},
                {"id": "456", "title": "Project Hail Mary (Alternate)", "author_name": "Andy Weir"}
            ]
        }
    }))
    
    results = client.search_books("Project Hail Mary")
    assert len(results) == 2
    assert results[0]["title"] == "Project Hail Mary"
    assert results[0]["id"] == "123"

@respx.mock
def test_update_progress(client):
    respx.post("https://api.hardcover.app/v1/graphql").mock(return_value=Response(200, json={
        "data": {
            "insert_user_book_one": {"id": "999"}
        }
    }))
    
    # Passing string ID which client converts to int
    success = client.update_progress(book_id="123", percentage=50.5, status="reading")
    assert success is True
