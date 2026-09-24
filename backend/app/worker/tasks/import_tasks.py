"""
Import Tasks.

Tasks Celery para importação de dados externos.
"""

import asyncio
from typing import Any
from uuid import UUID

from app.worker.celery_app import celery_app

_WORKER_LOOP: asyncio.AbstractEventLoop | None = None


def _run_in_worker_loop(coro):
    global _WORKER_LOOP
    if _WORKER_LOOP is None or _WORKER_LOOP.is_closed():
        _WORKER_LOOP = asyncio.new_event_loop()
        asyncio.set_event_loop(_WORKER_LOOP)
    return _WORKER_LOOP.run_until_complete(coro)


@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=120,
    rate_limit="2/m",
)
def import_zotero_collection_task(
    self,
    project_id: str,
    collection_key: str,
    user_id: str,
    import_pdfs: bool = True,
    max_items: int = 100,
    update_existing: bool = True,
    sync_run_id: str | None = None,
) -> dict[str, Any]:
    """
    Task para importação de collection do Zotero.

    Args:
        project_id: ID do projeto.
        collection_key: Key da collection no Zotero.
        user_id: ID do usuário.
        import_pdfs: Se deve importar PDFs.
        max_items: Máximo de items a importar.

    Returns:
        Dict com resultado da importação.
    """
    from app.core.deps import AsyncSessionLocal, get_supabase_client
    from app.core.factories import create_storage_adapter
    from app.services.zotero_import_service import ZoteroImportService

    async def run():
        async with AsyncSessionLocal() as session:
            try:
                supabase = get_supabase_client()
                storage = create_storage_adapter(supabase)
                service = ZoteroImportService(
                    db=session,
                    user_id=user_id,
                    storage=storage,
                    trace_id=self.request.id,
                )

                result = await service.import_collection(
                    project_id=UUID(project_id),
                    collection_key=collection_key,
                    max_items=max_items,
                    import_pdfs=import_pdfs,
                    update_existing=update_existing,
                    sync_run_id=UUID(sync_run_id) if sync_run_id else None,
                )

                await session.commit()

                result_payload = {
                    "sync_run_id": result.sync_run_id,
                    "total_items": result.total_items,
                    "imported": result.imported,
                    "updated": result.updated,
                    "failed": result.failed,
                    "skipped": result.skipped,
                    "removed_at_source": result.removed_at_source,
                    "reactivated": result.reactivated,
                    "results": [
                        {
                            "zotero_key": r.zotero_key,
                            "title": r.title,
                            "success": r.success,
                            "article_id": r.article_id,
                            "has_pdf": r.pdf_imported,
                            "error": r.error,
                        }
                        for r in result.results
                    ],
                }
                return result_payload
            except Exception:
                await session.rollback()
                raise

    try:
        return _run_in_worker_loop(run())
    except Exception as exc:
        self.retry(exc=exc)


@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=120,
    rate_limit="2/m",
)
def retry_failed_zotero_sync_task(
    self,
    project_id: str,
    source_sync_run_id: str,
    user_id: str,
    sync_run_id: str,
    limit: int = 100,
) -> dict[str, Any]:
    from app.core.deps import AsyncSessionLocal, get_supabase_client
    from app.core.factories import create_storage_adapter
    from app.services.zotero_import_service import ZoteroImportService

    async def run():
        async with AsyncSessionLocal() as session:
            try:
                supabase = get_supabase_client()
                storage = create_storage_adapter(supabase)
                service = ZoteroImportService(
                    db=session,
                    user_id=user_id,
                    storage=storage,
                    trace_id=self.request.id,
                )
                _, result = await service.retry_failed_items(
                    project_id=UUID(project_id),
                    source_run_id=UUID(source_sync_run_id),
                    target_run_id=UUID(sync_run_id),
                    limit=limit,
                )
                await session.commit()
                return {
                    "sync_run_id": sync_run_id,
                    "retry_of_sync_run_id": source_sync_run_id,
                    "queued_items": limit,
                    "imported": result.imported,
                    "updated": result.updated,
                    "failed": result.failed,
                    "skipped": result.skipped,
                }
            except Exception:
                await session.rollback()
                raise

    try:
        return _run_in_worker_loop(run())
    except Exception as exc:
        self.retry(exc=exc)


@celery_app.task(
    bind=True,
    max_retries=1,
    rate_limit="1/m",
)
def sync_zotero_library_task(
    self,
    user_id: str,
) -> dict[str, Any]:
    """
    Task para sincronização completa da biblioteca Zotero.

    Args:
        user_id: ID do usuário.

    Returns:
        Dict com resultado da sincronização.
    """
    from app.core.deps import AsyncSessionLocal
    from app.services.zotero_service import ZoteroService

    async def run():
        async with AsyncSessionLocal() as session:
            try:
                zotero = ZoteroService(
                    db=session,
                    user_id=user_id,
                )

                # Testar conexão
                connection_result = await zotero.test_connection()

                if not connection_result.get("success"):
                    return {
                        "success": False,
                        "error": connection_result.get("error"),
                    }

                # Listar collections
                collections_result = await zotero.list_collections()

                return {
                    "success": True,
                    "user_name": connection_result.get("user_name"),
                    "collections_count": len(collections_result.get("collections", [])),
                    "collections": [
                        {
                            "key": c.get("key"),
                            "name": c.get("data", {}).get("name"),
                        }
                        for c in collections_result.get("collections", [])[:20]  # Limitar
                    ],
                }
            except Exception:
                await session.rollback()
                raise

    try:
        return _run_in_worker_loop(run())
    except Exception as exc:
        self.retry(exc=exc)
