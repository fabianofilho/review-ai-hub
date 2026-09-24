"""
Pytest Configuration.

Fixtures compartilhadas para todos os testes.
Suporta testes com mocks e testes de integração com banco real.
"""

import asyncio
import uuid
from collections.abc import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.deps import get_db, get_supabase
from app.core.security import TokenPayload, get_current_user
from app.main import app

# =================== EVENT LOOP ===================


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# =================== FIXTURES COM MOCKS (para testes leves) ===================


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """
    Fixture que fornece cliente HTTP para testes de API.

    Sobrescreve dependencies de banco e autenticação com mocks.
    Use para testes que não precisam de banco de dados real.
    """

    # Mock da sessão de banco
    mock_db = AsyncMock(spec=AsyncSession)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield mock_db

    async def override_get_current_user() -> TokenPayload:
        return TokenPayload(
            sub="test-user-id",
            email="test@example.com",
            role="authenticated",
            aal="aal1",
        )

    # Mock do Supabase client
    mock_supabase = MagicMock()
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = (
        MagicMock(data=[])
    )

    def override_get_supabase() -> MagicMock:
        return mock_supabase

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_supabase] = override_get_supabase

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


# =================== FIXTURES COM BANCO REAL ===================


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Fixture que fornece sessão de banco de dados REAL para testes de integração.

    Cria engine e sessão por teste para evitar problemas de event loop.
    """
    # Criar engine por teste para evitar problemas com event loop
    database_url = settings.async_database_url
    engine = create_async_engine(
        database_url,
        echo=False,
        pool_pre_ping=True,
    )

    async_session = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def db_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """
    Fixture que fornece cliente HTTP com banco de dados REAL.

    Use para testes de integração que precisam do banco.
    """

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    async def override_get_current_user() -> TokenPayload:
        return TokenPayload(
            sub="test-user-id",
            email="test@example.com",
            role="authenticated",
            aal="aal1",
        )

    # Mock do Supabase client (ainda mockado para Storage)
    mock_supabase = MagicMock()
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = (
        MagicMock(data=[])
    )

    def override_get_supabase() -> MagicMock:
        return mock_supabase

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_supabase] = override_get_supabase

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


# =================== FIXTURES DE DADOS DE TESTE ===================


@pytest.fixture
def test_user_id() -> str:
    """ID de usuário para testes."""
    return str(uuid.uuid4())


@pytest.fixture
def test_org_id() -> str:
    """ID de organização para testes."""
    return str(uuid.uuid4())


@pytest.fixture
def mock_user() -> TokenPayload:
    """Fixture com usuário mock para testes."""
    return TokenPayload(
        sub="test-user-id",
        email="test@example.com",
        role="authenticated",
        aal="aal1",
    )


@pytest.fixture
def sample_pdf_bytes() -> bytes:
    """
    Fixture com PDF de exemplo para testes.

    Cria um PDF mínimo válido.
    """
    # PDF mínimo válido
    return b"""%PDF-1.4
1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj
2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj
3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >> endobj
4 0 obj << /Length 44 >> stream
BT /F1 12 Tf 100 700 Td (Test PDF) Tj ET
endstream endobj
xref
0 5
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000214 00000 n 
trailer << /Size 5 /Root 1 0 R >>
startxref
306
%%EOF"""
