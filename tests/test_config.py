import os
from koreadertohardcover.config import Config


def test_load_env_vars():
    # Mock environment variables
    os.environ["WEBDAV_URL"] = "https://example.com/dav"
    os.environ["WEBDAV_USERNAME"] = "user"
    os.environ["WEBDAV_PASSWORD"] = "pass"
    os.environ["HARDCOVER_BEARER_TOKEN"] = "token123"
    if "WEBDAV_PATH" in os.environ:
        del os.environ["WEBDAV_PATH"]

    config = Config()
    assert config.WEBDAV_URL == "https://example.com/dav"
    assert config.WEBDAV_USERNAME == "user"
    assert config.WEBDAV_PASSWORD == "pass"
    assert config.HARDCOVER_BEARER_TOKEN == "token123"
    # Verify default
    assert config.KOREADER_DB_PATH == "statistics.sqlite3"


def test_webdav_path_combination():
    os.environ["WEBDAV_PATH"] = "koreader/sync/"
    os.environ["KOREADER_DB_PATH"] = "stats.db"

    config = Config()
    assert config.KOREADER_DB_PATH == "koreader/sync/stats.db"


def test_missing_env_vars():
    # Clear env vars
    if "WEBDAV_URL" in os.environ:
        del os.environ["WEBDAV_URL"]
    if "WEBDAV_PATH" in os.environ:
        del os.environ["WEBDAV_PATH"]
    if "KOREADER_DB_PATH" in os.environ:
        del os.environ["KOREADER_DB_PATH"]

    config = Config()
    assert config.WEBDAV_URL is None
