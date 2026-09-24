"""
Extended unit tests for app.services.article_source_normalization.

Complements test_article_source_normalization.py with the field helpers and
the full field mapping of every ingestion source (Zotero, RIS, manual,
Scopus CSV and AI-extracted PDF metadata).
"""

from typing import Any

import pytest

from app.services.article_source_normalization import (
    CanonicalArticlePayload,
    _clean,
    extract_year,
    normalize_author_display_name,
    normalize_doi,
    normalize_manual_entry,
    normalize_pdf_ai_entry,
    normalize_ris_entry,
    normalize_scopus_csv_row,
    normalize_url,
    normalize_zotero_item,
)


class TestClean:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [(None, None), ("", None), ("   \t\n", None), ("  text  ", "text"), ("x", "x")],
    )
    def test_clean(self, value: str | None, expected: str | None) -> None:
        assert _clean(value) == expected


class TestNormalizeDoi:
    @pytest.mark.parametrize(
        ("doi", "expected"),
        [
            (None, None),
            ("", None),
            ("   ", None),
            ("10.1000/ABC", "10.1000/abc"),
            ("  10.1000/abc  ", "10.1000/abc"),
            ("https://doi.org/10.1000/XYZ", "10.1000/xyz"),
            ("HTTPS://DOI.ORG/10.1000/xyz", "10.1000/xyz"),
            ("doi:10.1000/xyz", "10.1000/xyz"),
            ("DOI:10.1000/XYZ", "10.1000/xyz"),
        ],
    )
    def test_normalize_doi(self, doi: str | None, expected: str | None) -> None:
        assert normalize_doi(doi) == expected


class TestNormalizeUrl:
    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            (None, None),
            ("", None),
            ("  ", None),
            ("https://example.org/paper", "https://example.org/paper"),
            (" https://example.org/paper/ ", "https://example.org/paper"),
            ("https://example.org/paper///", "https://example.org/paper"),
        ],
    )
    def test_normalize_url(self, url: str | None, expected: str | None) -> None:
        assert normalize_url(url) == expected


class TestExtractYear:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (None, None),
            ("", None),
            ("no year here", None),
            ("12345", None),
            ("2021", 2021),
            ("2021-05-03", 2021),
            ("May 2019", 2019),
            ("03/2018", 2018),
        ],
    )
    def test_extract_year(self, value: str | None, expected: int | None) -> None:
        assert extract_year(value) == expected


class TestNormalizeAuthorDisplayName:
    def test_uses_single_name_field(self) -> None:
        assert normalize_author_display_name({"name": "  WHO Group  "}) == "WHO Group"

    def test_name_field_takes_precedence(self) -> None:
        creator = {"name": "Consortium", "firstName": "Jane", "lastName": "Doe"}

        assert normalize_author_display_name(creator) == "Consortium"

    def test_formats_last_comma_first(self) -> None:
        creator = {"firstName": " Jane ", "lastName": " Doe "}

        assert normalize_author_display_name(creator) == "Doe, Jane"

    def test_only_last_name(self) -> None:
        assert normalize_author_display_name({"lastName": "Doe"}) == "Doe"

    def test_only_first_name(self) -> None:
        assert normalize_author_display_name({"firstName": "Jane"}) == "Jane"

    @pytest.mark.parametrize(
        "creator",
        [{}, {"firstName": None, "lastName": "   "}, {"name": ""}],
    )
    def test_unknown_when_no_usable_name(self, creator: dict[str, Any]) -> None:
        assert normalize_author_display_name(creator) == "Unknown"


