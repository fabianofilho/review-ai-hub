"""
Zotero Import Endpoint.

Migrado de: supabase/functions/zotero-import/index.ts

Endpoints para integração com Zotero:
- Salvar credenciais
- Testar conexão
- Listar collections
- Buscar items
- Download de attachments
"""

from enum import StrEnum
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.core.deps import CurrentUser, DbSession, SupabaseClient
from app.core.error_handler import AppError, AuthorizationError, NotFoundError
from app.core.factories import create_storage_adapter
from app.core.logging import get_logger
from app.repositories.unit_of_work import UnitOfWork
from app.schemas.common import ApiResponse
from app.schemas.zotero import (
    DownloadAttachmentRequest,
    FetchAttachmentsRequest,
    FetchItemsRequest,
    SaveCredentialsRequest,
    SyncCollectionRequest,
    SyncCollectionResponse,
    SyncCountsResponse,
    SyncItemResultEntry,
    SyncItemResultRequest,
    SyncItemResultsResponse,
    SyncRetryFailedRequest,
    SyncRetryFailedResponse,
    SyncStatusRequest,
    SyncStatusResponse,
)
from app.services.zotero_import_service import ZoteroImportService
from app.services.zotero_service import ZoteroService
from app.utils.rate_limiter import limiter
from app.worker.tasks.import_tasks import (
    import_zotero_collection_task,
    retry_failed_zotero_sync_task,
)

router = APIRouter()
logger = get_logger(__name__)


class ZoteroAction(StrEnum):
    """Ações disponíveis para Zotero."""

    SAVE_CREDENTIALS = "save-credentials"
    TEST_CONNECTION = "test-connection"
    LIST_COLLECTIONS = "list-collections"
    FETCH_ITEMS = "fetch-items"
    FETCH_ATTACHMENTS = "fetch-attachments"
    DOWNLOAD_ATTACHMENT = "download-attachment"
    SYNC_COLLECTION = "sync-collection"
    SYNC_STATUS = "sync-status"
    SYNC_RETRY_FAILED = "sync-retry-failed"
    SYNC_ITEM_RESULT = "sync-item-result"


