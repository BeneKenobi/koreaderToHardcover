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

    remote_path = "statistics.sqlite3"
    local_path = tmp_path / "downloaded.sqlite3"

    # Execute
    fetch_koreader_db(config, str(local_path), remote_path)

    # Verify
    mock_client_cls.assert_called_with(
        base_url="https://dav.example.com", auth=("user", "pass")
    )
    mock_client.download_file.assert_called_with(
        from_path=remote_path, to_path=str(local_path)
    )


def test_fetch_koreader_db_no_url():
    config = Config()
    config.WEBDAV_URL = None
    with pytest.raises(ValueError, match="WEBDAV_URL is not set"):
        fetch_koreader_db(config, "local.db")
