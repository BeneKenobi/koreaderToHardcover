from koreadertohardcover.ranking import (
    format_group,
    normalize_language,
    rank_editions,
    rank_search_results,
)


def _edition(**fields) -> dict:
    base = {
        "id": 0,
        "edition_format": None,
        "reading_format": None,
        "language": "Unknown",
        "language_codes": [],
        "pages": None,
        "users_count": 0,
    }
    base.update(fields)
    return base


def test_normalize_language() -> None:
    assert normalize_language("de") == "de"
    assert normalize_language("de-DE") == "de"
    assert normalize_language("de_AT") == "de"
    assert normalize_language("N/A") is None
    assert normalize_language(None) is None


def test_format_groups() -> None:
    assert format_group(_edition(edition_format="Kindle Edition")) == "Ebook"
    assert format_group(_edition(reading_format="Ebook")) == "Ebook"
    assert format_group(_edition(edition_format="Mass Market Paperback")) == "Paperback"
    assert format_group(_edition(edition_format="Taschenbuch")) == "Paperback"
    assert format_group(_edition(edition_format="Hardcover")) == "Hardcover"
    assert format_group(_edition(edition_format="Audio CD")) == "Audiobook"
    assert format_group(_edition(reading_format="Listened")) == "Audiobook"
    assert format_group(_edition(edition_format=None)) == "Other"


def test_rank_editions_prefers_language_then_ebook_then_pages() -> None:
    editions = [
        _edition(id=1, language="English", language_codes=["en"], users_count=999),
        _edition(id=2, language="German", language_codes=["de", "ger"]),
        _edition(
            id=3, language="German", language_codes=["de"], edition_format="Kindle"
        ),
        _edition(
            id=4,
            language="German",
            language_codes=["de"],
            edition_format="ebook",
            pages=300,
        ),
        _edition(id=5, pages=None),
    ]

    ranked = rank_editions(editions, "de-DE", 310)

    assert [e["id"] for e in ranked] == [4, 3, 2, 1, 5]
    assert ranked[0]["language_match"] and ranked[0]["pages_match"]


def test_rank_editions_popularity_breaks_ties() -> None:
    editions = [_edition(id=1, users_count=5), _edition(id=2, users_count=50)]

    assert [e["id"] for e in rank_editions(editions, None, None)] == [2, 1]


def test_shelf_results_come_first() -> None:
    results = [{"id": "1"}, {"id": "2"}, {"id": "3"}]

    ranked = rank_search_results(results, {3})

    assert [r["id"] for r in ranked] == ["3", "1", "2"]
    assert ranked[0]["on_shelf"] and not ranked[1]["on_shelf"]
