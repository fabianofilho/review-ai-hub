"""
AI Assessment Endpoint.

Migrado de: supabase/functions/ai-assessment/index.ts

Endpoint para avaliação de artigos usando IA (OpenAI Responses API).
Suporta leitura direta de PDF com fallback para File Search.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import (
    CurrentUser,
    DbSession,
    SupabaseClient,
    ensure_project_member,
    require_project_member,
)
from app.core.error_handler import AuthorizationError
from app.core.factories import create_storage_adapter
from app.core.logging import get_logger
from app.models.assessment import AIAssessmentRun
from app.models.extraction import AISuggestion, ExtractionRun
from app.models.screening import ScreeningRun
from app.repositories.extraction_repository import AISuggestionRepository
from app.services.api_key_service import APIKeyService
from app.schemas.assessment import (
    AIAssessmentRequest,
    AIAssessmentResponseData,
    AISuggestionSchema,
    BatchAIAssessmentRequest,
    BatchAIAssessmentResponseData,
    ListSuggestionsResponse,
    ReviewAISuggestionRequest,
    ReviewAISuggestionResponse,
)
from app.schemas.common import ApiResponse
from app.services.ai_assessment_service import AIAssessmentService
from app.utils.rate_limiter import limiter

router = APIRouter()
logger = get_logger(__name__)


async def _ensure_suggestion_access(
    db: AsyncSession,
    suggestion: AISuggestion,
    user_id: str,
) -> None:
    """Ensure the user is a member of the project that owns the suggestion's run."""
    run: AIAssessmentRun | ExtractionRun | ScreeningRun | None = None
    if suggestion.assessment_run_id is not None:
        run = await db.get(AIAssessmentRun, suggestion.assessment_run_id)
    elif suggestion.extraction_run_id is not None:
        run = await db.get(ExtractionRun, suggestion.extraction_run_id)
    elif suggestion.screening_run_id is not None:
        run = await db.get(ScreeningRun, suggestion.screening_run_id)
    if run is None:
        # Without a run the owning project is unknown: deny by default.
        raise AuthorizationError("User is not a member of this project.")
    await ensure_project_member(db, run.project_id, user_id)


