import pytest

from koreadertohardcover.hardcover_client import HardcoverClient


@pytest.fixture(autouse=True)
def no_request_throttle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests use mocked HTTP, so they need not wait for Hardcover's rate limit."""
    monkeypatch.setattr(HardcoverClient, "MIN_REQUEST_INTERVAL", 0.0)
