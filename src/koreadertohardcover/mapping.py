import click
from typing import Optional
from koreadertohardcover.hardcover_client import HardcoverClient
from koreadertohardcover.database import DatabaseManager

class InteractiveMapper:
    def __init__(self, client: HardcoverClient, db: DatabaseManager):
        self.client = client
        self.db = db

    def map_book(self, local_id: str, title: str, author: str) -> Optional[str]:
        """
        Interactive flow to map a local book to Hardcover.
        """
        # 1. Check if already mapped
        existing = self.db.get_book_mapping(local_id)
        if existing:
            return existing

        click.echo(click.style(f"\nNo mapping found for: \"{title}\" by {author}", fg='yellow'))
        
        # 2. Search Hardcover
        results = self.client.search_books(title) # Search by title primarily
        
        if not results:
            click.echo(click.style(f"  No matches found on Hardcover for \"{title}\".", fg='red'))
            return None

        # 3. Present choices
        click.echo("Found potential matches on Hardcover:")
        for i, res in enumerate(results, 1):
            click.echo(f"  {i}. {res['title']} ({res['author_name']}) [ID: {res['id']}]")
        
        click.echo("  0. Skip this book")
        
        choice = click.prompt("Select the correct book", type=int, default=1)
        
        if choice == 0:
            return None
        
        if 1 <= choice <= len(results):
            selected = results[choice - 1]
            hardcover_id = str(selected['id'])
            self.db.save_book_mapping(local_id, hardcover_id, selected['title'], selected['author_name'])
            click.echo(click.style(f"  Mapped to: {selected['title']}", fg='green'))
            return hardcover_id
        
        return None
