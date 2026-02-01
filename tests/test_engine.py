import pytest
from unittest.mock import MagicMock, patch
from koreadertohardcover.engine import SyncEngine
from koreadertohardcover.config import Config


@pytest.fixture
def mock_config():
    conf = Config()
    conf.WEBDAV_URL = "https://example.com/webdav"
    conf.WEBDAV_USERNAME = "user"
    conf.WEBDAV_PASSWORD = "pass"
    conf.HARDCOVER_BEARER_TOKEN = "test_token"
    return conf


@pytest.fixture
def mock_db_manager():
    with patch("koreadertohardcover.engine.DatabaseManager") as MockDB:
        # Configure the mock instance that will be returned
        db_instance = MockDB.return_value
        # Mock get_connection context manager
        mock_conn = MagicMock()
        db_instance.get_connection.return_value.__enter__.return_value = mock_conn
        yield db_instance


@pytest.fixture
def engine(mock_config, mock_db_manager):
    # Pass path explicitly to avoid real file creation
    return SyncEngine(db_path=":memory:", config=mock_config)


def test_ingest_from_webdav_success(engine):
    with patch("koreadertohardcover.engine.fetch_koreader_db") as mock_fetch:
        success = engine.ingest_from_webdav()

        assert success is True
        mock_fetch.assert_called_once()
        # Verify DB imports called
        engine.db.import_books.assert_called_once()
        engine.db.import_sessions.assert_called_once()


def test_ingest_from_webdav_no_url(engine):
    engine.config.WEBDAV_URL = None
    success = engine.ingest_from_webdav()
    assert success is False


def test_ingest_from_local_success(engine, tmp_path):
    fake_db = tmp_path / "stats.sqlite3"
    fake_db.touch()

    success = engine.ingest_from_local(str(fake_db))

    assert success is True
    engine.db.import_books.assert_called_with(str(fake_db))
    engine.db.import_sessions.assert_called_with(str(fake_db))


def test_ingest_from_local_missing_file(engine):
    success = engine.ingest_from_local("/non/existent/path.sqlite3")
    assert success is False


def test_sync_progress_no_token(engine):
    engine.config.HARDCOVER_BEARER_TOKEN = None
    results = engine.sync_progress()
    assert results == []


@patch("koreadertohardcover.engine.HardcoverClient")
def test_sync_progress_success(MockHC, engine):
    # Setup Mock Hardcover Client
    hc_instance = MockHC.return_value
    hc_instance.update_progress.return_value = True

    # Setup Mock DB Data
    # Columns: id, title, authors, read_pg, total_pg, status, read_time, last_open, hc_id, ed_id, start_date, last_session_date, max_page
    mock_books = [
        (
            "md5_1",
            "Book One",
            "Author A",
            50,
            100,
            "reading",
            3600,
            "2023-01-01",
            "1001",
            None,
            "2023-01-01",
            None,
            50,
        ),
        (
            "md5_2",
            "Book Two",
            "Author B",
            200,
            200,
            "finished",
            7200,
            "2023-01-02",
            "1002",
            "999",
            "2023-01-01",
            "2023-02-01",
            200,
        ),
        # New test case: Position > Count (e.g. Skipped pages)
        # Count is 90 (90%), but Position is 99 (99%) -> Should sync as 99% & finished
        (
            "md5_3",
            "Book Three",
            "Author C",
            90,
            100,
            "reading",
            3600,
            "2023-01-03",
            "1003",
            None,
            "2023-01-01",
            "2023-02-01",
            99,
        ),
    ]

    # Get the mock connection from the fixture
    conn = engine.db.get_connection.return_value.__enter__.return_value
    conn.execute.return_value.fetchall.return_value = mock_books

    # Run Sync
    results = engine.sync_progress(limit=10)

    # Verify Results
    assert len(results) == 3
    assert results[0] == ("Book One", True)
    assert results[1] == ("Book Two", True)
    assert results[2] == ("Book Three", True)

    # Verify Hardcover Client calls
    assert hc_instance.update_progress.call_count == 3

    # Check first call (Book One)
    hc_instance.update_progress.assert_any_call(
        "1001",
        50.0,
        "reading",
        seconds=3600,
        last_read_date="2023-01-01",
        start_date="2023-01-01",
        force=False,
        edition_id=None,
    )

    # Check second call (Book Two)
    hc_instance.update_progress.assert_any_call(
        "1002",
        100.0,
        "finished",
        seconds=7200,
        last_read_date="2023-02-01",
        start_date="2023-01-01",
        force=False,
        edition_id="999",
    )

    # Check third call (Book Three - The fix verification)
    hc_instance.update_progress.assert_any_call(
        "1003",
        99.0,  # Should be 99% (based on max_page), not 90%
        "finished",  # Should be finished (because >= 98%), despite DB saying "reading"
        seconds=3600,
        last_read_date="2023-02-01",
        start_date="2023-01-01",
        force=False,
        edition_id=None,
    )

    # Verify DB Updates (sync_status set to 'synced')
    # execute is called 1 (select) + 3 (updates) = 4 times
    assert conn.execute.call_count == 4
    conn.execute.assert_any_call(
        "UPDATE books SET sync_status = 'synced', updated_at = now() WHERE id = ?",
        ["md5_1"],
    )
    conn.execute.assert_any_call(
        "UPDATE books SET sync_status = 'synced', updated_at = now() WHERE id = ?",
        ["md5_2"],
    )
    conn.execute.assert_any_call(
        "UPDATE books SET sync_status = 'synced', updated_at = now() WHERE id = ?",
        ["md5_3"],
    )


def test_ingest_from_webdav_exception(engine):
    with patch(
        "koreadertohardcover.engine.fetch_koreader_db",
        side_effect=Exception("Fetch failed"),
    ):
        success = engine.ingest_from_webdav()
        assert success is False


def test_ingest_from_local_exception(engine, tmp_path):
    fake_db = tmp_path / "stats.sqlite3"
    fake_db.touch()

    # Mock db.import_books to raise exception
    engine.db.import_books.side_effect = Exception("Import failed")

    success = engine.ingest_from_local(str(fake_db))
    assert success is False


def test_sync_progress_exception(engine):
    # Mock get_connection to raise exception
    engine.db.get_connection.side_effect = Exception("DB Connection failed")

    results = engine.sync_progress()
    assert results == []


def test_ingest_from_webdav_cleanup_exception(engine):
    with patch("koreadertohardcover.engine.fetch_koreader_db"):
        # Mock os.remove to raise exception
        with patch("os.remove", side_effect=Exception("Remove failed")):
            # We need to ensure os.path.exists returns True so it tries to remove
            with patch("os.path.exists", return_value=True):
                success = engine.ingest_from_webdav()
                # Logic should still succeed even if cleanup fails
                assert success is True