class TestNormalizeZoteroItem:
    def test_maps_all_fields(self) -> None:
        item = {
            "key": "ITEM0001",
            "version": 42,
            "data": {
                "title": "Deep Learning for Sepsis",
                "abstractNote": "An abstract.",
                "date": "2020-11-01",
                "publicationTitle": "Critical Care",
                "ISSN": "1234-5678",
                "volume": "24",
                "issue": "3",
                "pages": "10-20",
                "DOI": "DOI:10.1186/ABC",
                "url": "https://example.org/sepsis/",
                "creators": [
                    {"creatorType": "author", "firstName": "Jane", "lastName": "Doe"},
                    {"name": "Sepsis Consortium"},
                    {"creatorType": "editor", "firstName": "Ed", "lastName": "Itor"},
                    "not-a-dict",
                ],
                "tags": [{"tag": "sepsis"}, {"tag": ""}, {"type": 1}, {"tag": "ml"}],
            },
        }

        payload = normalize_zotero_item(item=item, collection_key="COLL9")

        assert isinstance(payload, CanonicalArticlePayload)
        assert payload.source_lineage == "zotero"
        assert payload.canonical_identity == {
            "zotero_item_key": "ITEM0001",
            "doi": "10.1186/abc",
            "url_landing": "https://example.org/sepsis",
        }
        assert payload.creator_rows == [
            {
                "creator_type": "author",
                "display_name": "Doe, Jane",
                "raw": {"creatorType": "author", "firstName": "Jane", "lastName": "Doe"},
            },
            {
                "creator_type": "author",
                "display_name": "Sepsis Consortium",
                "raw": {"name": "Sepsis Consortium"},
            },
            {
                "creator_type": "editor",
                "display_name": "Itor, Ed",
                "raw": {"creatorType": "editor", "firstName": "Ed", "lastName": "Itor"},
            },
        ]
        fields = payload.article_fields
        assert fields["title"] == "Deep Learning for Sepsis"
        assert fields["abstract"] == "An abstract."
        assert fields["publication_year"] == 2020
        assert fields["journal_title"] == "Critical Care"
        assert fields["journal_issn"] == "1234-5678"
        assert fields["volume"] == "24"
        assert fields["issue"] == "3"
        assert fields["pages"] == "10-20"
        assert fields["doi"] == "10.1186/abc"
        assert fields["url_landing"] == "https://example.org/sepsis"
        assert fields["authors"] == ["Doe, Jane", "Sepsis Consortium"]
        assert fields["keywords"] == ["sepsis", "ml"]
        assert fields["ingestion_source"] == "zotero"
        assert fields["source_payload"] is item
        assert fields["zotero_item_key"] == "ITEM0001"
        assert fields["zotero_collection_key"] == "COLL9"
        assert fields["zotero_version"] == 42
        assert fields["sync_state"] == "active"
        assert fields["source_lineage"] == "zotero"

    def test_minimal_item_uses_defaults(self) -> None:
        payload = normalize_zotero_item(item={"key": "K1"}, collection_key="C1")

        fields = payload.article_fields
        assert fields["title"] == "Untitled"
        assert fields["abstract"] is None
        assert fields["publication_year"] is None
        assert fields["doi"] is None
        assert fields["url_landing"] is None
        assert fields["authors"] is None
        assert fields["keywords"] is None
        assert fields["zotero_version"] is None
        assert payload.creator_rows == []
        assert payload.canonical_identity == {
            "zotero_item_key": "K1",
            "doi": None,
            "url_landing": None,
        }

    def test_only_editors_yields_no_authors(self) -> None:
        item = {
            "key": "K2",
            "data": {"creators": [{"creatorType": "editor", "lastName": "Smith"}]},
        }

        payload = normalize_zotero_item(item=item, collection_key="C1")

        assert payload.article_fields["authors"] is None
        assert [row["display_name"] for row in payload.creator_rows] == ["Smith"]


class TestNormalizeRisEntry:
    def test_maps_all_fields(self) -> None:
        entry = {
            "title": "RIS Title",
            "abstract": "RIS abstract",
            "year": 2019,
            "journal": "BMJ",
            "doi": "https://doi.org/10.1136/BMJ.1",
            "url": "https://bmj.com/a/",
            "authors": ["Doe, Jane", "  ", "Smith, John "],
            "keywords": ["k1", "k2"],
        }

        payload = normalize_ris_entry(entry)

        assert payload.source_lineage == "ris"
        assert payload.canonical_identity == {
            "zotero_item_key": None,
            "doi": "10.1136/bmj.1",
            "url_landing": "https://bmj.com/a",
        }
        assert payload.creator_rows == [
            {"creator_type": "author", "display_name": "Doe, Jane", "raw": {"name": "Doe, Jane"}},
            {
                "creator_type": "author",
                "display_name": "Smith, John",
                "raw": {"name": "Smith, John "},
            },
        ]
        fields = payload.article_fields
        assert fields["title"] == "RIS Title"
        assert fields["abstract"] == "RIS abstract"
        assert fields["publication_year"] == 2019
        assert fields["journal_title"] == "BMJ"
        assert fields["authors"] == ["Doe, Jane", "Smith, John"]
        assert fields["keywords"] == ["k1", "k2"]
        assert fields["ingestion_source"] == "ris"
        assert fields["source_payload"] is entry
        assert fields["sync_state"] == "active"
        assert fields["source_lineage"] == "ris"

    def test_empty_entry_uses_defaults(self) -> None:
        payload = normalize_ris_entry({})

        assert payload.article_fields["title"] == "Untitled"
        assert payload.article_fields["authors"] is None
        assert payload.article_fields["doi"] is None
        assert payload.creator_rows == []


