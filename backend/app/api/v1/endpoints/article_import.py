"""
Article Import Endpoints.

Endpoints for importing articles via PDF metadata extraction and CSV (Scopus) files.
"""

import csv
import io
import uuid

from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form, status

from app.core.deps import CurrentUser, DbSession, SupabaseClient, ensure_project_member
from app.core.error_handler import AuthorizationError
from app.core.factories import create_storage_adapter
from app.core.logging import get_logger
from app.schemas.article_import import (
    PDFCreateArticleRequest,
    PDFMetadataExtractionResponse,
)
from app.schemas.common import ApiResponse
from app.services.api_key_service import APIKeyService
from app.services.article_import_service import (
    ArticleImportService,
    is_user_temp_storage_key,
    temp_upload_prefix,
)
from app.services.pdf_metadata_extraction_service import PDFMetadataExtractionService
from app.utils.rate_limiter import limiter

router = APIRouter()
logger = get_logger(__name__)


def _ensure_user_temp_storage_key(storage_key: str, user_id: str) -> None:
    """
    Only accept PDFs from the caller's own temporary upload area.

    Storage is read and moved with the service role, so any other key would
    let the caller read or take over files of other projects.
    """
    if not is_user_temp_storage_key(storage_key, user_id):
        raise AuthorizationError(
            f"storage_key must be a temporary upload under '{temp_upload_prefix(user_id)}'."
        )


@router.post(
    "/pdf-extract-metadata",
    response_model=ApiResponse,
    summary="Extract metadata from uploaded PDF via AI",
    description="Uploads a PDF and uses AI to extract bibliographic metadata.",
)
@limiter.limit("10/minute")
async def extract_pdf_metadata(
    request: Request,
    project_id: str = Form(...),
    storage_key: str = Form(...),
    original_filename: str = Form(...),
    db: DbSession = None,
    user: CurrentUser = None,
    supabase: SupabaseClient = None,
) -> ApiResponse:
    """
    Extract article metadata from an already-uploaded PDF.

    The PDF must already be in Supabase Storage. This endpoint downloads it,
    sends it to OpenAI for metadata extraction, and returns the extracted fields.
    """
    trace_id = str(uuid.uuid4())

    logger.info(
        "pdf_metadata_extraction_request",
        trace_id=trace_id,
        user_id=user.sub,
        project_id=project_id,
        storage_key=storage_key,
    )

    await ensure_project_member(db, project_id, user.sub)
    _ensure_user_temp_storage_key(storage_key, user.sub)

    try:
        # Resolve BYOK
        api_key_service = APIKeyService(db=db, user_id=user.sub)
        user_openai_key = await api_key_service.get_key_for_provider("openai")

        # Download PDF from storage
        storage = create_storage_adapter(supabase)
        pdf_bytes = await storage.download("articles", storage_key)

        # Extract metadata via AI
        service = PDFMetadataExtractionService(
            trace_id=trace_id,
            openai_api_key=user_openai_key,
        )

        try:
            result = await service.extract_metadata(
                pdf_bytes=pdf_bytes,
                filename=original_filename,
                model="gpt-4o-mini",
            )
        finally:
            await service.close()

        logger.info(
            "pdf_metadata_extraction_success",
            trace_id=trace_id,
            title=result.metadata.title[:80] if result.metadata.title else None,
        )

        return ApiResponse.success(
            data=result.model_dump(by_alias=True),
            trace_id=trace_id,
        )

    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PDF file not found in storage",
        )
    except Exception as e:
        logger.error(
            "pdf_metadata_extraction_error",
            trace_id=trace_id,
            error=str(e),
        )
        return ApiResponse.failure(
            code="PDF_EXTRACTION_ERROR",
            message=str(e),
            trace_id=trace_id,
        )


