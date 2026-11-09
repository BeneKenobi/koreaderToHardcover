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
        elif "GetLatestRead" in content:
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
        book_id="123", percentage=51, status="reading", seconds=3600
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
        book_id="123", percentage=50, status="reading", seconds=3600
    )

    # Should succeed (return True) but NOT call any mutations
    assert success is True


@respx.mock
def test_rate_limit_is_retried(client, monkeypatch):
    sleeps = []
    monkeypatch.setattr(
        "koreadertohardcover.hardcover_client.time.sleep", sleeps.append
    )
    respx.post("https://api.hardcover.app/v1/graphql").mock(
        side_effect=[
            Response(429, headers={"Retry-After": "2"}),
            Response(200, json={"data": {"me": [{"id": 1, "username": "u"}]}}),
        ]
    )

    assert client.get_me() == {"id": 1, "username": "u"}
    assert sleeps == [2.0]


def _edition_change_handler(calls: list, latest_after_switch: dict):
    def mock_handler(request):
        content = request.read().decode("utf-8")
        body = content.replace(" ", "")
        if "GetEditionPages" in content:
            return Response(200, json={"data": {"editions_by_pk": {"pages": 100}}})
        if "GetUserBookInfo" in content:
            user_book = {
                "id": 999,
                "status_id": 1,
                "edition_id": 10,
                "user_book_reads": [
                    {"id": 111, "progress_pages": 20, "finished_at": None}
                ],
            }
            return Response(200, json={"data": {"me": [{"user_books": [user_book]}]}})
        if "GetLatestRead" in content:
            reads = [latest_after_switch]
            return Response(
                200, json={"data": {"user_books_by_pk": {"user_book_reads": reads}}}
            )
        for name in ("MoveUBR", "DeleteUBR", "UpdateUBR", "UpdateUB"):
            if name in content:
                calls.append((name, body))
                return Response(200, json={"data": {"result": {"id": 1}}})
        return Response(404)

    return mock_handler


@respx.mock
def test_edition_change_keeps_the_current_read(client):
    # Hardcover starts a new, empty read when the edition changes. The sync
    # moves the current read to the new edition and drops that empty one.
    calls = []
    respx.post("https://api.hardcover.app/v1/graphql").mock(
        side_effect=_edition_change_handler(
            calls, {"id": 222, "progress_pages": None, "finished_at": None}
        )
    )

    success = client.update_progress(
        book_id="123", percentage=50, status="reading", edition_id="20"
    )

    assert success is True
    assert [name for name, _ in calls] == [
        "MoveUBR",
        "UpdateUB",
        "DeleteUBR",
        "UpdateUBR",
    ]
    assert '"ubr_id":111,"edition_id":20' in calls[0][1]
    assert '"ubr_id":222' in calls[2][1]
    assert '"ubr_id":111' in calls[3][1]
    assert '"pages":50' in calls[3][1]


@respx.mock
def test_edition_change_without_new_read_deletes_nothing(client):
    calls = []
    respx.post("https://api.hardcover.app/v1/graphql").mock(
        side_effect=_edition_change_handler(
            calls, {"id": 111, "progress_pages": 20, "finished_at": None}
        )
    )

    success = client.update_progress(
        book_id="123", percentage=50, status="reading", edition_id="20"
    )

    assert success is True
    assert [name for name, _ in calls] == ["MoveUBR", "UpdateUB", "UpdateUBR"]
    assert '"ubr_id":111' in calls[2][1]


def test_requests_are_spaced_out(client, monkeypatch):
    clock = [100.0]
    sleeps = []

    def sleep(seconds):
        sleeps.append(round(seconds, 3))
        clock[0] += seconds

    monkeypatch.setattr(HardcoverClient, "MIN_REQUEST_INTERVAL", 1.1)
    monkeypatch.setattr(HardcoverClient, "_next_request_at", 0.0)
    monkeypatch.setattr(
        "koreadertohardcover.hardcover_client.time.monotonic", lambda: clock[0]
    )
    monkeypatch.setattr("koreadertohardcover.hardcover_client.time.sleep", sleep)

    client._throttle()
    clock[0] += 0.5
    client._throttle()
    clock[0] += 2.0
    client._throttle()

    assert sleeps == [0.6]
