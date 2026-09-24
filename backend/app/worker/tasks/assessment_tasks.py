"""
Assessment Tasks.

Tasks Celery para processamento de assessments.
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
def assess_article_task(
    self: LoggedTask,
    project_id: str,
    article_id: str,
    assessment_item_id: str,
    instrument_id: str,
    user_id: str,
) -> dict[str, Any]:
    """
    Task para avaliação AI de um artigo.

    Args:
        project_id: ID do projeto.
        article_id: ID do artigo.
        assessment_item_id: ID do item de assessment.
        instrument_id: ID do instrumento.
        user_id: ID do usuário.

    Returns:
        Dict com resultado do assessment.
    """
    from app.core.deps import AsyncSessionLocal, get_supabase_client
    from app.core.factories import create_storage_adapter
    from app.services.ai_assessment_service import AIAssessmentService

    async def run() -> dict[str, Any]:
        async with AsyncSessionLocal() as session:
            try:
                supabase = get_supabase_client()
                storage = create_storage_adapter(supabase)

                service = AIAssessmentService(
                    db=session,
                    user_id=user_id,
                    storage=storage,
                    trace_id=self.request.id,
                )

                result = await service.assess(
                    project_id=UUID(project_id),
                    article_id=UUID(article_id),
                    assessment_item_id=UUID(assessment_item_id),
                    instrument_id=UUID(instrument_id),
                )

                await session.commit()

                return {
                    "assessment_id": result.assessment_id,
                    "selected_level": result.selected_level,
                    "confidence_score": result.confidence_score,
                    "status": "pending_review",
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
    rate_limit="2/m",
)
def batch_assess_task(
    self: LoggedTask,
    project_id: str,
    article_ids: list[str],
    instrument_id: str,
    user_id: str,
) -> dict[str, Any]:
    """
    Task para avaliação em batch de múltiplos artigos.

    Args:
        project_id: ID do projeto.
        article_ids: Lista de IDs de artigos.
        instrument_id: ID do instrumento.
        user_id: ID do usuário.

    Returns:
        Dict com estatísticas do batch.
    """
    results: dict[str, Any] = {
        "total": len(article_ids),
        "completed": 0,
        "failed": 0,
        "results": [],
    }

    for article_id in article_ids:
        try:
            # Disparar subtask para cada artigo
            task = assess_article_task.delay(
                project_id=project_id,
                article_id=article_id,
                assessment_item_id="",  # Seria obtido do instrumento
                instrument_id=instrument_id,
                user_id=user_id,
            )

            results["results"].append(
                {
                    "article_id": article_id,
                    "task_id": task.id,
                    "status": "queued",
                }
            )
            results["completed"] += 1

        except Exception as e:
            results["failed"] += 1
            results["results"].append(
                {
                    "article_id": article_id,
                    "status": "failed",
                    "error": str(e),
                }
            )

    return results