class TestNormalizeManualEntry:
    def test_maps_all_fields(self) -> None:
        entry = {
            "title": "Manual Title",
            "abstract": "Manual abstract",
            "publication_year": 2022,
            "journal_title": "Lancet",
            "doi": " 10.1016/S0140 ",
            "url_landing": "https://thelancet.com/x/",
            "authors": ["Jane Doe", "", 123],
        }

        payload = normalize_manual_entry(entry)

        assert payload.source_lineage == "manual"
        assert payload.canonical_identity == {
            "zotero_item_key": None,
            "doi": "10.1016/s0140",
            "url_landing": "https://thelancet.com/x",
        }
        assert payload.creator_rows == [
            {"creator_type": "author", "display_name": "Jane Doe", "raw": {"name": "Jane Doe"}},
            {"creator_type": "author", "display_name": "123", "raw": {"name": 123}},
        ]
        fields = payload.article_fields
        assert fields["title"] == "Manual Title"
        assert fields["abstract"] == "Manual abstract"
        assert fields["publication_year"] == 2022
        assert fields["journal_title"] == "Lancet"
        assert fields["authors"] == ["Jane Doe", "123"]
        assert fields["ingestion_source"] == "manual"
        assert fields["source_payload"] is entry
        assert fields["source_lineage"] == "manual"

    def test_empty_entry_uses_defaults(self) -> None:
        payload = normalize_manual_entry({"title": ""})

        assert payload.article_fields["title"] == "Untitled"
        assert payload.article_fields["authors"] is None
        assert payload.canonical_identity["doi"] is None


def _scopus_row(**overrides: str) -> dict[str, str]:
    row = {
        "Title": "  Scopus Title  ",
        "DOI": "10.1016/J.X.2021",
        "Link": "https://www.scopus.com/record/1/",
        "Authors": "Doe J.; Smith A.; ",
        "Year": "2021",
        "Page start": "100",
        "Page end": "110",
        "Author Keywords": "sepsis; machine learning",
        "Index Keywords": "machine learning; sepsis;; ICU",
        "Open Access": "All Open Access; Gold",
        "Abstract": " Abstract text ",
        "Source title": "Journal of X",
        "Volume": "12",
        "Issue": "4",
        "Document Type": "Article",
        "Publication Stage": "Final",
        "EID": "2-s2.0-123",
        "Cited by": "7",
        "Source": "Scopus",
        "Author full names": "Doe, John (1); Smith, Anna (2)",
        "Author(s) ID": "1;2",
        "Art. No.": "e123",
    }
    row.update(overrides)
    return row


class TestNormalizeScopusCsvRow:
    def test_maps_all_fields(self) -> None:
        payload = normalize_scopus_csv_row(_scopus_row())

        assert payload.source_lineage == "csv_scopus"
        assert payload.canonical_identity == {
            "zotero_item_key": None,
            "doi": "10.1016/j.x.2021",
            "url_landing": "https://www.scopus.com/record/1",
        }
        assert payload.creator_rows == [
            {"creator_type": "author", "display_name": "Doe J.", "raw": {"name": "Doe J."}},
            {"creator_type": "author", "display_name": "Smith A.", "raw": {"name": "Smith A."}},
        ]
        fields = payload.article_fields
        assert fields["title"] == "Scopus Title"
        assert fields["abstract"] == "Abstract text"
        assert fields["authors"] == ["Doe J.", "Smith A."]
        assert fields["publication_year"] == 2021
        assert fields["journal_title"] == "Journal of X"
        assert fields["volume"] == "12"
        assert fields["issue"] == "4"
        assert fields["pages"] == "100-110"
        assert fields["doi"] == "10.1016/j.x.2021"
        # Both keyword columns are merged and deduplicated in order of first appearance.
        assert fields["keywords"] == ["sepsis", "machine learning", "ICU"]
        assert fields["article_type"] == "Article"
        assert fields["open_access"] is True
        assert fields["url_landing"] == "https://www.scopus.com/record/1"
        assert fields["publication_status"] == "Final"
        assert fields["ingestion_source"] == "CSV_SCOPUS"
        assert fields["source_payload"] == {
            "eid": "2-s2.0-123",
            "cited_by": "7",
            "source_db": "Scopus",
            "author_full_names": "Doe, John (1); Smith, Anna (2)",
            "author_ids": "1;2",
            "art_no": "e123",
        }
        assert fields["sync_state"] == "active"
        assert fields["source_lineage"] == "csv_scopus"

    def test_only_page_start(self) -> None:
        payload = normalize_scopus_csv_row(_scopus_row(**{"Page end": " "}))

        assert payload.article_fields["pages"] == "100"

    def test_only_page_end_gives_no_pages(self) -> None:
        payload = normalize_scopus_csv_row(_scopus_row(**{"Page start": ""}))

        assert payload.article_fields["pages"] is None

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("No", False),
            ("false", False),
            ("FALSE", False),
            ("0", False),
            ("Yes", True),
            ("Green", True),
            ("", None),
            ("   ", None),
        ],
    )
    def test_open_access_parsing(self, raw: str, expected: bool | None) -> None:
        payload = normalize_scopus_csv_row(_scopus_row(**{"Open Access": raw}))

        assert payload.article_fields["open_access"] is expected

    def test_empty_row_uses_defaults(self) -> None:
        payload = normalize_scopus_csv_row({})

        fields = payload.article_fields
        assert fields["title"] == "Untitled"
        assert fields["authors"] is None
        assert fields["publication_year"] is None
        assert fields["pages"] is None
        assert fields["keywords"] is None
        assert fields["open_access"] is None
        assert fields["doi"] is None
        assert fields["url_landing"] is None
        assert fields["source_payload"] == {
            "eid": None,
            "cited_by": None,
            "source_db": None,
            "author_full_names": None,
            "author_ids": None,
            "art_no": None,
        }
        assert payload.creator_rows == []


