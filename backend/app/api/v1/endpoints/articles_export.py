"""
Articles Export Endpoint.

Endpoints para exportação de artigos (CSV, RIS, RDF) com opção de incluir arquivos.
"""

import uuid
from uuid import UUID

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse
from redis import Redis

from app.core.deps import CurrentUser, DbSession, SupabaseClient
from app.core.factories import create_storage_adapter
from app.core.logging import get_logger
from app.repositories.unit_of_work import UnitOfWork
from app.schemas.articles_export import (
    ExportCancelResponse,
    ExportRequest,
    ExportStartedResponse,
    ExportStatusResponse,
    SkippedFileEntry,
)
from app.schemas.common import ApiResponse
from app.services.articles_export_service import ArticlesExportService
from app.utils.rate_limiter import limiter
from app.worker.celery_app import REDIS_URL
from app.worker.tasks.export_tasks import export_articles_task

router = APIRouter()
logger = get_logger(__name__)

# Limite para executar export de metadados de forma síncrona (sem Celery)
SYNC_METADATA_ONLY_MAX_ARTICLES = 50


def _is_queue_available() -> bool:
    try:
        Redis.from_url(
            REDIS_URL,
            socket_connect_timeout=0.25,
            socket_timeout=0.25,
        ).ping()
        return True
    except Exception:
        return False


@router.post(
    "",
    response_model=None,
    summary="Iniciar exportação de artigos",
    description="Exporta artigos em CSV, RIS e/ou RDF; opcionalmente inclui arquivos. Retorna 200 com arquivo (sync) ou 202 com jobId (async).",
)
@limiter.limit("10/minute")
async def start_export(
    request: Request,
    payload: ExportRequest,
    db: DbSession,
    user: CurrentUser,
    supabase: SupabaseClient,
) -> Response | ApiResponse[ExportStartedResponse] | ApiResponse[None]:
    """Inicia exportação. Metadados-only e poucos artigos → 200 com arquivo; caso contrário → 202 com job_id."""
    trace_id = str(uuid.uuid4())
    project_id = payload.project_id
    article_ids = payload.article_ids
    formats = [f.lower() for f in payload.formats if (f or "").strip()]
    file_scope = (payload.file_scope or "none").strip().lower()

    if not formats:
        return ApiResponse.failure(
            code="VALIDATION_ERROR",
            message="At least one format is required (csv, ris, rdf).",
            trace_id=trace_id,
        )
    if not article_ids:
        return ApiResponse.failure(
            code="VALIDATION_ERROR",
            message="articleIds cannot be empty.",
            trace_id=trace_id,
        )
    valid_formats = {"csv", "ris", "rdf"}
    if not all(f in valid_formats for f in formats):
        return ApiResponse.failure(
            code="VALIDATION_ERROR",
            message="formats must be one or more of: csv, ris, rdf.",
            trace_id=trace_id,
        )
    if file_scope not in ("none", "main_only", "all"):
        return ApiResponse.failure(
            code="VALIDATION_ERROR",
            message="fileScope must be one of: none, main_only, all.",
            trace_id=trace_id,
        )

    async with UnitOfWork(db) as uow:
        is_member = await uow.project_members.is_member(project_id, user.sub)
        if not is_member:
            return ApiResponse.failure(
                code="FORBIDDEN",
                message="User is not a member of this project.",
                trace_id=trace_id,
            )

    storage = create_storage_adapter(supabase)
    service = ArticlesExportService(
        db=db,
        user_id=user.sub,
        storage=storage,
        trace_id=trace_id,
    )
    articles = await service.get_articles_for_export(
        project_id,
        article_ids,
        include_files=(file_scope != "none"),
    )
    if len(articles) != len(article_ids):
        return ApiResponse.failure(
            code="NOT_FOUND",
            message="One or more articles not found or do not belong to this project.",
            trace_id=trace_id,
        )

    # Sync: metadados-only e até SYNC_METADATA_ONLY_MAX_ARTICLES artigos
    if file_scope == "none" and len(article_ids) <= SYNC_METADATA_ONLY_MAX_ARTICLES:
        content, media_type, filename, skipped = await service.run_export(
            project_id, article_ids, formats, file_scope, job_id=None
        )
        return Response(
            content=content,
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )

    # Async: enfileirar task
    if not _is_queue_available():
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=ApiResponse.failure(
                code="SERVICE_UNAVAILABLE",
                message="Background export queue is unavailable. Please start Redis/Celery and try again.",
                trace_id=trace_id,
            ).model_dump(),
        )
    try:
        task = export_articles_task.delay(
            project_id=str(project_id),
            article_ids=[str(aid) for aid in article_ids],
            formats=formats,
            file_scope=file_scope,
            user_id=user.sub,
        )
    except Exception:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=ApiResponse.failure(
                code="SERVICE_UNAVAILABLE",
                message="Background export queue is unavailable. Please start Redis/Celery and try again.",
                trace_id=trace_id,
            ).model_dump(),
        )
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=ApiResponse.success(
            data=ExportStartedResponse(job_id=task.id),
            trace_id=trace_id,
        ).model_dump(),
    )