@router.post(
    "/{action}",
    response_model=ApiResponse,
    summary="Executar ação Zotero",
    description="Endpoint unificado para todas as ações de integração com Zotero.",
)
@limiter.limit("120/minute")
async def zotero_action(
    request: Request,
    action: ZoteroAction,
    db: DbSession,
    user: CurrentUser,
    supabase: SupabaseClient,
    body: dict[str, Any] | None = None,
) -> ApiResponse:
    """
    Executa uma ação de integração com Zotero.

    Args:
        action: Tipo de ação a executar.
        body: Dados específicos da ação.

    Returns:
        ApiResponse com resultado da ação.
    """
    trace_id = getattr(request.state, "trace_id", None)
    service = ZoteroService(db=db, user_id=user.sub)
    body = body or {}

    logger.info(
        "zotero_action_request",
        action=action.value,
        user_id=user.sub,
    )

    try:
        match action:
            case ZoteroAction.SAVE_CREDENTIALS:
                request = SaveCredentialsRequest(**body)
                result = await service.save_credentials(
                    zotero_user_id=request.zotero_user_id,
                    api_key=request.api_key,
                    library_type=request.library_type,
                )
                # Commit explícito para persistir credenciais
                await db.commit()

            case ZoteroAction.TEST_CONNECTION:
                result = await service.test_connection()

            case ZoteroAction.LIST_COLLECTIONS:
                result = await service.list_collections()

            case ZoteroAction.FETCH_ITEMS:
                request = FetchItemsRequest(**body)
                result = await service.fetch_items(
                    collection_key=request.collection_key,
                    limit=request.limit,
                    start=request.start,
                )

            case ZoteroAction.FETCH_ATTACHMENTS:
                request = FetchAttachmentsRequest(**body)
                result = await service.fetch_attachments(item_key=request.item_key)

            case ZoteroAction.DOWNLOAD_ATTACHMENT:
                request = DownloadAttachmentRequest(**body)
                result = await service.download_attachment(
                    attachment_key=request.attachment_key,
                )

            case ZoteroAction.SYNC_COLLECTION:
                payload = SyncCollectionRequest(**body)
                project_id = UUID(payload.project_id)
                async with UnitOfWork(db) as uow:
                    is_member = await uow.project_members.is_member(project_id, user.sub)
                    if not is_member:
                        raise AuthorizationError("User is not authorized for this project")
                import_service = ZoteroImportService(
                    db=db,
                    user_id=user.sub,
                    storage=create_storage_adapter(supabase),
                    trace_id=trace_id or "unknown-trace",
                )
                sync_run = await import_service.create_sync_run(
                    project_id=project_id,
                    collection_key=payload.collection_key,
                )
                await db.commit()
                task = import_zotero_collection_task.delay(
                    project_id=str(project_id),
                    collection_key=payload.collection_key,
                    user_id=user.sub,
                    import_pdfs=payload.include_attachments,
                    max_items=payload.max_items,
                    update_existing=payload.update_existing,
                    sync_run_id=str(sync_run.id),
                )
                response = ApiResponse.success(
                    SyncCollectionResponse(
                        syncRunId=str(sync_run.id),
                        status="pending",
                        message="Sync started",
                    ),
                    trace_id=trace_id,
                )
                return JSONResponse(
                    status_code=status.HTTP_202_ACCEPTED,
                    content=response.model_dump(by_alias=True),
                )

            case ZoteroAction.SYNC_STATUS:
                payload = SyncStatusRequest(**body)
                import_service = ZoteroImportService(
                    db=db,
                    user_id=user.sub,
                    storage=create_storage_adapter(supabase),
                    trace_id=trace_id or "unknown-trace",
                )
                run = await import_service.get_sync_status(UUID(payload.sync_run_id))
                if not run:
                    raise NotFoundError(resource="sync_run", resource_id=payload.sync_run_id)
                result = SyncStatusResponse(
                    syncRunId=str(run.id),
                    status=run.status,
                    counts=SyncCountsResponse(
                        totalReceived=run.total_received,
                        persisted=run.persisted,
                        updated=run.updated,
                        skipped=run.skipped,
                        failed=run.failed,
                        removedAtSource=run.removed_at_source,
                        reactivated=run.reactivated,
                    ),
                    startedAt=run.started_at,
                    completedAt=run.completed_at,
                    traceId=trace_id or "",
                )

            case ZoteroAction.SYNC_RETRY_FAILED:
                payload = SyncRetryFailedRequest(**body)
                import_service = ZoteroImportService(
                    db=db,
                    user_id=user.sub,
                    storage=create_storage_adapter(supabase),
                    trace_id=trace_id or "unknown-trace",
                )
                run = await import_service.get_sync_status(UUID(payload.sync_run_id))
                if not run:
                    raise NotFoundError(resource="sync_run", resource_id=payload.sync_run_id)
                retry_run = await import_service.create_sync_run(
                    project_id=run.project_id,
                    collection_key=run.source_collection_key,
                )
                await db.commit()
                retry_failed_zotero_sync_task.delay(
                    project_id=str(run.project_id),
                    source_sync_run_id=str(run.id),
                    user_id=user.sub,
                    sync_run_id=str(retry_run.id),
                    limit=payload.limit,
                )
                response = ApiResponse.success(
                    SyncRetryFailedResponse(
                        syncRunId=str(retry_run.id),
                        retryOfSyncRunId=str(run.id),
                        queuedItems=payload.limit,
                    ),
                    trace_id=trace_id,
                )
                return JSONResponse(
                    status_code=status.HTTP_202_ACCEPTED,
                    content=response.model_dump(by_alias=True),
                )

            case ZoteroAction.SYNC_ITEM_RESULT:
                payload = SyncItemResultRequest(**body)
                import_service = ZoteroImportService(
                    db=db,
                    user_id=user.sub,
                    storage=create_storage_adapter(supabase),
                    trace_id=trace_id or "unknown-trace",
                )
                run = await import_service.get_sync_status(UUID(payload.sync_run_id))
                if not run:
                    raise NotFoundError(resource="sync_run", resource_id=payload.sync_run_id)
                events, total = await import_service.get_sync_item_results(
                    sync_run_id=UUID(payload.sync_run_id),
                    status_filter=payload.status_filter,
                    offset=payload.offset,
                    limit=payload.limit,
                )
                result = SyncItemResultsResponse(
                    items=[
                        SyncItemResultEntry(
                            zoteroItemKey=event.zotero_item_key,
                            articleId=str(event.article_id) if event.article_id else None,
                            status=event.status,
                            errorCode=event.error_code,
                            errorMessage=event.error_message,
                            authorityRuleApplied=event.authority_rule_applied,
                            processedAt=event.processed_at,
                        )
                        for event in events
                    ],
                    total=total,
                    offset=payload.offset,
                    limit=payload.limit,
                )

            case _:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unknown action: {action}",
                )

        logger.info(
            "zotero_action_success",
            action=action.value,
            user_id=user.sub,
        )

        return ApiResponse.success(result, trace_id=trace_id)

    except AppError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    except ValueError as e:
        logger.warning(
            "zotero_action_validation_error",
            action=action.value,
            error=str(e),
        )
        if action in {
            ZoteroAction.SYNC_RETRY_FAILED,
            ZoteroAction.SYNC_STATUS,
            ZoteroAction.SYNC_ITEM_RESULT,
        }:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        logger.error(
            "zotero_action_error",
            action=action.value,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Zotero operation failed: {str(e)}",
        ) from e
