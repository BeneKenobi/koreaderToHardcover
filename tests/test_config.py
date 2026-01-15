import os
import pytest
from koreadertohardcover.config import Config

def test_load_env_vars():
    # Mock environment variables
    os.environ["WEBDAV_URL"] = "https://example.com/dav"
    os.environ["WEBDAV_USERNAME"] = "user"
    os.environ["WEBDAV_PASSWORD"] = "pass"
    
    config = Config()
    assert config.WEBDAV_URL == "https://example.com/dav"
    assert config.WEBDAV_USERNAME == "user"
    assert config.WEBDAV_PASSWORD == "pass"
    # Verify default
    assert config.KOREADER_DB_PATH == "metadata.sqlite3"

def test_missing_env_vars():
    # Clear specific env var if it exists
    if "WEBDAV_URL" in os.environ:
        del os.environ["WEBDAV_URL"]
    
    config = Config()
    assert config.WEBDAV_URL is None
