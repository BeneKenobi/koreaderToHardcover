import click
from typing import Optional
from koreadertohardcover.hardcover_client import HardcoverClient
from koreadertohardcover.database import DatabaseManager


class InteractiveMapper:
    def __init__(self, client: HardcoverClient, db: DatabaseManager):
        self.client = client
        self.db = db

    def map_book(
        self, local_id: str, title: str, author: str, force: bool = False
    ) -> Optional[tuple[str, Optional[str]]]:
        """
        Interactive flow to map a local book to Hardcover.
        Returns (hardcover_id, edition_id)
        """
        # 1. Check if already mapped in local DB
        if not force:
            existing = self.db.get_book_mapping(local_id)
            if existing:
                return existing

        # Get local book details for comparison
        conn = self.db.get_connection()
        local_book = conn.execute(
            "SELECT total_pages FROM books WHERE id = ?", [local_id]
        ).fetchone()
        local_pages = local_book[0] if local_book else 0

        click.echo(
            click.style(
                f'\n{"Remapping" if force else "No mapping found for"}: "{title}" by {author}',
                fg="yellow",
            )
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
            # We don't have edition here from shelf search yet, maybe we should fetch it
            hc_id = str(selected["id"])
            edition_id = self._ask_for_edition(hc_id, author, local_pages)
            self.db.save_book_mapping(
                local_id,
                hc_id,
                edition_id,
                selected["title"],
                selected["author_name"],
                selected.get("slug"),
            )
            return (hc_id, edition_id)

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

                # Ask for edition
                edition_id = self._ask_for_edition(hardcover_id, author, local_pages)

                self.db.save_book_mapping(
                    local_id,
                    hardcover_id,
                    edition_id,
                    selected["title"],
                    selected["author_name"],
                    selected.get("slug"),
                )
                click.echo(click.style(f"  Mapped to: {selected['title']}", fg="green"))
                return (hardcover_id, edition_id)
        except ValueError:
            pass

        return None

    def _ask_for_edition(
        self, book_id: str, local_author: str, local_pages: int
    ) -> Optional[str]:
        """Interactive flow to select an edition for a book."""
        click.echo(
            f"  Fetching editions (Local Author: {local_author}, Local Pages: {local_pages})..."
        )
        editions = self.client.get_editions(int(book_id))

        if not editions:
            click.echo("  No editions found. Mapping to the general book.")
            return None

        click.echo("  Select an edition:")
        for i, ed in enumerate(editions, 1):
            fmt = ed.get("edition_format") or "Unknown format"
            lang = ed.get("language") or "Unknown"

            pages_val = ed.get("pages")
            pages_str = f"{pages_val} pages" if pages_val else "unknown pages"

            # Highlight page count if it matches local pages
            if pages_val and abs(pages_val - local_pages) < 5:  # fuzzy match
                pages_str = click.style(pages_str, fg="green")

            date = ed.get("release_date") or "unknown date"
            click.echo(f"    {i}. {fmt}, {lang}, {pages_str} ({date}) [ID: {ed['id']}]")

        click.echo("    0. None (use general book)")

        choice_str = click.prompt("  Select edition", default="0")
        if choice_str == "0":
            return None

        try:
            choice = int(choice_str)
            if 1 <= choice <= len(editions):
                selected = editions[choice - 1]
                return str(selected["id"])
        except ValueError:
            pass

        return None