@router.post(
    "/ai",
    response_model=ApiResponse,
    summary="Avaliar artigo com IA",
    description="Usa OpenAI para avaliar um item de assessment baseado no PDF do artigo.",
)
@limiter.limit("10/minute")
async def ai_assessment(
    request: Request,  # Necessário para o rate limiter
    payload: AIAssessmentRequest,
    db: DbSession,
    user: CurrentUser,
    supabase: SupabaseClient,
) -> ApiResponse:
    """
    Executa avaliação AI de um item de assessment.
    
    Rate limit: 10 requisições por minuto por usuário.
    
    Args:
        request: Request HTTP (usado pelo rate limiter).
        payload: Dados do assessment a avaliar.
        
    Returns:
        ApiResponse com resultado da avaliação.
    """
    trace_id = str(uuid.uuid4())
    
    logger.info(
        "ai_assessment_request",
        trace_id=trace_id,
        user_id=user.sub,
        project_id=str(payload.project_id),
        article_id=str(payload.article_id),
        assessment_item_id=str(payload.assessment_item_id),
    )

    await ensure_project_member(db, payload.project_id, user.sub)

    try:
        # Resolve user's stored API key (BYOK) with env var fallback
        api_key_service = APIKeyService(db=db, user_id=user.sub)
        user_openai_key = await api_key_service.get_key_for_provider("openai")

        # Cria storage adapter via factory
        storage = create_storage_adapter(supabase)

        service = AIAssessmentService(
            db=db,
            user_id=user.sub,
            storage=storage,
            trace_id=trace_id,
            openai_api_key=user_openai_key,
        )

        result = await service.assess(
            project_id=payload.project_id,
            article_id=payload.article_id,
            assessment_item_id=payload.assessment_item_id,
            instrument_id=payload.instrument_id,
            pdf_storage_key=payload.pdf_storage_key,
            pdf_base64=payload.pdf_base64,
            pdf_filename=payload.pdf_filename,
            pdf_file_id=payload.pdf_file_id,
            force_file_search=payload.force_file_search,
            model=payload.model or "gpt-4o-mini",
            extraction_instance_id=payload.extraction_instance_id,  # For PROBAST by model
        )
        
        # Commit explícito para persistir os resultados
        await db.commit()
        
        logger.info(
            "ai_assessment_success",
            trace_id=trace_id,
            user_id=user.sub,
            assessment_id=result.assessment_id,
            tokens_total=result.tokens_prompt + result.tokens_completion,
            method_used=result.method_used,
        )
        
        # Formatar resposta no formato camelCase para o frontend
        response_data = AIAssessmentResponseData(
            id=result.assessment_id,
            selected_level=result.selected_level,
            confidence_score=result.confidence_score,
            justification=result.justification,
            evidence_passages=result.evidence_passages,
            status="pending_review",
            metadata={
                "processingTimeMs": result.processing_time_ms,
                "tokensPrompt": result.tokens_prompt,
                "tokensCompletion": result.tokens_completion,
                "methodUsed": result.method_used,
            },
        ).model_dump(by_alias=True)
        
        return ApiResponse(ok=True, data=response_data, trace_id=trace_id)
        
    except ValueError as e:
        await db.rollback()
        logger.warning(
            "ai_assessment_validation_error",
            trace_id=trace_id,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except Exception as e:
        await db.rollback()
        logger.error(
            "ai_assessment_error",
            trace_id=trace_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Assessment failed: {str(e)}",
        ) from e


@router.post(
    "/ai/batch",
    response_model=ApiResponse,
    summary="Avaliar múltiplos itens com IA",
    description="Usa OpenAI para avaliar múltiplos itens de assessment em batch.",
)
@limiter.limit("5/minute")
async def ai_assessment_batch(
    request: Request,
    payload: BatchAIAssessmentRequest,
    db: DbSession,
    user: CurrentUser,
    supabase: SupabaseClient,
) -> ApiResponse:
    """
    Executa avaliação AI em batch para múltiplos itens.
    
    Rate limit: 5 requisições por minuto por usuário.
    
    Args:
        request: Request HTTP (usado pelo rate limiter).
        payload: Dados dos itens a avaliar.
        
    Returns:
        ApiResponse com lista de resultados.
    """
    trace_id = str(uuid.uuid4())
    
    logger.info(
        "ai_assessment_batch_request",
        trace_id=trace_id,
        user_id=user.sub,
        project_id=str(payload.project_id),
        article_id=str(payload.article_id),
        items_count=len(payload.item_ids),
    )

    await ensure_project_member(db, payload.project_id, user.sub)

    try:
        # Resolve user's stored API key (BYOK) with env var fallback
        api_key_service = APIKeyService(db=db, user_id=user.sub)
        user_openai_key = await api_key_service.get_key_for_provider("openai")

        storage = create_storage_adapter(supabase)

        service = AIAssessmentService(
            db=db,
            user_id=user.sub,
            storage=storage,
            trace_id=trace_id,
            openai_api_key=user_openai_key,
        )

        results = await service.assess_batch(
            project_id=payload.project_id,
            article_id=payload.article_id,
            item_ids=payload.item_ids,
            instrument_id=payload.instrument_id,
            model=payload.model or "gpt-4o-mini",
            extraction_instance_id=payload.extraction_instance_id,  # For PROBAST by model
        )
        
        await db.commit()
        
        # Formatar respostas
        formatted_results = [service.to_dict(r) for r in results]
        
        logger.info(
            "ai_assessment_batch_success",
            trace_id=trace_id,
            user_id=user.sub,
            total_items=len(payload.item_ids),
            successful_items=len(results),
        )
        
        response_data = BatchAIAssessmentResponseData(
            results=formatted_results,
            total_items=len(payload.item_ids),
            successful_items=len(results),
        ).model_dump(by_alias=True)

        return ApiResponse(ok=True, data=response_data, trace_id=trace_id)
        
    except Exception as e:
        await db.rollback()
        logger.error(
            "ai_assessment_batch_error",
            trace_id=trace_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Batch assessment failed: {str(e)}",
        ) from e


@router.get(
    "/ai/suggestions",
    response_model=ApiResponse,
    summary="Listar sugestões de AI pendentes",
    description="Lista sugestões de AI que aguardam revisão humana.",
    dependencies=[Depends(require_project_member)],
)
@limiter.limit("30/minute")
async def list_ai_suggestions(
    request: Request,
    project_id: str,
    article_id: str,
    instrument_id: str | None = None,
    extraction_instance_id: str | None = None,
    status_filter: str | None = None,
    db: DbSession = None,
    user: CurrentUser = None,
) -> ApiResponse:
    """
    Lista sugestões de AI pendentes de revisão.

    Args:
        project_id: ID do projeto.
        article_id: ID do artigo.
        instrument_id: Filtrar por instrumento (opcional).
        extraction_instance_id: Filtrar por extraction instance (opcional).
        status_filter: Filtrar por status: 'pending', 'accepted', 'rejected' (opcional).

    Returns:
        ApiResponse com lista de sugestões.
    """
    trace_id = str(uuid.uuid4())

    try:
        from app.repositories.extraction_repository import AISuggestionRepository
        from sqlalchemy import and_, or_, select
        from app.models.extraction import AISuggestion
        from app.models.assessment import AIAssessmentRun

        # Build query - include both global and project-scoped assessment suggestions
        query = select(AISuggestion).where(
            or_(
                AISuggestion.assessment_item_id.isnot(None),
                AISuggestion.project_assessment_item_id.isnot(None),
            )
        )

        # Join with runs to filter by project/article
        query = query.join(
            AIAssessmentRun,
            AISuggestion.assessment_run_id == AIAssessmentRun.id
        ).where(
            and_(
                AIAssessmentRun.project_id == uuid.UUID(project_id),
                AIAssessmentRun.article_id == uuid.UUID(article_id),
            )
        )

        # Apply filters
        if instrument_id:
            query = query.where(AIAssessmentRun.instrument_id == uuid.UUID(instrument_id))

        if extraction_instance_id:
            query = query.where(
                AIAssessmentRun.extraction_instance_id == uuid.UUID(extraction_instance_id)
            )

        if status_filter:
            query = query.where(AISuggestion.status == status_filter)

        # Execute query
        result = await db.execute(query.order_by(AISuggestion.created_at.desc()))
        suggestions = result.scalars().all()

        # Format response
        suggestions_data = [
            AISuggestionSchema.model_validate(s).model_dump(by_alias=True)
            for s in suggestions
        ]

        response_data = ListSuggestionsResponse(
            suggestions=suggestions_data,
            total=len(suggestions_data),
        ).model_dump(by_alias=True)

        return ApiResponse(ok=True, data=response_data, trace_id=trace_id)

    except Exception as e:
        logger.error(
            "list_ai_suggestions_error",
            trace_id=trace_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list suggestions: {str(e)}",
        ) from e


@router.post(
    "/ai/suggestions/{suggestion_id}/review",
    response_model=ApiResponse,
    summary="Revisar sugestão de AI",
    description="Aceita, rejeita ou modifica uma sugestão de AI.",
)
@limiter.limit("20/minute")
async def review_ai_suggestion(
    request: Request,
    suggestion_id: str,
    payload: ReviewAISuggestionRequest,
    db: DbSession,
    user: CurrentUser,
) -> ApiResponse:
    """
    Revisa uma sugestão de AI (accept/reject/modify).

    Workflow:
    - accept: Marca sugestão como aceita e cria AIAssessment final
    - reject: Marca sugestão como rejeitada (não cria assessment)
    - modify: Marca sugestão como aceita com valor modificado e cria AIAssessment

    Args:
        suggestion_id: ID da sugestão.
        payload: Ação de revisão e dados opcionais.

    Returns:
        ApiResponse com resultado da revisão.
    """
    trace_id = str(uuid.uuid4())

    logger.info(
        "review_ai_suggestion_request",
        trace_id=trace_id,
        user_id=user.sub,
        suggestion_id=suggestion_id,
        action=payload.action,
    )

    existing = await AISuggestionRepository(db).get_by_id(uuid.UUID(suggestion_id))
    if existing is not None:
        await _ensure_suggestion_access(db, existing, user.sub)

    try:
        from app.repositories.assessment_repository import AIAssessmentRepository
        from app.models.assessment import AIAssessment

        suggestion_repo = AISuggestionRepository(db)
        assessment_repo = AIAssessmentRepository(db)

        # 1. Fetch suggestion
        suggestion = await suggestion_repo.get_by_id(uuid.UUID(suggestion_id))
        if not suggestion:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Suggestion {suggestion_id} not found",
            )

        # 2. Validate status
        if suggestion.status != "pending":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Suggestion already reviewed: {suggestion.status}",
            )

        assessment_created = False
        assessment_id = None

        # 3. Process action
        if payload.action == "accept":
            # Accept suggestion and create final assessment
            suggestion.status = "accepted"
            await suggestion_repo.update(suggestion)

            # Create AIAssessment from suggestion
            assessment = AIAssessment(
                id=uuid.uuid4(),
                run_id=suggestion.assessment_run_id,
                assessment_item_id=suggestion.assessment_item_id,
                selected_level=suggestion.suggested_value.get("level", ""),
                confidence_score=suggestion.confidence_score,
                justification=suggestion.reasoning or "",
                evidence_passages=suggestion.suggested_value.get("evidence_passages", []),
                status="completed",
                reviewed_by=uuid.UUID(user.sub),
                metadata_=suggestion.metadata_,
            )
            saved_assessment = await assessment_repo.create(assessment)
            assessment_created = True
            assessment_id = saved_assessment.id

        elif payload.action == "modify":
            # Accept with modifications
            if not payload.modified_value:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="modified_value is required for modify action",
                )

            suggestion.status = "accepted"
            await suggestion_repo.update(suggestion)

            # Create AIAssessment with modified values
            assessment = AIAssessment(
                id=uuid.uuid4(),
                run_id=suggestion.assessment_run_id,
                assessment_item_id=suggestion.assessment_item_id,
                selected_level=payload.modified_value.get("level", ""),
                confidence_score=payload.modified_value.get("confidence_score"),
                justification=payload.review_notes or suggestion.reasoning or "",
                evidence_passages=payload.modified_value.get("evidence_passages", []),
                status="completed",
                reviewed_by=uuid.UUID(user.sub),
                metadata_={
                    **suggestion.metadata_,
                    "modified": True,
                    "original_suggestion": suggestion.suggested_value,
                },
            )
            saved_assessment = await assessment_repo.create(assessment)
            assessment_created = True
            assessment_id = saved_assessment.id

        elif payload.action == "reject":
            # Reject suggestion (no assessment created)
            suggestion.status = "rejected"
            suggestion.metadata_["rejection_notes"] = payload.review_notes
            await suggestion_repo.update(suggestion)

        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid action: {payload.action}",
            )

        await db.commit()

        logger.info(
            "review_ai_suggestion_success",
            trace_id=trace_id,
            user_id=user.sub,
            suggestion_id=suggestion_id,
            action=payload.action,
            assessment_created=assessment_created,
            assessment_id=str(assessment_id) if assessment_id else None,
        )

        response_data = ReviewAISuggestionResponse(
            suggestion_id=uuid.UUID(suggestion_id),
            action=payload.action,
            assessment_created=assessment_created,
            assessment_id=assessment_id,
        ).model_dump(by_alias=True)

        return ApiResponse(ok=True, data=response_data, trace_id=trace_id)

    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.error(
            "review_ai_suggestion_error",
            trace_id=trace_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Review failed: {str(e)}",
        ) from e
