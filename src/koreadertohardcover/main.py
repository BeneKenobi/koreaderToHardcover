import click
import os
import tempfile
from rich.console import Console
from rich.table import Table
from koreadertohardcover.database import DatabaseManager
from koreadertohardcover.config import Config
from koreadertohardcover.webdav_client import fetch_koreader_db
from koreadertohardcover.hardcover_client import HardcoverClient
from koreadertohardcover.mapping import InteractiveMapper


@click.group()
def cli():
    """KOReader to Hardcover sync tool."""
    pass


@cli.command(name="map")
@click.argument("query", required=False)
@click.option(
    "--db-path", default="reading_stats.duckdb", help="Path to local DuckDB database."
)
def map_book(query, db_path):
    """
    Manually map a local book to a Hardcover edition.

    If QUERY is provided, searches for books matching the title.
    Otherwise, opens an interactive browser of local books.
    """
    db = DatabaseManager(db_path)
    try:
        db.connect()
    except Exception as e:
        click.echo(click.style(f"Error connecting to database: {e}", fg="red"))
        return

    config = Config()
    hc = HardcoverClient(config)
    mapper = InteractiveMapper(hc, db)
    console = Console()

    offset = 0
    limit = 10

    while True:
        # Fetch books
        books, total_count = db.get_local_books(query, limit, offset)

        # If specific query yields exactly one match and we're on the first page
        # and not in browser navigation (offset=0), we could auto-select,
        # but to be safe and consistent, we'll show the table unless user confirms.
        # Actually, let's just stick to the browser view for consistency.

        if not books:
            console.print("[yellow]No local books found matching criteria.[/yellow]")
            return

        # Display table
        table = Table(
            title=f"Local Books ({offset + 1}-{min(offset + len(books), total_count)} of {total_count})"
        )
        table.add_column("#", style="cyan", no_wrap=True)
        table.add_column("Title", style="white")
        table.add_column("Author", style="dim")
        table.add_column("Last Read", style="blue")
        table.add_column("Status", style="green")

        for idx, (b_id, title, author, last_open, is_mapped) in enumerate(books, 1):
            status = "[green]Mapped[/green]" if is_mapped else "[red]Unmapped[/red]"
            last_read_str = str(last_open) if last_open else "Never"
            table.add_row(str(idx), title, author or "Unknown", last_read_str, status)

        console.print(table)

        # Prompt
        console.print(
            "\n[bold]Options:[/bold] [cyan]1-9, 0[/cyan] Select (0=10) | [cyan]n[/cyan]ext | [cyan]p[/cyan]revious | [cyan]q[/cyan]uit"
        )
        choice = click.getchar()

        if choice.lower() == "q":
            break
        elif choice.lower() == "n":
            if offset + limit < total_count:
                offset += limit
            else:
                console.print("[yellow]Already on last page.[/yellow]")
        elif choice.lower() == "p":
            if offset - limit >= 0:
                offset -= limit
            else:
                console.print("[yellow]Already on first page.[/yellow]")
        else:
            try:
                # Map '0' to 10 for single-keystroke selection
                if choice == "0":
                    choice = "10"

                idx = int(choice)
                if 1 <= idx <= len(books):
                    selected = books[idx - 1]
                    b_id, title, authors = selected[0], selected[1], selected[2]

                    console.print(f"\n[bold]Starting mapping for: {title}[/bold]")
                    mapper.map_book(b_id, title, authors, force=True)

                    # Pause to let user see result
                    click.prompt(
                        "\nPress Enter to continue", default="", show_default=False
                    )
                else:
                    console.print("[red]Invalid selection.[/red]")
            except ValueError:
                # Don't print error for random keys to keep UI clean,
                # or maybe just ignore them.
                # But 'getchar' is immediate, so user might type something accidental.
                pass


@cli.command()
@click.argument(
    "sqlite_path", type=click.Path(exists=True, dir_okay=False), required=False
)
@click.option(
    "--db-path", default="reading_stats.duckdb", help="Path to local DuckDB database."
)
@click.option(
    "--ingest-only",
    is_flag=True,
    help="Only ingest data from KOReader, do not sync to Hardcover.",
)
@click.option(
    "--reset-db", is_flag=True, help="Clear the local database before syncing."
)
@click.option(
    "--past", default=2, help="Number of recently read books to sync to Hardcover."
)
@click.option(
    "--force",
    is_flag=True,
    help="Force update even if progress/status matches Hardcover.",
)
def sync(sqlite_path, db_path, ingest_only, reset_db, past, force):
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
            raise click.ClickException(
                "No local file provided and WEBDAV_URL is not set in environment."
            )

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
                click.echo(
                    click.style(
                        "Warning: HARDCOVER_BEARER_TOKEN not set. Skipping Hardcover sync.",
                        fg="yellow",
                    )
                )
            else:
                click.echo(f"\nSyncing {past} most recent books to Hardcover...")
                hc = HardcoverClient(config)
                mapper = InteractiveMapper(hc, db)

                # Fetch recent books with start date
                conn = db.get_connection()
                recent_books = conn.execute(
                    """
                    SELECT 
                        b.id, b.title, b.authors, b.total_read_pages, b.total_pages, b.status, b.total_read_time, b.last_open,
                        (SELECT MIN(start_time) FROM reading_sessions rs WHERE rs.book_id = b.id) as start_date
                    FROM books b
                    ORDER BY b.last_open DESC
                    LIMIT ?
                """,
                    [past],
                ).fetchall()

                for (
                    b_id,
                    title,
                    authors,
                    read_pg,
                    total_pg,
                    status,
                    read_time,
                    last_open,
                    start_date,
                ) in recent_books:
                    click.echo(f'\nProcessing "{title}"... ')

                    # Mapping
                    mapping = mapper.map_book(b_id, title, authors)
                    if not mapping:
                        continue

                    hc_id, edition_id = mapping

                    # Calculate percentage
                    percentage = (read_pg / total_pg * 100) if total_pg > 0 else 0

                    # Sync
                    click.echo(
                        f"  Updating Hardcover (Progress: {percentage:.1f}%, Time: {read_time}s, Status: {status})..."
                    )
                    success = hc.update_progress(
                        hc_id,
                        percentage,
                        status,
                        seconds=read_time,
                        last_read_date=last_open,
                        start_date=start_date,
                        force=force,
                        edition_id=edition_id,
                    )

                    if success:
                        click.echo(
                            click.style(f'  Successfully synced "{title}".', fg="green")
                        )
                        db.conn.execute(
                            "UPDATE books SET sync_status = 'synced', updated_at = now() WHERE id = ?",
                            [b_id],
                        )
                    else:
                        click.echo(
                            click.style(f'  Failed to sync "{title}".', fg="red")
                        )

        books_count = db.conn.execute("SELECT count(*) FROM books").fetchone()[0]
        sessions_count = db.conn.execute(
            "SELECT count(*) FROM reading_sessions"
        ).fetchone()[0]

        click.echo(
            click.style(
                f"\nSuccessfully processed {books_count} total books and {sessions_count} sessions.",
                fg="green",
            )
        )
    except Exception as e:
        click.echo(click.style(f"Error during sync: {e}", fg="red"), err=True)
    finally:
        db.close()
        # Clean up temp file if we created one
        if using_temp_file and sqlite_path and os.path.exists(sqlite_path):
            try:
                os.remove(sqlite_path)
            except Exception:
                pass


if __name__ == "__main__":
    cli()