@router.post(
    "/pdf-create-article",
    response_model=ApiResponse,
    summary="Create article from AI-extracted PDF metadata",
    description="Creates an article record, moves the PDF to permanent storage, and links the file.",
)
@limiter.limit("10/minute")
async def pdf_create_article(
    request: Request,
    body: PDFCreateArticleRequest,
    db: DbSession = None,
    user: CurrentUser = None,
    supabase: SupabaseClient = None,
) -> ApiResponse:
    """
    Create an article from reviewed AI-extracted PDF metadata.

    The frontend calls this after the user reviews and confirms the extracted metadata.
    This endpoint normalizes the data, upserts the article (with deduplication),
    moves the PDF to permanent storage, and creates the article_files record.
    """
    trace_id = str(uuid.uuid4())

    logger.info(
        "pdf_create_article_request",
        trace_id=trace_id,
        user_id=user.sub,
        project_id=str(body.project_id),
        storage_key=body.storage_key,
    )

    await ensure_project_member(db, body.project_id, user.sub)
    _ensure_user_temp_storage_key(body.storage_key, user.sub)

    try:
        storage = create_storage_adapter(supabase)
        service = ArticleImportService(db=db, storage=storage)

        metadata = body.model_dump(
            exclude={"project_id", "storage_key", "original_filename", "file_bytes"},
            by_alias=False,
        )

        article = await service.create_from_pdf_metadata(
            project_id=body.project_id,
            metadata=metadata,
            storage_key=body.storage_key,
            original_filename=body.original_filename,
            file_bytes=body.file_bytes,
        )

        await db.commit()

        logger.info(
            "pdf_create_article_success",
            trace_id=trace_id,
            article_id=str(article.id),
            title=article.title[:80] if article.title else None,
        )

        return ApiResponse.success(
            data={"id": str(article.id), "title": article.title},
            trace_id=trace_id,
        )

    except Exception as e:
        await db.rollback()
        logger.error(
            "pdf_create_article_error",
            trace_id=trace_id,
            error=str(e),
        )
        return ApiResponse.failure(
            code="PDF_CREATE_ARTICLE_ERROR",
            message=str(e),
            trace_id=trace_id,
        )


@router.post(
    "/csv-import",
    response_model=ApiResponse,
    summary="Import articles from Scopus CSV file",
    description="Parses a Scopus-format CSV and bulk-inserts articles into the project.",
)
@limiter.limit("10/minute")
async def csv_import(
    request: Request,
    project_id: str = Form(...),
    file: UploadFile = File(...),
    db: DbSession = None,
    user: CurrentUser = None,
    supabase: SupabaseClient = None,
) -> ApiResponse:
    """
    Import articles from a Scopus-format CSV file.

    Parses the CSV, normalizes via CanonicalArticlePayload, and upserts articles
    using ArticleRepository for consistent deduplication.
    """
    trace_id = str(uuid.uuid4())

    logger.info(
        "csv_import_request",
        trace_id=trace_id,
        user_id=user.sub,
        project_id=project_id,
        filename=file.filename,
    )

    await ensure_project_member(db, project_id, user.sub)

    try:
        # Read and decode CSV
        content = await file.read()

        # Try UTF-8 first, fallback to latin-1
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = content.decode("latin-1")

        reader = csv.DictReader(io.StringIO(text))

        # Validate that it looks like a Scopus CSV
        fieldnames = reader.fieldnames or []
        if "Title" not in fieldnames:
            return ApiResponse.failure(
                code="INVALID_CSV_FORMAT",
                message="CSV must have a 'Title' column. Expected Scopus export format.",
                trace_id=trace_id,
            )

        rows = list(reader)

        logger.info(
            "csv_import_parsing",
            trace_id=trace_id,
            total_rows=len(rows),
            columns=fieldnames[:10],
        )

        service = ArticleImportService(db=db)
        import_result = await service.import_csv_scopus(
            project_id=uuid.UUID(project_id),
            rows=rows,
        )

        await db.commit()

        logger.info(
            "csv_import_complete",
            trace_id=trace_id,
            success=import_result.success_count,
            failed=import_result.fail_count,
            duplicates=import_result.duplicate_count,
        )

        return ApiResponse.success(
            data=import_result.model_dump(by_alias=True),
            trace_id=trace_id,
        )

    except Exception as e:
        await db.rollback()
        logger.error(
            "csv_import_error",
            trace_id=trace_id,
            error=str(e),
        )
        return ApiResponse.failure(
            code="CSV_IMPORT_ERROR",
            message=str(e),
            trace_id=trace_id,
        )
