"""Orders Hardcover search results and editions so the likely match comes first."""

from typing import Any, Dict, List, Optional

EBOOK_FORMAT_HINTS = ("ebook", "e-book", "kindle", "epub", "digital")
# KOReader and print page counts rarely agree exactly.
PAGE_TOLERANCE = 0.1


def normalize_language(language: Optional[str]) -> Optional[str]:
    """Turns KOReader values like 'de', 'de-DE' or 'de_AT' into 'de'."""
    if not language or language.strip().upper() == "N/A":
        return None
    return language.strip().lower().replace("_", "-").split("-")[0]


def is_ebook(edition: Dict[str, Any]) -> bool:
    if edition.get("reading_format") == "Ebook":
        return True
    edition_format = (edition.get("edition_format") or "").lower()
    return any(hint in edition_format for hint in EBOOK_FORMAT_HINTS)


FORMAT_GROUPS = ("Ebook", "Paperback", "Hardcover", "Audiobook", "Other")
AUDIO_FORMAT_HINTS = ("audio", "cassette", "cd", "mp3", "hörbuch")
HARDCOVER_FORMAT_HINTS = ("hardcover", "hardback", "gebunden", "library binding")
PAPERBACK_FORMAT_HINTS = (
    "paperback",
    "softcover",
    "soft cover",
    "taschenbuch",
    "broschiert",
    "mass market",
    "trade",
)


def format_group(edition: Dict[str, Any]) -> str:
    """Maps Hardcover's free-text edition formats onto a few filterable groups."""
    edition_format = (edition.get("edition_format") or "").lower()
    if edition.get("reading_format") == "Listened" or any(
        hint in edition_format for hint in AUDIO_FORMAT_HINTS
    ):
        return "Audiobook"
    if is_ebook(edition):
        return "Ebook"
    if any(hint in edition_format for hint in HARDCOVER_FORMAT_HINTS):
        return "Hardcover"
    if any(hint in edition_format for hint in PAPERBACK_FORMAT_HINTS):
        return "Paperback"
    return "Other"


def language_matches(edition: Dict[str, Any], local_language: Optional[str]) -> bool:
    if not local_language:
        return False
    codes = [code.lower() for code in edition.get("language_codes", [])]
    name = (edition.get("language") or "").lower()
    return local_language in codes or local_language == name


def pages_match(edition: Dict[str, Any], local_pages: Optional[int]) -> bool:
    pages = edition.get("pages")
    if not pages or not local_pages:
        return False
    return abs(pages - local_pages) <= local_pages * PAGE_TOLERANCE


def rank_editions(
    editions: List[Dict[str, Any]],
    local_language: Optional[str],
    local_pages: Optional[int],
) -> List[Dict[str, Any]]:
    """
    Sorts editions by language match, ebook format, similar page count and
    popularity. Each edition gets 'language_match', 'is_ebook' and 'pages_match'
    flags for display.
    """
    language = normalize_language(local_language)
    for edition in editions:
        edition["language_match"] = language_matches(edition, language)
        edition["is_ebook"] = is_ebook(edition)
        edition["pages_match"] = pages_match(edition, local_pages)
        edition["format_group"] = format_group(edition)

    return sorted(
        editions,
        key=lambda e: (
            not e["language_match"],
            not e["is_ebook"],
            not e["pages_match"],
            -(e.get("users_count") or 0),
        ),
    )


def rank_search_results(
    results: List[Dict[str, Any]], shelf_ids: set[int]
) -> List[Dict[str, Any]]:
    """Puts books from the user's shelf first and keeps the search order otherwise."""
    for result in results:
        result["on_shelf"] = int(result["id"]) in shelf_ids
    return sorted(results, key=lambda r: not r["on_shelf"])
