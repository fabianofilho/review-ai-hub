"""
Screening Endpoints.

API endpoints for the article screening workflow.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request

from app.core.deps import (
    CurrentUser,
    DbSession,
    SupabaseClient,
    ensure_project_member,
    require_project_member,
)
from app.core.factories import create_storage_adapter
from app.core.logging import get_logger
from app.repositories.screening_repository import ScreeningConflictRepository
from app.schemas.common import ApiResponse
from app.schemas.screening import (
    AdvanceToFullTextRequest,
    AIScreeningRequest,
    BatchAIScreeningRequest,
    BulkDecideRequest,
    ResolveConflictRequest,
    ScreeningConfigCreate,
    ScreeningConfigResponse,
    ScreeningConflictResponse,
    ScreeningDashboardData,
    ScreeningDecisionCreate,
    ScreeningDecisionResponse,
)
from app.services.ai_screening_service import AIScreeningService
from app.services.api_key_service import APIKeyService
from app.services.screening_service import ScreeningService
from app.utils.rate_limiter import limiter

router = APIRouter()
logger = get_logger(__name__)


# =================== CONFIG ===================


@router.post(
    "/config",
    response_model=ApiResponse,
    summary="Create or update screening config",
)
@limiter.limit("10/minute")
async def upsert_config(
    request: Request,
    payload: ScreeningConfigCreate,
    db: DbSession,
    user: CurrentUser,
) -> ApiResponse[Any]:
    """Create or update screening configuration for a project/phase."""
    trace_id = str(uuid.uuid4())
    await ensure_project_member(db, payload.project_id, user.sub)
    try:
        service = ScreeningService(db=db, user_id=user.sub)
        config = await service.upsert_config(
            project_id=payload.project_id,
            phase=payload.phase,
            require_dual_review=payload.require_dual_review,
            blind_mode=payload.blind_mode,
            criteria=[c.model_dump() for c in payload.criteria],
            ai_model_name=payload.ai_model_name,
            ai_system_instruction=payload.ai_system_instruction,
        )
        await db.commit()

        return ApiResponse.success(
            data=ScreeningConfigResponse.model_validate(config).model_dump(by_alias=True),
            trace_id=trace_id,
        )
    except Exception as e:
        logger.error("screening_config_error", trace_id=trace_id, error=str(e))
        return ApiResponse.failure(code="SCREENING_CONFIG_ERROR", message=str(e), trace_id=trace_id)


@router.get(
    "/config/{project_id}/{phase}",
    response_model=ApiResponse,
    summary="Get screening config",
    dependencies=[Depends(require_project_member)],
)
async def get_config(
    project_id: str,
    phase: str,
    db: DbSession,
    user: CurrentUser,
) -> ApiResponse[Any]:
    """Get screening configuration for a project/phase."""
    from app.repositories.screening_repository import ScreeningConfigRepository

    repo = ScreeningConfigRepository(db)
    config = await repo.get_by_project_and_phase(project_id, phase)
    if not config:
        return ApiResponse.success(data=None)
    return ApiResponse.success(
        data=ScreeningConfigResponse.model_validate(config).model_dump(by_alias=True)
    )


# =================== DECISIONS ===================


@router.post(
    "/decide",
    response_model=ApiResponse,
    summary="Submit screening decision",
)
@limiter.limit("60/minute")
async def submit_decision(
    request: Request,
    payload: ScreeningDecisionCreate,
    db: DbSession,
    user: CurrentUser,
) -> ApiResponse[Any]:
    """Submit a screening decision for an article."""
    trace_id = str(uuid.uuid4())
    await ensure_project_member(db, payload.project_id, user.sub)
    try:
        service = ScreeningService(db=db, user_id=user.sub)
        decision = await service.create_decision(
            project_id=payload.project_id,
            article_id=payload.article_id,
            phase=payload.phase,
            decision=payload.decision,
            reason=payload.reason,
            criteria_responses=payload.criteria_responses,
        )
        await db.commit()

        return ApiResponse.success(
            data=ScreeningDecisionResponse.model_validate(decision).model_dump(by_alias=True),
            trace_id=trace_id,
        )
    except Exception as e:
        logger.error("screening_decision_error", trace_id=trace_id, error=str(e))
        return ApiResponse.failure(
            code="SCREENING_DECISION_ERROR", message=str(e), trace_id=trace_id
        )


@router.get(
    "/decisions/{project_id}/{phase}",
    response_model=ApiResponse,
    summary="List screening decisions",
    dependencies=[Depends(require_project_member)],
)
async def list_decisions(
    project_id: str,
    phase: str,
    db: DbSession,
    user: CurrentUser,
) -> ApiResponse[Any]:
    """List all screening decisions for a project/phase."""
    from sqlalchemy import and_, select

    from app.models.screening import ScreeningDecision

    result = await db.execute(
        select(ScreeningDecision).where(
            and_(
                ScreeningDecision.project_id == project_id,
                ScreeningDecision.phase == phase,
            )
        )
    )
    decisions = result.scalars().all()
    return ApiResponse.success(
        data=[
            ScreeningDecisionResponse.model_validate(d).model_dump(by_alias=True) for d in decisions
        ]
    )


# =================== PROGRESS ===================


@router.get(
    "/progress/{project_id}/{phase}",
    response_model=ApiResponse,
    summary="Get screening progress",
    dependencies=[Depends(require_project_member)],
)
async def get_progress(
    project_id: str,
    phase: str,
    db: DbSession,
    user: CurrentUser,
) -> ApiResponse[Any]:
    """Get screening progress statistics."""
    service = ScreeningService(db=db, user_id=user.sub)
    progress = await service.get_progress(uuid.UUID(project_id), phase)
    return ApiResponse.success(data=progress.model_dump(by_alias=True))


# =================== CONFLICTS ===================


@router.get(
    "/conflicts/{project_id}/{phase}",
    response_model=ApiResponse,
    summary="List screening conflicts",
    dependencies=[Depends(require_project_member)],
)
async def list_conflicts(
    project_id: str,
    phase: str,
    db: DbSession,
    user: CurrentUser,
) -> ApiResponse[Any]:
    """List all unresolved screening conflicts."""
    from app.repositories.screening_repository import ScreeningConflictRepository

    repo = ScreeningConflictRepository(db)
    conflicts = await repo.get_unresolved(project_id, phase)
    return ApiResponse.success(
        data=[
            ScreeningConflictResponse.model_validate(c).model_dump(by_alias=True) for c in conflicts
        ]
    )


@router.post(
    "/conflicts/{conflict_id}/resolve",
    response_model=ApiResponse,
    summary="Resolve a screening conflict",
)
@limiter.limit("30/minute")
async def resolve_conflict(
    request: Request,
    conflict_id: uuid.UUID,
    payload: ResolveConflictRequest,
    db: DbSession,
    user: CurrentUser,
) -> ApiResponse[Any]:
    """Resolve a screening conflict."""
    trace_id = str(uuid.uuid4())
    existing = await ScreeningConflictRepository(db).get_by_id(conflict_id)
    if existing is not None:
        await ensure_project_member(db, existing.project_id, user.sub)
    try:
        service = ScreeningService(db=db, user_id=user.sub)
        conflict = await service.resolve_conflict(
            conflict_id=conflict_id,
            decision=payload.decision,
            reason=payload.reason,
        )
        await db.commit()

        return ApiResponse.success(
            data=ScreeningConflictResponse.model_validate(conflict).model_dump(by_alias=True),
            trace_id=trace_id,
        )
    except Exception as e:
        logger.error("screening_conflict_error", trace_id=trace_id, error=str(e))
        return ApiResponse.failure(
            code="SCREENING_CONFLICT_ERROR", message=str(e), trace_id=trace_id
        )


# =================== AI SCREENING ===================


@router.post(
    "/ai",
    response_model=ApiResponse,
    summary="AI screen single article",
)
@limiter.limit("10/minute")
async def ai_screen(
    request: Request,
    payload: AIScreeningRequest,
    db: DbSession,
    user: CurrentUser,
    supabase: SupabaseClient,
) -> ApiResponse[Any]:
    """AI-screen a single article."""
    trace_id = str(uuid.uuid4())
    await ensure_project_member(db, payload.project_id, user.sub)
    try:
        api_key_service = APIKeyService(db=db, user_id=user.sub)
        user_openai_key = await api_key_service.get_key_for_provider("openai")
        storage = create_storage_adapter(supabase)

        service = AIScreeningService(
            db=db,
            user_id=user.sub,
            storage=storage,
            trace_id=trace_id,
            openai_api_key=user_openai_key,
        )

        try:
            suggestion = await service.screen_article(
                project_id=payload.project_id,
                article_id=payload.article_id,
                phase=payload.phase,
                model=payload.model or "gpt-4o-mini",
            )
        finally:
            await service.close()

        await db.commit()

        return ApiResponse.success(
            data={
                "suggestionId": str(suggestion.id),
                "decision": suggestion.suggested_value.get("decision"),
                "relevanceScore": suggestion.suggested_value.get("relevance_score"),
                "reasoning": suggestion.reasoning,
            },
            trace_id=trace_id,
        )
    except Exception as e:
        logger.error("ai_screening_error", trace_id=trace_id, error=str(e))
        return ApiResponse.failure(code="AI_SCREENING_ERROR", message=str(e), trace_id=trace_id)


@router.post(
    "/ai/batch",
    response_model=ApiResponse,
    summary="AI screen batch of articles",
)
@limiter.limit("5/minute")
async def ai_screen_batch(
    request: Request,
    payload: BatchAIScreeningRequest,
    db: DbSession,
    user: CurrentUser,
    supabase: SupabaseClient,
) -> ApiResponse[Any]:
    """AI-screen multiple articles."""
    trace_id = str(uuid.uuid4())
    await ensure_project_member(db, payload.project_id, user.sub)
    try:
        api_key_service = APIKeyService(db=db, user_id=user.sub)
        user_openai_key = await api_key_service.get_key_for_provider("openai")
        storage = create_storage_adapter(supabase)

        service = AIScreeningService(
            db=db,
            user_id=user.sub,
            storage=storage,
            trace_id=trace_id,
            openai_api_key=user_openai_key,
        )

        try:
            results = await service.screen_batch(
                project_id=payload.project_id,
                article_ids=payload.article_ids,
                phase=payload.phase,
                model=payload.model or "gpt-4o-mini",
            )
        finally:
            await service.close()

        await db.commit()

        return ApiResponse.success(data=results, trace_id=trace_id)
    except Exception as e:
        logger.error("ai_screening_batch_error", trace_id=trace_id, error=str(e))
        return ApiResponse.failure(
            code="AI_SCREENING_BATCH_ERROR", message=str(e), trace_id=trace_id
        )


# =================== PRISMA ===================


@router.get(
    "/prisma/{project_id}",
    response_model=ApiResponse,
    summary="Get PRISMA flow data",
    dependencies=[Depends(require_project_member)],
)
async def get_prisma(
    project_id: str,
    db: DbSession,
    user: CurrentUser,
) -> ApiResponse[Any]:
    """Get PRISMA 2020 flow diagram counts."""
    service = ScreeningService(db=db, user_id=user.sub)
    prisma = await service.get_prisma_counts(uuid.UUID(project_id))
    return ApiResponse.success(data=prisma.model_dump(by_alias=True))


# =================== DASHBOARD ===================


@router.get(
    "/dashboard/{project_id}/{phase}",
    response_model=ApiResponse,
    summary="Get screening dashboard",
    dependencies=[Depends(require_project_member)],
)
async def get_dashboard(
    project_id: str,
    phase: str,
    db: DbSession,
    user: CurrentUser,
) -> ApiResponse[Any]:
    """Get screening dashboard with progress and inter-rater metrics."""
    service = ScreeningService(db=db, user_id=user.sub)
    pid = uuid.UUID(project_id)

    progress = await service.get_progress(pid, phase)
    prisma = await service.get_prisma_counts(pid)
    kappa = await service.compute_cohens_kappa(pid, phase)

    dashboard = ScreeningDashboardData(
        title_abstract_progress=progress if phase == "title_abstract" else None,
        full_text_progress=progress if phase == "full_text" else None,
        prisma=prisma,
        cohens_kappa=kappa,
    )
    return ApiResponse.success(data=dashboard.model_dump(by_alias=True))


# =================== BULK OPERATIONS ===================


@router.post(
    "/bulk-decide",
    response_model=ApiResponse,
    summary="Bulk screening decisions",
)
@limiter.limit("10/minute")
async def bulk_decide(
    request: Request,
    payload: BulkDecideRequest,
    db: DbSession,
    user: CurrentUser,
) -> ApiResponse[Any]:
    """Bulk include/exclude multiple articles."""
    trace_id = str(uuid.uuid4())
    await ensure_project_member(db, payload.project_id, user.sub)
    try:
        service = ScreeningService(db=db, user_id=user.sub)
        count = await service.bulk_decide(
            project_id=payload.project_id,
            article_ids=payload.article_ids,
            phase=payload.phase,
            decision=payload.decision,
            reason=payload.reason,
        )
        await db.commit()

        return ApiResponse.success(data={"count": count}, trace_id=trace_id)
    except Exception as e:
        logger.error("bulk_decide_error", trace_id=trace_id, error=str(e))
        return ApiResponse.failure(code="BULK_DECIDE_ERROR", message=str(e), trace_id=trace_id)


@router.post(
    "/advance-to-fulltext",
    response_model=ApiResponse,
    summary="Advance articles to full-text phase",
)
@limiter.limit("10/minute")
async def advance_to_fulltext(
    request: Request,
    payload: AdvanceToFullTextRequest,
    db: DbSession,
    user: CurrentUser,
) -> ApiResponse[Any]:
    """Advance included articles from title/abstract to full-text screening."""
    trace_id = str(uuid.uuid4())
    await ensure_project_member(db, payload.project_id, user.sub)
    try:
        service = ScreeningService(db=db, user_id=user.sub)
        count = await service.advance_to_fulltext(
            project_id=payload.project_id,
            article_ids=payload.article_ids,
        )
        await db.commit()

        return ApiResponse.success(data={"count": count}, trace_id=trace_id)
    except Exception as e:
        logger.error("advance_fulltext_error", trace_id=trace_id, error=str(e))
        return ApiResponse.failure(code="ADVANCE_ERROR", message=str(e), trace_id=trace_id)
