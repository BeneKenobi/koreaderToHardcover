import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    def __init__(self):
        self.WEBDAV_URL = os.getenv("WEBDAV_URL")
        self.WEBDAV_USERNAME = os.getenv("WEBDAV_USERNAME")
        self.WEBDAV_PASSWORD = os.getenv("WEBDAV_PASSWORD")
        self.KOREADER_DB_PATH = os.getenv("KOREADER_DB_PATH", "metadata.sqlite3")
