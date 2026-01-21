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
    respx.post("https://api.hardcover.app/v1/graphql").mock(
        return_value=Response(
            200,
            json={
                "data": {
                    "search": {
                        "results": {
                            "hits": [
                                {
                                    "document": {
                                        "id": "123",
                                        "title": "Project Hail Mary",
                                        "author_names": ["Andy Weir"],
                                        "pages": 100,
                                        "slug": "project-hail-mary",
                                    }
                                },
                                {
                                    "document": {
                                        "id": "456",
                                        "title": "Project Hail Mary (Alternate)",
                                        "author_names": ["Andy Weir"],
                                        "pages": 100,
                                        "slug": "project-hail-mary-alt",
                                    }
                                },
                            ]
                        }
                    }
                }
            },
        )
    )

    results = client.search_books("Project Hail Mary")
    assert len(results) == 2
    assert results[0]["title"] == "Project Hail Mary"
    assert results[0]["author_name"] == "Andy Weir"
    assert results[0]["id"] == "123"


@respx.mock
def test_update_progress(client):
    def mock_handler(request):
        content = request.read().decode("utf-8")
        if "GetBookPages" in content:
            return Response(200, json={"data": {"books_by_pk": {"pages": 100}}})
        if "GetUserBookInfo" in content:
            return Response(200, json={"data": {"me": [{"user_books": []}]}})
        elif "CreateUserBookRead" in content:
            return Response(200, json={"data": {"insert_user_book_read": {"id": 888}}})
        elif "CreateUserBook" in content:
            return Response(200, json={"data": {"insert_user_book": {"id": 999}}})
        elif "UpdateUBR" in content:
            return Response(200, json={"data": {"update_user_book_read": {"id": 888}}})
        elif "UpdateUB" in content:
            return Response(200, json={"data": {"update_user_book": {"id": 999}}})
        return Response(404)

    respx.post("https://api.hardcover.app/v1/graphql").mock(side_effect=mock_handler)

    # Passing string ID which client converts to int
    success = client.update_progress(
        book_id="123", percentage=50.5, status="reading", seconds=3600
    )
    assert success is True
