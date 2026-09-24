"""
Section Extraction Endpoint.

Migrado de: supabase/functions/section-extraction/index.ts

Endpoint para extração de seções específicas de templates.
Suporta extração individual ou em batch de todas as seções.
"""

import uuid

from fastapi import APIRouter, HTTPException, Request, status

from app.core.deps import CurrentUser, DbSession, SupabaseClient, ensure_project_member
from app.core.factories import create_storage_adapter
from app.core.logging import get_logger
from app.schemas.common import ApiResponse
from app.schemas.extraction import (
    BatchSectionResult,
    SectionExtractionRequest,
    SingleSectionResult,
)
from app.services.api_key_service import APIKeyService
from app.services.section_extraction_service import SectionExtractionService
from app.utils.rate_limiter import limiter

router = APIRouter()
logger = get_logger(__name__)


@router.post(
    "",
    response_model=ApiResponse,
    summary="Extrair seção(ões) de template",
    description="Extrai dados de uma seção específica ou todas as seções de um modelo.",
)
@limiter.limit("10/minute")
async def extract_section(
    request: Request,  # Necessário para o rate limiter
    payload: SectionExtractionRequest,
    db: DbSession,
    user: CurrentUser,
    supabase: SupabaseClient,
) -> ApiResponse:
    """
    Executa extração de seção(ões) de um template.

    Rate limit: 10 requisições por minuto por usuário.

    Modos de operação:
    1. Seção única: entity_type_id obrigatório
    2. Todas as seções: extract_all_sections=true, parent_instance_id obrigatório

    Args:
        request: Request HTTP (usado pelo rate limiter).
        payload: Parâmetros de extração.

    Returns:
        ApiResponse com resultado da extração.
    """
    trace_id = str(uuid.uuid4())

    logger.info(
        "section_extraction_request",
        trace_id=trace_id,
        user_id=user.sub,
        project_id=str(payload.project_id),
        article_id=str(payload.article_id),
        template_id=str(payload.template_id),
        entity_type_id=str(payload.entity_type_id) if payload.entity_type_id else None,
        extract_all_sections=payload.extract_all_sections,
        model=payload.model,
    )

    await ensure_project_member(db, payload.project_id, user.sub)

    try:
        # Cria storage adapter via factory
        storage = create_storage_adapter(supabase)

        # Buscar API key do usuário (BYOK) com fallback para global
        api_key_service = APIKeyService(db=db, user_id=user.sub)
        user_openai_key = await api_key_service.get_key_for_provider("openai")

        service = SectionExtractionService(
            db=db,
            user_id=user.sub,
            storage=storage,
            trace_id=trace_id,
            openai_api_key=user_openai_key,
        )

        if payload.extract_all_sections:
            # Extração em batch de todas as seções
            result = await service.extract_all_sections(
                project_id=payload.project_id,
                article_id=payload.article_id,
                template_id=payload.template_id,
                parent_instance_id=payload.parent_instance_id,  # type: ignore
                section_ids=payload.section_ids,
                pdf_text=payload.pdf_text,
                model=payload.model or "gpt-4o-mini",
            )

            # Commit explícito para persistir instâncias e sugestões criadas
            await db.commit()

            logger.info(
                "batch_section_extraction_success",
                trace_id=trace_id,
                run_id=result.extraction_run_id,
                total_sections=result.total_sections,
                successful=result.successful_sections,
                failed=result.failed_sections,
                tokens_total=result.total_tokens_used,
            )

            # Formatar resposta no formato camelCase para o frontend
            response_data = BatchSectionResult(
                extraction_run_id=result.extraction_run_id,
                total_sections=result.total_sections,
                successful_sections=result.successful_sections,
                failed_sections=result.failed_sections,
                total_suggestions_created=result.total_suggestions_created,
                total_tokens_used=result.total_tokens_used,
                duration_ms=result.duration_ms,
                sections=result.sections,
            ).model_dump(by_alias=True)
        else:
            # Extração de seção única
            result = await service.extract_section(
                project_id=payload.project_id,
                article_id=payload.article_id,
                template_id=payload.template_id,
                entity_type_id=payload.entity_type_id,  # type: ignore
                parent_instance_id=payload.parent_instance_id,
                model=payload.model or "gpt-4o-mini",
            )

            # Commit explícito para persistir instâncias e sugestões criadas
            await db.commit()

            logger.info(
                "section_extraction_success",
                trace_id=trace_id,
                run_id=result.extraction_run_id,
                suggestions_created=result.suggestions_created,
                tokens_total=result.tokens_total,
            )

            # Formatar resposta no formato camelCase para o frontend
            response_data = SingleSectionResult(
                extraction_run_id=result.extraction_run_id,
                entity_type_id=result.entity_type_id,
                suggestions_created=result.suggestions_created,
                tokens_prompt=result.tokens_prompt,
                tokens_completion=result.tokens_completion,
                tokens_total=result.tokens_total,
                duration_ms=result.duration_ms,
            ).model_dump(by_alias=True)

        return ApiResponse(ok=True, data=response_data, trace_id=trace_id)

    except ValueError as e:
        await db.rollback()
        logger.warning(
            "section_extraction_validation_error",
            trace_id=trace_id,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except FileNotFoundError as e:
        await db.rollback()
        logger.warning(
            "section_extraction_pdf_not_found",
            trace_id=trace_id,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PDF not found. Upload a PDF first.",
        ) from e
    except Exception as e:
        await db.rollback()
        logger.error(
            "section_extraction_error",
            trace_id=trace_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Section extraction failed: {str(e)}",
        ) from e
