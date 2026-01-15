import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    def __init__(self):
        self.WEBDAV_URL = os.getenv("WEBDAV_URL")
        self.WEBDAV_USERNAME = os.getenv("WEBDAV_USERNAME")
        self.WEBDAV_PASSWORD = os.getenv("WEBDAV_PASSWORD")
        self.HARDCOVER_BEARER_TOKEN = os.getenv("HARDCOVER_BEARER_TOKEN")

        webdav_path = os.getenv("WEBDAV_PATH", "")
        db_name = os.getenv("KOREADER_DB_PATH", "statistics.sqlite3")

        # Combine path and name, handling slashes
        if webdav_path:
            self.KOREADER_DB_PATH = os.path.join(webdav_path, db_name)
        else:
            self.KOREADER_DB_PATH = db_name
