"""
Dependencies Module.

Contém todas as dependencies compartilhadas da aplicação:
- Database session
- Supabase client
- Current user
- Project membership check
"""

from collections.abc import AsyncGenerator
from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from supabase import Client, create_client

from app.core.config import settings
from app.core.error_handler import AuthorizationError
from app.core.logging import get_logger
from app.core.security import TokenPayload, get_current_user
from app.repositories.project_repository import ProjectMemberRepository

logger = get_logger(__name__)

# =================== DATABASE ===================

# Engine async para PostgreSQL
# NOTA: O workaround de ::VARCHAR para ENUMs foi REMOVIDO.
# Agora usamos PostgreSQLEnumType (em app.models.base) que resolve o problema
# de forma declarativa diretamente nos models SQLAlchemy.
engine = create_async_engine(
    settings.async_database_url,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    connect_args={
        "statement_cache_size": 0,  # ✅ Desabilita prepared statements (compatível com pgbouncer)
        "server_settings": {
            "jit": "off",  # Desabilita JIT para melhor performance em queries complexas
        },
    },
)

# Session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency que fornece uma sessão de banco de dados.
    
    A sessão é automaticamente fechada ao final da request.
    
    Yields:
        AsyncSession: Sessão do SQLAlchemy.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


# Type alias para uso nas rotas
DbSession = Annotated[AsyncSession, Depends(get_db)]


# =================== SUPABASE CLIENT ===================

@lru_cache
def get_supabase_client() -> Client:
    """
    Retorna cliente Supabase configurado com service role.
    
    Usado para operações que precisam de acesso elevado:
    - Storage operations
    - Bypass RLS quando necessário
    
    Returns:
        Client: Supabase client configurado.
    """
    return create_client(
        settings.SUPABASE_URL,
        settings.SUPABASE_SERVICE_ROLE_KEY,
    )


def get_supabase() -> Client:
    """Dependency para obter Supabase client."""
    return get_supabase_client()


SupabaseClient = Annotated[Client, Depends(get_supabase)]


# =================== CURRENT USER ===================

CurrentUser = Annotated[TokenPayload, Depends(get_current_user)]


# =================== PROJECT MEMBERSHIP ===================

NOT_A_MEMBER_MESSAGE = "User is not a member of this project."


async def ensure_project_member(
    db: AsyncSession,
    project_id: UUID | str,
    user_id: UUID | str,
) -> None:
    """
    Ensure that the user is a member of the project.

    The backend talks to Postgres directly (RLS does not apply), so every
    route that receives a project_id must run this check before reading or
    writing project data.

    Raises:
        AuthorizationError: HTTP 403 when the user is not a member, or when
            the ids are not valid UUIDs.
    """
    try:
        project_uuid = project_id if isinstance(project_id, UUID) else UUID(str(project_id))
        user_uuid = user_id if isinstance(user_id, UUID) else UUID(str(user_id))
    except (TypeError, ValueError):
        raise AuthorizationError(NOT_A_MEMBER_MESSAGE) from None

    if not await ProjectMemberRepository(db).is_member(project_uuid, user_uuid):
        raise AuthorizationError(NOT_A_MEMBER_MESSAGE)


async def require_project_member(
    project_id: UUID,
    db: DbSession,
    user: CurrentUser,
) -> UUID:
    """
    FastAPI dependency for routes with a `project_id` path or query parameter.

    Returns the validated project id, or answers 403 when the current user is
    not a member of the project. Routes that receive project_id in the body or
    in a form must call ensure_project_member() explicitly.
    """
    await ensure_project_member(db, project_id, user.sub)
    return project_id


ProjectMemberId = Annotated[UUID, Depends(require_project_member)]


# =================== COMBINED DEPENDENCIES ===================

class RequestContext:
    """
    Contexto da requisição com todas as dependencies comuns.
    
    Agrupa db, user e supabase para facilitar passagem para services.
    """
    
    def __init__(
        self,
        db: AsyncSession,
        user: TokenPayload,
        supabase: Client,
    ):
        self.db = db
        self.user = user
        self.supabase = supabase
    
    @property
    def user_id(self) -> str:
        """ID do usuário atual."""
        return self.user.sub


async def get_request_context(
    db: DbSession,
    user: CurrentUser,
    supabase: SupabaseClient,
) -> RequestContext:
    """
    Dependency que fornece contexto completo da requisição.
    
    Útil para services que precisam de múltiplas dependencies.
    """
    return RequestContext(db=db, user=user, supabase=supabase)


RequestCtx = Annotated[RequestContext, Depends(get_request_context)]

