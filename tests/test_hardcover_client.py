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
        elif "GetNewUserBook" in content:
            return Response(
                200,
                json={"data": {"user_books_by_pk": {"user_book_reads": [{"id": 777}]}}},
            )
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


@respx.mock
def test_update_progress_skips_finished(client):
    # Test that we skip update if remote status is 3 (Finished)
    def mock_handler(request):
        content = request.read().decode("utf-8")
        if "GetBookPages" in content:
            return Response(200, json={"data": {"books_by_pk": {"pages": 100}}})
        if "GetUserBookInfo" in content:
            # Return status_id 3 (Finished)
            return Response(
                200,
                json={
                    "data": {
                        "me": [
                            {
                                "user_books": [
                                    {
                                        "id": 999,
                                        "status_id": 3,
                                        "edition_id": None,
                                        "user_book_reads": [],
                                    }
                                ]
                            }
                        ]
                    }
                },
            )
        # Fail if any mutation is attempted
        if "mutation" in content:
            return Response(500, json={"error": "Should not attempt mutation"})

        return Response(404)

    respx.post("https://api.hardcover.app/v1/graphql").mock(side_effect=mock_handler)

    # Try to update a book that is finished remotely
    success = client.update_progress(
        book_id="123", percentage=50.0, status="reading", seconds=3600
    )

    # Should succeed (return True) but NOT call any mutations
    assert success is True
