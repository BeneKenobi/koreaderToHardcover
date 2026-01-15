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
@click.option('--webdav', is_flag=True, help="Fetch KOReader database via WebDAV instead of local file.")
def sync(sqlite_path, db_path, ingest_only, webdav):
    """Sync data from KOReader SQLite database to Hardcover."""
    config = Config()
    
    if webdav:
        if not config.WEBDAV_URL:
            raise click.ClickException("WebDAV sync requested but WEBDAV_URL is not set in environment.")
        
        # Create a temp file to download the database to
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(tmp_fd)
        
        try:
            click.echo(f"Fetching database from WebDAV: {config.WEBDAV_URL}...")
            fetch_koreader_db(config, tmp_path)
            sqlite_path = tmp_path
        except Exception as e:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise click.ClickException(f"Failed to fetch database from WebDAV: {e}")
    elif not sqlite_path:
        raise click.UsageError("Missing argument 'SQLITE_PATH' or use --webdav flag.")

    db = DatabaseManager(db_path)
    
    try:
        # We use a progress bar with 2 steps for ingestion
        # If not ingest-only, we would add more steps later
        total_steps = 2
        
        with click.progressbar(length=total_steps, label='Syncing data') as bar:
            db.connect()
            
            # Step 1: Ingest Books
            bar.label = "Ingesting books"
            db.import_books(sqlite_path)
            bar.update(1)
            
            # Step 2: Ingest Sessions
            bar.label = "Ingesting sessions"
            db.import_sessions(sqlite_path)
            bar.update(1)
            
            if not ingest_only:
                # TODO: Implement Hardcover sync logic
                click.echo(click.style("\nHardcover sync not yet implemented.", fg='yellow'))
            
        conn = db.get_connection()
        books_count = conn.execute("SELECT count(*) FROM books").fetchone()[0]
        sessions_count = conn.execute("SELECT count(*) FROM reading_sessions").fetchone()[0]
        
        click.echo(click.style(f"Successfully processed {books_count} books and {sessions_count} sessions.", fg='green'))
    except Exception as e:
        click.echo(click.style(f"Error during sync: {e}", fg='red'), err=True)
    finally:
        db.close()
        if webdav and sqlite_path and os.path.exists(sqlite_path):
            os.remove(sqlite_path)

if __name__ == '__main__':
    cli()