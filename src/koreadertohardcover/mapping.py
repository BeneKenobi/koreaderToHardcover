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
        # 1. Check if already mapped in local DB
        existing = self.db.get_book_mapping(local_id)
        if existing:
            return existing

        click.echo(
            click.style(f'\nNo mapping found for: "{title}" by {author}', fg="yellow")
        )

        # 2. Search user's shelf first
        click.echo(f'  Searching your shelf for "{title}"...')
        shelf_results = self.client.search_shelf(title)

        if len(shelf_results) == 1:
            selected = shelf_results[0]
            click.echo(
                click.style(
                    f"  Found exact match on your shelf: {selected['title']} ({selected['author_name']})",
                    fg="green",
                )
            )
            self.db.save_book_mapping(
                local_id,
                str(selected["id"]),
                selected["title"],
                selected["author_name"],
            )
            return str(selected["id"])

        if len(shelf_results) > 1:
            click.echo("  Found multiple matches on your shelf:")
            results = shelf_results
        else:
            # 3. Fallback to global search
            click.echo(
                f'  Not found on shelf. Searching global Hardcover library for "{title}"...'
            )
            results = self.client.search_books(title)

        if not results:
            click.echo(
                click.style(f'  No matches found on Hardcover for "{title}".', fg="red")
            )
            return None

        # Check for canonical matches on shelf
        for res in results:
            if res.get("canonical_id"):
                canon_id = res["canonical_id"]
                if self.client.is_book_on_shelf(canon_id):
                    click.echo(
                        click.style(
                            f"  Found canonical match on shelf: ID {canon_id} (linked to {res['title']})",
                            fg="green",
                        )
                    )
                    # Verify we want to map to canonical
                    if click.confirm(
                        f"  Map to canonical book ID {canon_id}?", default=True
                    ):
                        self.db.save_book_mapping(
                            local_id, str(canon_id), res["title"], res["author_name"]
                        )
                        return str(canon_id)

        # 4. Present choices
        click.echo("Potential matches:")
        for i, res in enumerate(results, 1):
            click.echo(
                f"  {i}. {res['title']} ({res['author_name']}) [ID: {res['id']}]"
            )

        click.echo("  0. Skip this book")
        click.echo("  s. Search for a different title")

        choice_str = click.prompt("Select the correct book", default="1")

        if choice_str == "0":
            return None

        if choice_str.lower() == "s":
            new_title = click.prompt("Enter new title to search")
            return self.map_book(local_id, new_title, author)

        try:
            choice = int(choice_str)
            if 1 <= choice <= len(results):
                selected = results[choice - 1]
                hardcover_id = str(selected["id"])
                self.db.save_book_mapping(
                    local_id, hardcover_id, selected["title"], selected["author_name"]
                )
                click.echo(click.style(f"  Mapped to: {selected['title']}", fg="green"))
                return hardcover_id
        except ValueError:
            pass

        return None
