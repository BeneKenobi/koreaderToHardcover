from webdav4.client import Client
from koreadertohardcover.config import Config

def fetch_koreader_db(config: Config, local_path: str, remote_path: str = None) -> None:
    """
    Downloads the KOReader database from WebDAV.
    """
    if not config.WEBDAV_URL:
        raise ValueError("WEBDAV_URL is not set in configuration")
        
    remote_path = remote_path or config.KOREADER_DB_PATH
    
    # Ensure URL starts with http:// or https:// if not already
    base_url = config.WEBDAV_URL
    if not base_url.startswith(("http://", "https://")):
        base_url = f"https://{base_url}"

    client = Client(
        base_url=base_url,
        auth=(config.WEBDAV_USERNAME, config.WEBDAV_PASSWORD)
    )
    
    client.download_file(from_path=remote_path, to_path=local_path)
