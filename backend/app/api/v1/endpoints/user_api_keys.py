"""
User API Keys Endpoint.

Endpoints para gerenciar API keys de provedores externos (OpenAI, Anthropic, etc.).
As keys são criptografadas via Fernet na aplicação (mesmo padrão de ZoteroIntegration).
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.core.deps import CurrentUser, DbSession
from app.core.logging import get_logger
from app.schemas.common import ApiResponse
from app.schemas.user_api_key import (
    APIKeyResponse,
    CreateAPIKeyRequest,
    UpdateAPIKeyRequest,
)
from app.services.api_key_service import APIKeyService

router = APIRouter()
logger = get_logger(__name__)


@router.get(
    "",
    response_model=ApiResponse,
    summary="Listar API keys",
    description="Lista todas as API keys do usuário (sem expor as keys).",
)
async def list_api_keys(
    db: DbSession,
    user: CurrentUser,
    active_only: bool = True,
) -> ApiResponse:
    """
    Lista API keys do usuário autenticado.

    Retorna metadados das keys (provedor, status, etc.) sem expor as keys.
    """
    logger.info(
        "api_keys_list_start",
        user_id=user.sub,
        user_email=user.email,
        active_only=active_only,
    )

    service = APIKeyService(db=db, user_id=user.sub)

    try:
        logger.debug("api_keys_list_calling_service", user_id=user.sub)
        keys = await service.list_keys(active_only=active_only)
        logger.debug("api_keys_list_service_returned", user_id=user.sub, count=len(keys))

        result = [
            APIKeyResponse(
                id=str(key.id),
                provider=key.provider,
                key_name=key.key_name,
                is_active=key.is_active,
                is_default=key.is_default,
                validation_status=key.validation_status,
                last_used_at=key.last_used_at.isoformat() if key.last_used_at else None,
                last_validated_at=key.last_validated_at.isoformat()
                if key.last_validated_at
                else None,
                created_at=key.created_at.isoformat(),
            ).model_dump(by_alias=True)
            for key in keys
        ]

        logger.info(
            "api_keys_listed",
            user_id=user.sub,
            count=len(result),
        )

        return ApiResponse(ok=True, data={"keys": result})

    except Exception as e:
        import traceback

        error_traceback = traceback.format_exc()
        logger.error(
            "api_keys_list_error",
            user_id=user.sub,
            error=str(e),
            error_type=type(e).__name__,
            error_traceback=error_traceback,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao listar API keys: {type(e).__name__}: {str(e)}",
        ) from e


@router.post(
    "",
    response_model=ApiResponse,
    summary="Criar API key",
    description="Adiciona nova API key para um provedor.",
)
async def create_api_key(
    db: DbSession,
    user: CurrentUser,
    request: CreateAPIKeyRequest,
) -> ApiResponse:
    """
    Cria nova API key.

    A key é criptografada automaticamente via Fernet.
    Opcionalmente valida a key antes de salvar.
    """
    service = APIKeyService(db=db, user_id=user.sub)

    try:
        result = await service.save_key(
            provider=request.provider,
            api_key=request.api_key,
            key_name=request.key_name,
            is_default=request.is_default,
            key_metadata=request.key_metadata,
            validate=request.validate_key,
        )

        # Commit explícito para persistir a key
        await db.commit()

        logger.info(
            "api_key_created",
            user_id=user.sub,
            provider=request.provider,
            key_id=result["id"],
        )

        return ApiResponse(ok=True, data=result)

    except ValueError as e:
        logger.warning(
            "api_key_create_validation_error",
            user_id=user.sub,
            provider=request.provider,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except Exception as e:
        logger.error(
            "api_key_create_error",
            user_id=user.sub,
            provider=request.provider,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao criar API key: {str(e)}",
        ) from e


@router.patch(
    "/{key_id}",
    response_model=ApiResponse,
    summary="Atualizar API key",
    description="Atualiza propriedades de uma API key.",
)
async def update_api_key(
    key_id: UUID,
    db: DbSession,
    user: CurrentUser,
    request: UpdateAPIKeyRequest,
) -> ApiResponse:
    """
    Atualiza uma API key existente.

    Permite alterar is_default, is_active e key_name.
    """
    service = APIKeyService(db=db, user_id=user.sub)

    try:
        # Se está marcando como default
        if request.is_default is True:
            success = await service.set_default(key_id)
            if not success:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="API key não encontrada",
                )

        # Se está desativando
        if request.is_active is False:
            success = await service.deactivate_key(key_id)
            if not success:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="API key não encontrada",
                )

        # Commit explícito para persistir alterações
        await db.commit()

        logger.info(
            "api_key_updated",
            user_id=user.sub,
            key_id=str(key_id),
        )

        return ApiResponse(ok=True, data={"id": str(key_id), "updated": True})

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "api_key_update_error",
            user_id=user.sub,
            key_id=str(key_id),
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao atualizar API key: {str(e)}",
        ) from e


@router.get(
    "/providers",
    response_model=ApiResponse,
    summary="Listar provedores suportados",
    description="Lista os provedores de IA suportados.",
)
async def list_providers() -> ApiResponse:
    """
    Lista os provedores de IA suportados.

    Retorna informações sobre cada provedor.
    Endpoint público - não requer autenticação.
    """
    providers = [
        {
            "id": "openai",
            "name": "OpenAI",
            "description": "GPT-4, GPT-4o, etc.",
            "docsUrl": "https://platform.openai.com/api-keys",
        },
        {
            "id": "anthropic",
            "name": "Anthropic",
            "description": "Claude 3, Claude 3.5, etc.",
            "docsUrl": "https://console.anthropic.com/settings/keys",
        },
        {
            "id": "gemini",
            "name": "Google Gemini",
            "description": "Gemini Pro, Gemini Ultra, etc.",
            "docsUrl": "https://aistudio.google.com/app/apikey",
        },
        {
            "id": "grok",
            "name": "xAI Grok",
            "description": "Grok-1, Grok-2, etc.",
            "docsUrl": "https://console.x.ai/",
        },
    ]

    return ApiResponse(ok=True, data={"providers": providers})


@router.delete(
    "/{key_id}",
    response_model=ApiResponse,
    summary="Remover API key",
    description="Remove permanentemente uma API key.",
)
async def delete_api_key(
    key_id: UUID,
    db: DbSession,
    user: CurrentUser,
) -> ApiResponse:
    """
    Remove permanentemente uma API key.

    Esta operação não pode ser desfeita.
    """
    service = APIKeyService(db=db, user_id=user.sub)

    try:
        success = await service.delete_key(key_id)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="API key não encontrada",
            )

        # Commit explícito para persistir deleção
        await db.commit()

        logger.info(
            "api_key_deleted",
            user_id=user.sub,
            key_id=str(key_id),
        )

        return ApiResponse(ok=True, data={"id": str(key_id), "deleted": True})

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "api_key_delete_error",
            user_id=user.sub,
            key_id=str(key_id),
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao remover API key: {str(e)}",
        ) from e


@router.post(
    "/{key_id}/validate",
    response_model=ApiResponse,
    summary="Revalidar API key",
    description="Revalida uma API key existente.",
)
async def validate_api_key(
    key_id: UUID,
    db: DbSession,
    user: CurrentUser,
) -> ApiResponse:
    """
    Revalida uma API key existente.

    Faz uma chamada de teste ao provedor para verificar se a key é válida.
    """
    service = APIKeyService(db=db, user_id=user.sub)

    try:
        result = await service.revalidate_key(key_id)

        # Commit explícito para persistir status de validação
        await db.commit()

        logger.info(
            "api_key_validated",
            user_id=user.sub,
            key_id=str(key_id),
            status=result["status"],
        )

        return ApiResponse(ok=True, data=result)

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except Exception as e:
        logger.error(
            "api_key_validate_error",
            user_id=user.sub,
            key_id=str(key_id),
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao validar API key: {str(e)}",
        ) from e
