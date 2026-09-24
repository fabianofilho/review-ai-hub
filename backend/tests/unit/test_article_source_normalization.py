from app.services.article_source_normalization import (
    normalize_manual_entry,
    normalize_ris_entry,
    normalize_zotero_item,
)


def test_normalize_zotero_item_preserves_identity() -> None:
    payload = normalize_zotero_item(
        item={
            "key": "ABCD1234",
            "version": 1,
            "data": {
                "title": "Title",
                "DOI": "https://doi.org/10.1000/xyz",
                "url": "https://example.org/paper/",
                "creators": [{"creatorType": "author", "name": "Jane Doe"}],
            },
        },
        collection_key="COLL01",
    )
    assert payload.canonical_identity["zotero_item_key"] == "ABCD1234"
    assert payload.canonical_identity["doi"] == "10.1000/xyz"
    assert payload.canonical_identity["url_landing"] == "https://example.org/paper"
    assert payload.source_lineage == "zotero"


def test_cross_source_lineage_does_not_change_identity_keys() -> None:
    ris = normalize_ris_entry(
        {
            "title": "Title",
            "doi": "10.1000/xyz",
            "url": "https://example.org/paper",
            "authors": ["Jane Doe"],
        }
    )
    manual = normalize_manual_entry(
        {
            "title": "Title",
            "doi": "doi:10.1000/xyz",
            "url_landing": "https://example.org/paper/",
            "authors": ["Jane Doe"],
        }
    )
    assert ris.canonical_identity["doi"] == manual.canonical_identity["doi"] == "10.1000/xyz"
    assert (
        ris.canonical_identity["url_landing"]
        == manual.canonical_identity["url_landing"]
        == "https://example.org/paper"
    )
    assert ris.source_lineage == "ris"
    assert manual.source_lineage == "manual"
