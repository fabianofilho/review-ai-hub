from app.services.article_source_normalization import (
    normalize_manual_entry,
    normalize_ris_entry,
    normalize_zotero_item,
)


def test_cross_source_identity_is_stable() -> None:
    zotero = normalize_zotero_item(
        item={
            "key": "ZKEY1234",
            "version": 1,
            "data": {
                "title": "Same Article",
                "DOI": "10.1000/same",
                "url": "https://example.com/same",
                "creators": [{"creatorType": "author", "name": "Alice"}],
            },
        },
        collection_key="COLL",
    )
    ris = normalize_ris_entry(
        {
            "title": "Same Article",
            "doi": "10.1000/same",
            "url": "https://example.com/same/",
            "authors": ["Alice"],
        }
    )
    manual = normalize_manual_entry(
        {
            "title": "Same Article",
            "doi": "doi:10.1000/same",
            "url_landing": "https://example.com/same/",
            "authors": ["Alice"],
        }
    )

    assert (
        zotero.canonical_identity["doi"]
        == ris.canonical_identity["doi"]
        == manual.canonical_identity["doi"]
    )
    assert ris.canonical_identity["url_landing"] == manual.canonical_identity["url_landing"]
