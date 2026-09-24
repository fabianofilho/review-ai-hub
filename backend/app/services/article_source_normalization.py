"""
Canonical normalization for article ingestion sources.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def normalize_doi(doi: str | None) -> str | None:
    cleaned = _clean(doi)
    if not cleaned:
        return None
    return cleaned.lower().removeprefix("https://doi.org/").removeprefix("doi:")


def normalize_url(url: str | None) -> str | None:
    cleaned = _clean(url)
    if not cleaned:
        return None
    return cleaned.rstrip("/")


def extract_year(date_value: str | None) -> int | None:
    if not date_value:
        return None
    match = re.search(r"\b(\d{4})\b", date_value)
    if not match:
        return None
    return int(match.group(1))


def normalize_author_display_name(creator: dict[str, Any]) -> str:
    if creator.get("name"):
        return str(creator["name"]).strip()
    first = str(creator.get("firstName") or "").strip()
    last = str(creator.get("lastName") or "").strip()
    if first and last:
        return f"{last}, {first}"
    return first or last or "Unknown"


@dataclass(slots=True)
class CanonicalArticlePayload:
    canonical_identity: dict[str, str | None]
    article_fields: dict[str, Any]
    creator_rows: list[dict[str, Any]]
    source_lineage: str


def normalize_zotero_item(
    *,
    item: dict[str, Any],
    collection_key: str,
) -> CanonicalArticlePayload:
    data = item.get("data", {})
    creators = list(data.get("creators") or [])
    doi = normalize_doi(data.get("DOI"))
    url_landing = normalize_url(data.get("url"))
    zotero_item_key = item.get("key")
    creator_rows = [
        {
            "creator_type": creator.get("creatorType") or "author",
            "display_name": normalize_author_display_name(creator),
            "raw": creator,
        }
        for creator in creators
        if isinstance(creator, dict)
    ]
    article_fields: dict[str, Any] = {
        "title": data.get("title") or "Untitled",
        "abstract": data.get("abstractNote"),
        "publication_year": extract_year(data.get("date")),
        "journal_title": data.get("publicationTitle"),
        "journal_issn": data.get("ISSN"),
        "volume": data.get("volume"),
        "issue": data.get("issue"),
        "pages": data.get("pages"),
        "doi": doi,
        "url_landing": url_landing,
        "authors": [row["display_name"] for row in creator_rows if row["creator_type"] == "author"]
        or None,
        "keywords": [tag.get("tag") for tag in data.get("tags", []) if tag.get("tag")] or None,
        "ingestion_source": "zotero",
        "source_payload": item,
        "zotero_item_key": zotero_item_key,
        "zotero_collection_key": collection_key,
        "zotero_version": item.get("version"),
        "sync_state": "active",
        "source_lineage": "zotero",
    }

    canonical_identity = {
        "zotero_item_key": zotero_item_key,
        "doi": doi,
        "url_landing": url_landing,
    }
    return CanonicalArticlePayload(
        canonical_identity=canonical_identity,
        article_fields=article_fields,
        creator_rows=creator_rows,
        source_lineage="zotero",
    )


def normalize_ris_entry(entry: dict[str, Any]) -> CanonicalArticlePayload:
    doi = normalize_doi(entry.get("doi"))
    url_landing = normalize_url(entry.get("url"))
    creators = entry.get("authors") or []
    creator_rows = [
        {
            "creator_type": "author",
            "display_name": str(name).strip(),
            "raw": {"name": name},
        }
        for name in creators
        if str(name).strip()
    ]
    article_fields: dict[str, Any] = {
        "title": entry.get("title") or "Untitled",
        "abstract": entry.get("abstract"),
        "publication_year": entry.get("year"),
        "journal_title": entry.get("journal"),
        "doi": doi,
        "url_landing": url_landing,
        "authors": [row["display_name"] for row in creator_rows] or None,
        "keywords": entry.get("keywords"),
        "ingestion_source": "ris",
        "source_payload": entry,
        "sync_state": "active",
        "source_lineage": "ris",
    }
    return CanonicalArticlePayload(
        canonical_identity={"zotero_item_key": None, "doi": doi, "url_landing": url_landing},
        article_fields=article_fields,
        creator_rows=creator_rows,
        source_lineage="ris",
    )


def normalize_manual_entry(entry: dict[str, Any]) -> CanonicalArticlePayload:
    doi = normalize_doi(entry.get("doi"))
    url_landing = normalize_url(entry.get("url_landing"))
    authors = entry.get("authors") or []
    creator_rows = [
        {"creator_type": "author", "display_name": str(name).strip(), "raw": {"name": name}}
        for name in authors
        if str(name).strip()
    ]
    article_fields: dict[str, Any] = {
        "title": entry.get("title") or "Untitled",
        "abstract": entry.get("abstract"),
        "publication_year": entry.get("publication_year"),
        "journal_title": entry.get("journal_title"),
        "doi": doi,
        "url_landing": url_landing,
        "authors": [row["display_name"] for row in creator_rows] or None,
        "ingestion_source": "manual",
        "source_payload": entry,
        "sync_state": "active",
        "source_lineage": "manual",
    }
    return CanonicalArticlePayload(
        canonical_identity={"zotero_item_key": None, "doi": doi, "url_landing": url_landing},
        article_fields=article_fields,
        creator_rows=creator_rows,
        source_lineage="manual",
    )


def normalize_scopus_csv_row(row: dict[str, str]) -> CanonicalArticlePayload:
    """Normalize a single Scopus CSV row into a CanonicalArticlePayload."""
    title = _clean(row.get("Title")) or "Untitled"
    doi = normalize_doi(row.get("DOI"))
    url_landing = normalize_url(row.get("Link"))

    # Parse authors from "LastName, First; LastName2, First2" format
    authors_raw = _clean(row.get("Authors"))
    authors = [a.strip() for a in authors_raw.split(";") if a.strip()] if authors_raw else []
    creator_rows = [
        {"creator_type": "author", "display_name": name, "raw": {"name": name}} for name in authors
    ]

    # Parse year
    publication_year = extract_year(row.get("Year"))

    # Parse pages from start/end
    page_start = _clean(row.get("Page start"))
    page_end = _clean(row.get("Page end"))
    pages = None
    if page_start and page_end:
        pages = f"{page_start}-{page_end}"
    elif page_start:
        pages = page_start

    # Parse keywords (semicolon-separated, deduplicated)
    keywords: list[str] = []
    for kw_field in ("Author Keywords", "Index Keywords"):
        raw = _clean(row.get(kw_field))
        if raw:
            for k in raw.split(";"):
                k = k.strip()
                if k and k not in keywords:
                    keywords.append(k)

    # Parse open access
    oa_raw = _clean(row.get("Open Access"))
    open_access = None
    if oa_raw:
        open_access = oa_raw.lower() not in ("", "no", "false", "0")

    article_fields: dict[str, Any] = {
        "title": title,
        "abstract": _clean(row.get("Abstract")),
        "authors": authors or None,
        "publication_year": publication_year,
        "journal_title": _clean(row.get("Source title")),
        "volume": _clean(row.get("Volume")),
        "issue": _clean(row.get("Issue")),
        "pages": pages,
        "doi": doi,
        "keywords": keywords or None,
        "article_type": _clean(row.get("Document Type")),
        "open_access": open_access,
        "url_landing": url_landing,
        "publication_status": _clean(row.get("Publication Stage")),
        "ingestion_source": "CSV_SCOPUS",
        "source_payload": {
            "eid": _clean(row.get("EID")),
            "cited_by": _clean(row.get("Cited by")),
            "source_db": _clean(row.get("Source")),
            "author_full_names": _clean(row.get("Author full names")),
            "author_ids": _clean(row.get("Author(s) ID")),
            "art_no": _clean(row.get("Art. No.")),
        },
        "sync_state": "active",
        "source_lineage": "csv_scopus",
    }

    return CanonicalArticlePayload(
        canonical_identity={"zotero_item_key": None, "doi": doi, "url_landing": url_landing},
        article_fields=article_fields,
        creator_rows=creator_rows,
        source_lineage="csv_scopus",
    )


def normalize_pdf_ai_entry(metadata: dict[str, Any]) -> CanonicalArticlePayload:
    """Normalize AI-extracted PDF metadata into a CanonicalArticlePayload."""
    doi = normalize_doi(metadata.get("doi"))
    url_landing = normalize_url(metadata.get("url_landing"))

    authors_raw = metadata.get("authors") or []
    if isinstance(authors_raw, str):
        authors_raw = [a.strip() for a in authors_raw.split(",") if a.strip()]
    creator_rows = [
        {"creator_type": "author", "display_name": str(name).strip(), "raw": {"name": name}}
        for name in authors_raw
        if str(name).strip()
    ]

    keywords_raw = metadata.get("keywords") or []
    if isinstance(keywords_raw, str):
        keywords_raw = [k.strip() for k in keywords_raw.split(",") if k.strip()]

    article_fields: dict[str, Any] = {
        "title": _clean(metadata.get("title")) or "Untitled",
        "abstract": _clean(metadata.get("abstract")),
        "authors": [row["display_name"] for row in creator_rows] or None,
        "publication_year": metadata.get("publication_year"),
        "publication_month": metadata.get("publication_month"),
        "journal_title": _clean(metadata.get("journal_title")),
        "journal_issn": _clean(metadata.get("journal_issn")),
        "volume": _clean(metadata.get("volume")),
        "issue": _clean(metadata.get("issue")),
        "pages": _clean(metadata.get("pages")),
        "doi": doi,
        "pmid": _clean(metadata.get("pmid")),
        "pmcid": _clean(metadata.get("pmcid")),
        "keywords": keywords_raw or None,
        "article_type": _clean(metadata.get("article_type")),
        "language": _clean(metadata.get("language")),
        "url_landing": url_landing,
        "study_design": _clean(metadata.get("study_design")),
        "ingestion_source": "PDF_AI",
        "source_payload": metadata,
        "sync_state": "active",
        "source_lineage": "pdf_ai",
    }

    return CanonicalArticlePayload(
        canonical_identity={"zotero_item_key": None, "doi": doi, "url_landing": url_landing},
        article_fields=article_fields,
        creator_rows=creator_rows,
        source_lineage="pdf_ai",
    )
