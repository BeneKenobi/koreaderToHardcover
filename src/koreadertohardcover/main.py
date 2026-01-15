import click
import os
import tempfile
from koreadertohardcover.database import DatabaseManager
from koreadertohardcover.config import Config
from koreadertohardcover.webdav_client import fetch_koreader_db

@click.group()
def cli():
    """KOReader to Hardcover sync tool."""
    pass

@cli.command()
@click.argument('sqlite_path', type=click.Path(exists=True, dir_okay=False), required=False)
@click.option('--db-path', default="reading_stats.duckdb", help="Path to local DuckDB database.")
@click.option('--ingest-only', is_flag=True, help="Only ingest data from KOReader, do not sync to Hardcover.")
@click.option('--reset-db', is_flag=True, help="Clear the local database before syncing.")
def sync(sqlite_path, db_path, ingest_only, reset_db):
    """
    Sync data from KOReader SQLite database to Hardcover.
    
    If SQLITE_PATH is provided, uses that local file.
    Otherwise, attempts to fetch the database via WebDAV using environment variables.
    """
    if reset_db and os.path.exists(db_path):
        click.echo(f"Resetting database: {db_path}")
        os.remove(db_path)

    config = Config()
    using_temp_file = False
    
    if not sqlite_path:
        if not config.WEBDAV_URL:
            raise click.ClickException("No local file provided and WEBDAV_URL is not set in environment.")
        
        # Create a temp file to download the database to
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(tmp_fd)
        
        try:
            click.echo(f"Fetching database from WebDAV: {config.WEBDAV_URL}...")
            fetch_koreader_db(config, tmp_path)
            sqlite_path = tmp_path
            using_temp_file = True
        except Exception as e:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise click.ClickException(f"Failed to fetch database from WebDAV: {e}")

import click
import os
import tempfile
from koreadertohardcover.database import DatabaseManager
from koreadertohardcover.config import Config
from koreadertohardcover.webdav_client import fetch_koreader_db
from koreadertohardcover.hardcover_client import HardcoverClient
from koreadertohardcover.mapping import InteractiveMapper

@click.group()
def cli():
    """KOReader to Hardcover sync tool."""
    pass

@cli.command()
@click.argument('sqlite_path', type=click.Path(exists=True, dir_okay=False), required=False)
@click.option('--db-path', default="reading_stats.duckdb", help="Path to local DuckDB database.")
@click.option('--ingest-only', is_flag=True, help="Only ingest data from KOReader, do not sync to Hardcover.")
@click.option('--reset-db', is_flag=True, help="Clear the local database before syncing.")
@click.option('--past', default=2, help="Number of recently read books to sync to Hardcover.")
def sync(sqlite_path, db_path, ingest_only, reset_db, past):
    """
    Sync data from KOReader SQLite database to Hardcover.
    
    If SQLITE_PATH is provided, uses that local file.
    Otherwise, attempts to fetch the database via WebDAV using environment variables.
    """
    if reset_db and os.path.exists(db_path):
        click.echo(f"Resetting database: {db_path}")
        os.remove(db_path)

    config = Config()
    using_temp_file = False
    
    if not sqlite_path:
        if not config.WEBDAV_URL:
            raise click.ClickException("No local file provided and WEBDAV_URL is not set in environment.")
        
        # Create a temp file to download the database to
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(tmp_fd)
        
        try:
            click.echo(f"Fetching database from WebDAV: {config.WEBDAV_URL}...")
            fetch_koreader_db(config, tmp_path)
            sqlite_path = tmp_path
            using_temp_file = True
        except Exception as e:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise click.ClickException(f"Failed to fetch database from WebDAV: {e}")

    db = DatabaseManager(db_path)
    
    try:
        # Step 1 & 2: Ingestion
        db.connect()
        click.echo("Ingesting data from KOReader...")
        db.import_books(sqlite_path)
        db.import_sessions(sqlite_path)
            
        if not ingest_only:
            if not config.HARDCOVER_BEARER_TOKEN:
                click.echo(click.style("Warning: HARDCOVER_BEARER_TOKEN not set. Skipping Hardcover sync.", fg='yellow'))
            else:
                click.echo(f"\nSyncing {past} most recent books to Hardcover...")
                hc = HardcoverClient(config)
                mapper = InteractiveMapper(hc, db)
                
                # Fetch recent books
                conn = db.get_connection()
                recent_books = conn.execute("""
                    SELECT id, title, authors, total_read_pages, total_pages, status
                    FROM books
                    ORDER BY last_open DESC
                    LIMIT ?
                """, [past]).fetchall()
                
                for b_id, title, authors, read_pg, total_pg, status in recent_books:
                    click.echo(f"\nProcessing \"{title}\"...")
                    
                    # Mapping
                    hc_id = mapper.map_book(b_id, title, authors)
                    if not hc_id:
                        continue
                        
                    # Calculate percentage
                    percentage = (read_pg / total_pg * 100) if total_pg > 0 else 0
                    
                    # Sync
                    click.echo(f"  Updating Hardcover (Progress: {percentage:.1f}%, Status: {status})...")
                    success = hc.update_progress(hc_id, percentage, status)
                    
                    if success:
                        click.echo(click.style(f"  Successfully synced \"{title}\".", fg='green'))
                        db.conn.execute("UPDATE books SET sync_status = 'synced', updated_at = now() WHERE id = ?", [b_id])
                    else:
                        click.echo(click.style(f"  Failed to sync \"{title}\".", fg='red'))
            
        books_count = db.conn.execute("SELECT count(*) FROM books").fetchone()[0]
        sessions_count = db.conn.execute("SELECT count(*) FROM reading_sessions").fetchone()[0]
        
        click.echo(click.style(f"\nSuccessfully processed {books_count} total books and {sessions_count} sessions.", fg='green'))
    except Exception as e:
        click.echo(click.style(f"Error during sync: {e}", fg='red'), err=True)
    finally:
        db.close()
        if using_temp_file and sqlite_path and os.path.exists(sqlite_path):
            os.remove(sqlite_path)

if __name__ == '__main__':
    cli()