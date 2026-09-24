"""
Event Handlers.
Handlers to process domain events.
"""

import structlog

from app.domain.events.assessment_events import (
    ArticleAssessed,
    AssessmentApproved,
    AssessmentRejected,
)
from app.domain.events.base import event_bus
from app.domain.events.extraction_events import (
    ExtractionCompleted,
    ModelsExtracted,
    SuggestionAccepted,
)

logger = structlog.get_logger()


# =================== ASSESSMENT HANDLERS ===================


@event_bus.subscribe(ArticleAssessed)
async def on_article_assessed(event: ArticleAssessed) -> None:
    """
    Handler when an article is assessed.
    Actions:
    - Structured log
    - Update metrics (future)
    - Notify user (future)
    """
    logger.info(
        "handler_article_assessed",
        article_id=str(event.article_id),
        assessment_id=str(event.assessment_id),
        selected_level=event.selected_level,
        confidence=event.confidence_score,
    )

    # TODO: Update AI usage metrics
    # TODO: Send notification if confidence < threshold


@event_bus.subscribe(AssessmentApproved)
async def on_assessment_approved(event: AssessmentApproved) -> None:
    """
    Handler when an assessment is approved.
    Actions:
    - Update article status
    - Update project progress
    - Audit log
    """
    logger.info(
        "handler_assessment_approved",
        assessment_id=str(event.assessment_id),
        article_id=str(event.article_id),
        reviewer_id=str(event.reviewer_id),
        modifications_made=event.modifications_made,
    )

    # TODO: Update assessed article counters
    # TODO: Check if project is complete


@event_bus.subscribe(AssessmentRejected)
async def on_assessment_rejected(event: AssessmentRejected) -> None:
    """
    Handler when an assessment is rejected.
    Actions:
    - Log for AI quality analysis
    - Collect feedback
    - Re-schedule manual assessment
    """
    logger.warning(
        "handler_assessment_rejected",
        assessment_id=str(event.assessment_id),
        article_id=str(event.article_id),
        reason=event.rejection_reason,
    )

    # TODO: Collect rejections for quality analysis
    # TODO: Trigger re-assessment if needed


# =================== EXTRACTION HANDLERS ===================


@event_bus.subscribe(ExtractionCompleted)
async def on_extraction_completed(event: ExtractionCompleted) -> None:
    """
    Handler when an extraction is completed.
    Actions:
    - Update progress
    - Trigger next extractions
    - Performance log
    """
    logger.info(
        "handler_extraction_completed",
        article_id=str(event.article_id),
        run_id=event.run_id,
        suggestions_created=event.suggestions_created,
        duration_ms=event.duration_ms,
    )

    # TODO: Check if there are more sections to extract
    # TODO: Atualizar progresso do artigo


@event_bus.subscribe(ModelsExtracted)
async def on_models_extracted(event: ModelsExtracted) -> None:
    """
    Handler when models are extracted.
    Actions:
    - Trigger extraction of child sections
    - Update count
    - Notify user
    """
    logger.info(
        "handler_models_extracted",
        article_id=str(event.article_id),
        models_count=event.models_count,
        child_instances=event.child_instances_count,
        model_names=event.model_names,
    )

    # TODO: Trigger automatic extraction of child sections
    # TODO: Send notification of models found


@event_bus.subscribe(SuggestionAccepted)
async def on_suggestion_accepted(event: SuggestionAccepted) -> None:
    """
    Handler when a suggestion is accepted.
    Actions:
    - Collect feedback for training
    - Update accuracy metrics
    - Audit log
    """
    logger.info(
        "handler_suggestion_accepted",
        suggestion_id=str(event.suggestion_id),
        field_name=event.field_name,
        was_modified=event.was_modified,
    )

    # TODO: Coletar para dataset de fine-tuning
    # TODO: Calculate modification rate per field


def register_handlers() -> None:
    """
    Register all handlers.
    Call at application startup to ensure handlers
    are registered before any event is published.
    """
    # Decorators already register automatically, but this function
    # ensures the module was imported
    logger.info("event_handlers_registered", handler_count=6)
