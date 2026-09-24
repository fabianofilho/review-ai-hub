"""
Article Import Service.

Centralized business logic for importing articles from CSV and PDF sources.
Uses CanonicalArticlePayload and ArticleRepository for consistent normalization
and deduplication across all ingestion flows.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import LoggerMixin
from app.infrastructure.storage.base import StorageAdapter
from app.models.article import Article, ArticleFile
from app.repositories.article_repository import ArticleFileRepository, ArticleRepository
from app.schemas.article_import import CSVImportResult
from app.services.article_source_normalization import (
    normalize_pdf_ai_entry,
    normalize_scopus_csv_row,
)

# PDFs imported via AI are first uploaded by the browser to this per-user area
# of the "articles" bucket, then moved to {project_id}/{article_id}/{filename}.
TEMP_UPLOAD_ROOT = "temp"
DEFAULT_PDF_FILENAME = "document.pdf"

# Characters that the storage client does not keep as part of the object path.
# It parses keys as URLs: "%" is percent-decoded ("%2e%2e" becomes ".." and is
# then resolved), while "?" and "#" start a query or a fragment. A key holding
# them would be validated as one object and downloaded as another.
URL_UNSAFE_KEY_CHARS = frozenset("%?#")


def temp_upload_prefix(user_id: str) -> str:
    """Storage prefix where the given user uploads PDFs before import."""
    return f"{TEMP_UPLOAD_ROOT}/{user_id}/"


def is_user_temp_storage_key(storage_key: str, user_id: str) -> bool:
    """
    True when storage_key is an object inside the user's temporary upload area.

    Storage is accessed with the service role, so a key taken from the request
    must not point outside that area (another project's file, "..", encoded
    "%2e%2e", etc.).
    """
    prefix = temp_upload_prefix(user_id)
    if not storage_key.startswith(prefix) or len(storage_key) == len(prefix):
        return False
    if "\\" in storage_key or any(ch in URL_UNSAFE_KEY_CHARS for ch in storage_key):
        return False
    return all(segment not in ("", ".", "..") for segment in storage_key.split("/"))


def sanitize_filename(filename: str | None) -> str:
    """
    Keep only the base name of an uploaded file.

    Directories and control characters are dropped, and URL-unsafe characters
    are replaced with "_" because the name becomes part of a storage key.
    """
    name = (filename or "").replace("\\", "/").split("/")[-1]
    name = "".join(
        "_" if ch in URL_UNSAFE_KEY_CHARS else ch for ch in name if ch.isprintable()
    ).strip()
    if name in ("", ".", ".."):
        return DEFAULT_PDF_FILENAME
    return name


class ArticleImportService(LoggerMixin):
    """Service for importing articles from CSV and PDF sources."""

    def __init__(self, db: AsyncSession, storage: StorageAdapter | None = None):
        self.db = db
        self.storage = storage
        self.article_repo = ArticleRepository(db)
        self.file_repo = ArticleFileRepository(db)

    async def import_csv_scopus(
        self,
        *,
        project_id: UUID,
        rows: list[dict[str, str]],
    ) -> CSVImportResult:
        """
        Import articles from parsed Scopus CSV rows.

        Uses CanonicalArticlePayload for normalization and
        ArticleRepository.upsert_by_canonical_identity for deduplication.
        """
        success_count = 0
        fail_count = 0
        duplicate_count = 0
        errors: list[str] = []

        for i, row in enumerate(rows):
            try:
                title = (row.get("Title") or "").strip()
                if not title:
                    fail_count += 1
                    errors.append(f"Row {i + 2}: Missing title")
                    continue

                payload = normalize_scopus_csv_row(row)
                payload.article_fields["project_id"] = str(project_id)

                article, created = await self.article_repo.upsert_by_canonical_identity(
                    project_id=project_id,
                    payload=payload.article_fields,
                    canonical_identity=payload.canonical_identity,
                )

                if created:
                    success_count += 1
                else:
                    duplicate_count += 1

            except Exception as e:
                fail_count += 1
                title_preview = (row.get("Title") or "?")[:50]
                errors.append(f"Row {i + 2} ({title_preview}): {str(e)[:100]}")

        await self.db.flush()

        return CSVImportResult(
            success_count=success_count,
            fail_count=fail_count,
            duplicate_count=duplicate_count,
            errors=errors[:20],
        )

    async def create_from_pdf_metadata(
        self,
        *,
        project_id: UUID,
        metadata: dict,
        storage_key: str,
        original_filename: str,
        file_bytes: int = 0,
    ) -> Article:
        """
        Create an article from AI-extracted PDF metadata.

        Normalizes metadata, upserts the article via canonical identity,
        moves the PDF to the permanent path, and creates the ArticleFile record.
        All in one DB transaction.
        """
        # The client-provided name becomes part of the storage path.
        original_filename = sanitize_filename(original_filename)

        payload = normalize_pdf_ai_entry(metadata)
        payload.article_fields["project_id"] = str(project_id)

        article, _created = await self.article_repo.upsert_by_canonical_identity(
            project_id=project_id,
            payload=payload.article_fields,
            canonical_identity=payload.canonical_identity,
        )
        await self.db.flush()

        # Move PDF from temp path to permanent path under article ID
        final_key = storage_key
        if self.storage:
            new_key = f"{project_id}/{article.id}/{original_filename}"
            moved = await self.storage.move("articles", storage_key, new_key)
            if moved:
                final_key = new_key

        # Create article_files record
        article_file = ArticleFile(
            project_id=project_id,
            article_id=article.id,
            file_type="application/pdf",
            file_role="MAIN",
            storage_key=final_key,
            original_filename=original_filename,
            bytes=file_bytes or None,
        )
        await self.file_repo.create(article_file)

        return article