@router.get(
    "/status/{job_id}",
    response_model=ApiResponse[ExportStatusResponse],
    summary="Status do job de exportação",
)
@limiter.limit("30/minute")
async def get_export_status(
    request: Request,
    job_id: str,
    user: CurrentUser,
) -> ApiResponse[ExportStatusResponse] | ApiResponse[None]:
    """Retorna status do job; quando completed, inclui downloadUrl e expiresAt."""
    from celery.result import AsyncResult

    from app.worker.celery_app import celery_app

    result = AsyncResult(job_id, app=celery_app)
    if not result.backend:
        return ApiResponse.failure(
            code="NOT_FOUND",
            message="Job not found or expired.",
        )
    state = result.state
    if state == "PENDING":
        return ApiResponse.success(
            data=ExportStatusResponse(
                job_id=job_id,
                status="pending",
            ),
        )
    if state == "STARTED" or state == "RETRY":
        return ApiResponse.success(
            data=ExportStatusResponse(
                job_id=job_id,
                status="running",
            ),
        )
    if state == "FAILURE":
        return ApiResponse.success(
            data=ExportStatusResponse(
                job_id=job_id,
                status="failed",
                error=str(result.result) if result.result else "Task failed.",
            ),
        )
    if state == "SUCCESS" and result.result:
        data = result.result
        if isinstance(data, dict) and data.get("user_id") != user.sub:
            return ApiResponse.failure(
                code="FORBIDDEN",
                message="Job does not belong to current user.",
            )
        skipped = data.get("skipped_files") or []
        skipped_entries = None
        if skipped:
            skipped_entries = [
                SkippedFileEntry(
                    article_id=UUID(s["articleId"])
                    if isinstance(s.get("articleId"), str)
                    else s["articleId"],
                    storage_key=s["storageKey"],
                    reason=s["reason"],
                )
                for s in skipped
            ]
        return ApiResponse.success(
            data=ExportStatusResponse(
                job_id=job_id,
                status="completed",
                download_url=data.get("download_url"),
                expires_at=data.get("expires_at"),
                skipped_files=skipped_entries,
            ),
        )
    if state == "REVOKED":
        return ApiResponse.success(
            data=ExportStatusResponse(
                job_id=job_id,
                status="cancelled",
            ),
        )
    return ApiResponse.success(
        data=ExportStatusResponse(
            job_id=job_id,
            status=state.lower() if state else "pending",
        ),
    )


@router.post(
    "/status/{job_id}/cancel",
    response_model=ApiResponse[ExportCancelResponse],
    summary="Cancelar exportação (POST)",
)
@router.delete(
    "/status/{job_id}",
    response_model=ApiResponse[ExportCancelResponse],
    summary="Cancelar exportação (DELETE)",
)
@limiter.limit("20/minute")
async def cancel_export(
    request: Request,
    job_id: str,
    user: CurrentUser,
) -> ApiResponse[ExportCancelResponse]:
    """Revoga o job de exportação. Se já concluído, no-op."""
    from celery.result import AsyncResult

    from app.worker.celery_app import celery_app

    result = AsyncResult(job_id, app=celery_app)
    if result.state in ("SUCCESS", "FAILURE", "REVOKED"):
        return ApiResponse.success(
            data=ExportCancelResponse(cancelled=False),
        )
    celery_app.control.revoke(job_id, terminate=True)
    return ApiResponse.success(
        data=ExportCancelResponse(cancelled=True),
    )