class TestNormalizePdfAiEntry:
    def test_maps_all_fields_with_list_inputs(self) -> None:
        metadata = {
            "title": "  PDF Title ",
            "abstract": " PDF abstract ",
            "authors": ["Jane Doe", "  ", "John Smith "],
            "publication_year": 2023,
            "publication_month": 7,
            "journal_title": " Nature Medicine ",
            "journal_issn": " 1078-8956 ",
            "volume": " 29 ",
            "issue": " 7 ",
            "pages": " 1-10 ",
            "doi": "https://doi.org/10.1038/S41591",
            "pmid": " 123456 ",
            "pmcid": " PMC999 ",
            "keywords": ["ai", "health"],
            "article_type": " research ",
            "language": " en ",
            "url_landing": "https://nature.com/articles/x/",
            "study_design": " cohort ",
        }

        payload = normalize_pdf_ai_entry(metadata)

        assert payload.source_lineage == "pdf_ai"
        assert payload.canonical_identity == {
            "zotero_item_key": None,
            "doi": "10.1038/s41591",
            "url_landing": "https://nature.com/articles/x",
        }
        assert payload.creator_rows == [
            {"creator_type": "author", "display_name": "Jane Doe", "raw": {"name": "Jane Doe"}},
            {
                "creator_type": "author",
                "display_name": "John Smith",
                "raw": {"name": "John Smith "},
            },
        ]
        fields = payload.article_fields
        assert fields["title"] == "PDF Title"
        assert fields["abstract"] == "PDF abstract"
        assert fields["authors"] == ["Jane Doe", "John Smith"]
        assert fields["publication_year"] == 2023
        assert fields["publication_month"] == 7
        assert fields["journal_title"] == "Nature Medicine"
        assert fields["journal_issn"] == "1078-8956"
        assert fields["volume"] == "29"
        assert fields["issue"] == "7"
        assert fields["pages"] == "1-10"
        assert fields["doi"] == "10.1038/s41591"
        assert fields["pmid"] == "123456"
        assert fields["pmcid"] == "PMC999"
        assert fields["keywords"] == ["ai", "health"]
        assert fields["article_type"] == "research"
        assert fields["language"] == "en"
        assert fields["url_landing"] == "https://nature.com/articles/x"
        assert fields["study_design"] == "cohort"
        assert fields["ingestion_source"] == "PDF_AI"
        assert fields["source_payload"] is metadata
        assert fields["sync_state"] == "active"
        assert fields["source_lineage"] == "pdf_ai"

    def test_splits_comma_separated_strings(self) -> None:
        payload = normalize_pdf_ai_entry(
            {"authors": "Jane Doe, John Smith, ", "keywords": "ai,  health ,"}
        )

        assert payload.article_fields["authors"] == ["Jane Doe", "John Smith"]
        assert [row["display_name"] for row in payload.creator_rows] == ["Jane Doe", "John Smith"]
        assert payload.article_fields["keywords"] == ["ai", "health"]

    def test_empty_metadata_uses_defaults(self) -> None:
        payload = normalize_pdf_ai_entry({"title": "   ", "authors": "", "keywords": ""})

        fields = payload.article_fields
        assert fields["title"] == "Untitled"
        assert fields["authors"] is None
        assert fields["keywords"] is None
        assert fields["doi"] is None
        assert fields["abstract"] is None
        assert payload.creator_rows == []
