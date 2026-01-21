import click
import os
import logging
from rich.console import Console
from rich.table import Table
from koreadertohardcover.database import DatabaseManager

# Configure logging for CLI
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

from koreadertohardcover.config import Config
from koreadertohardcover.hardcover_client import HardcoverClient
from koreadertohardcover.mapping import InteractiveMapper
from koreadertohardcover.engine import SyncEngine


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
    # try:
    #     db.connect()
    # except Exception as e:
    #     click.echo(click.style(f"Error connecting to database: {e}", fg="red"))
    #     return

    config = Config()
    hc = HardcoverClient(config)
    mapper = InteractiveMapper(hc, db)
    console = Console()

    offset = 0
    limit = 10

    while True:
        # Fetch books
        books, total_count = db.get_local_books(query, limit, offset)

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
    engine = SyncEngine(db_path, config)

    # 1. Ingestion
    if sqlite_path:
        success = engine.ingest_from_local(sqlite_path)
    else:
        success = engine.ingest_from_webdav()

    if not success:
        raise click.ClickException("Ingestion failed. Check logs or parameters.")

    # 2. Sync
    if not ingest_only:
        click.echo(f"\nSyncing {past} most recent books to Hardcover...")
        results = engine.sync_progress(limit=past, force=force)

        for title, status in results:
            if status:
                click.echo(click.style(f'  Successfully synced "{title}".', fg="green"))
            else:
                click.echo(click.style(f'  Failed to sync "{title}".', fg="red"))

    # 3. Summary
    db = DatabaseManager(db_path)
    with db.get_connection() as conn:
        books_count = conn.execute("SELECT count(*) FROM books").fetchone()[0]
        sessions_count = conn.execute(
            "SELECT count(*) FROM reading_sessions"
        ).fetchone()[0]

        click.echo(
            click.style(
                f"\nSuccessfully processed {books_count} total books and {sessions_count} sessions.",
                fg="green",
            )
        )


if __name__ == "__main__":
    cli()
