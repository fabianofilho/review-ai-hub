"""
Extraction Tasks.

Tasks Celery para processamento de extrações.
"""

import asyncio
from typing import Any
from uuid import UUID

from app.worker.celery_app import LoggedTask, bound_task


@bound_task(
    max_retries=3,
    default_retry_delay=60,
    rate_limit="5/m",
)
def extract_section_task(
    self: LoggedTask,
    project_id: str,
    article_id: str,
    template_id: str,
    entity_type_id: str,
    user_id: str,
    parent_instance_id: str | None = None,
    openai_api_key: str | None = None,
) -> dict[str, Any]:
    """
    Task para extração de uma seção.

    Args:
        project_id: ID do projeto.
        article_id: ID do artigo.
        template_id: ID do template.
        entity_type_id: ID do entity type.
        user_id: ID do usuário.
        parent_instance_id: ID da instância pai (opcional).
        openai_api_key: API key customizada (BYOK). Se None, busca do usuário ou usa global.

    Returns:
        Dict com resultado da extração.
    """
    from app.core.deps import AsyncSessionLocal, get_supabase_client
    from app.core.factories import create_storage_adapter
    from app.services.api_key_service import APIKeyService
    from app.services.section_extraction_service import SectionExtractionService

    async def run() -> dict[str, Any]:
        async with AsyncSessionLocal() as session:
            try:
                supabase = get_supabase_client()
                storage = create_storage_adapter(supabase)

                # Buscar API key do usuário se não foi passada
                api_key = openai_api_key
                if not api_key:
                    api_key_service = APIKeyService(db=session, user_id=user_id)
                    api_key = await api_key_service.get_key_for_provider("openai")

                service = SectionExtractionService(
                    db=session,
                    user_id=user_id,
                    storage=storage,
                    trace_id=self.request.id,
                    openai_api_key=api_key,
                )

                result = await service.extract_section(
                    project_id=UUID(project_id),
                    article_id=UUID(article_id),
                    template_id=UUID(template_id),
                    entity_type_id=UUID(entity_type_id),
                    parent_instance_id=UUID(parent_instance_id) if parent_instance_id else None,
                )

                await session.commit()

                return {
                    "extraction_run_id": result.extraction_run_id,
                    "suggestions_created": result.suggestions_created,
                    "entity_type_id": result.entity_type_id,
                    "duration_ms": int(result.duration_ms),
                }
            except Exception:
                await session.rollback()
                raise

    try:
        return asyncio.run(run())
    except Exception as exc:
        raise self.retry(exc=exc)


@bound_task(
    max_retries=3,
    default_retry_delay=60,
    rate_limit="5/m",
)
def extract_models_task(
    self: LoggedTask,
    project_id: str,
    article_id: str,
    template_id: str,
    user_id: str,
    openai_api_key: str | None = None,
) -> dict[str, Any]:
    """
    Task para extração de modelos de predição.

    Args:
        project_id: ID do projeto.
        article_id: ID do artigo.
        template_id: ID do template.
        user_id: ID do usuário.
        openai_api_key: API key customizada (BYOK). Se None, busca do usuário ou usa global.

    Returns:
        Dict com modelos extraídos.
    """
    from app.core.deps import AsyncSessionLocal, get_supabase_client
    from app.core.factories import create_storage_adapter
    from app.services.api_key_service import APIKeyService
    from app.services.model_extraction_service import ModelExtractionService

    async def run() -> dict[str, Any]:
        async with AsyncSessionLocal() as session:
            try:
                supabase = get_supabase_client()
                storage = create_storage_adapter(supabase)

                # Buscar API key do usuário se não foi passada
                api_key = openai_api_key
                if not api_key:
                    api_key_service = APIKeyService(db=session, user_id=user_id)
                    api_key = await api_key_service.get_key_for_provider("openai")

                service = ModelExtractionService(
                    db=session,
                    user_id=user_id,
                    storage=storage,
                    trace_id=self.request.id,
                    openai_api_key=api_key,
                )

                result = await service.extract(
                    project_id=UUID(project_id),
                    article_id=UUID(article_id),
                    template_id=UUID(template_id),
                )

                await session.commit()

                return {
                    "extraction_run_id": result.extraction_run_id,
                    "total_models": result.total_models,
                    "child_instances_created": result.child_instances_created,
                    "duration_ms": int(result.duration_ms),
                    "models": [
                        {
                            "instance_id": m.get("instanceId") or m.get("instance_id"),
                            "model_name": m.get("modelName") or m.get("model_name"),
                            "model_type": (
                                m.get("modellingMethod")
                                or m.get("modelType")
                                or m.get("model_type")
                            ),
                        }
                        for m in result.models_created
                    ],
                }
            except Exception:
                await session.rollback()
                raise

    try:
        return asyncio.run(run())
    except Exception as exc:
        raise self.retry(exc=exc)


@bound_task(
    max_retries=2,
    default_retry_delay=120,
    rate_limit="1/m",
)
def batch_extract_task(
    self: LoggedTask,
    project_id: str,
    article_ids: list[str],
    template_id: str,
    user_id: str,
) -> dict[str, Any]:
    """
    Task para extração em batch de múltiplos artigos.

    Args:
        project_id: ID do projeto.
        article_ids: Lista de IDs de artigos.
        template_id: ID do template.
        user_id: ID do usuário.

    Returns:
        Dict com estatísticas do batch.
    """
    results: dict[str, Any] = {
        "total": len(article_ids),
        "queued": 0,
        "results": [],
    }

    for article_id in article_ids:
        try:
            task = extract_models_task.delay(
                project_id=project_id,
                article_id=article_id,
                template_id=template_id,
                user_id=user_id,
            )

            results["results"].append(
                {
                    "article_id": article_id,
                    "task_id": task.id,
                    "status": "queued",
                }
            )
            results["queued"] += 1

        except Exception as e:
            results["results"].append(
                {
                    "article_id": article_id,
                    "status": "failed",
                    "error": str(e),
                }
            )

    return results
