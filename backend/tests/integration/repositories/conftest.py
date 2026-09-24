"""
Fixtures for repository integration tests.

These tests run the repositories against the real PostgreSQL database
(DATABASE_URL). Repositories only flush, so every test runs inside one
transaction that the ``session`` fixture rolls back at teardown.
"""

from collections.abc import AsyncGenerator
from uuid import UUID

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.article import Article
from app.models.project import Project
from tests.integration.repositories.factories import (
    create_article,
    create_project,
    create_user,
)


@pytest_asyncio.fixture
async def session(db_session: AsyncSession) -> AsyncGenerator[AsyncSession, None]:
    """Database session whose changes are always rolled back."""
    try:
        yield db_session
    finally:
        await db_session.rollback()


@pytest_asyncio.fixture
async def user_id(session: AsyncSession) -> UUID:
    """Id of a freshly created user profile."""
    return await create_user(session)


@pytest_asyncio.fixture
async def project(session: AsyncSession, user_id: UUID) -> Project:
    """Project owned by ``user_id``."""
    return await create_project(session, user_id)


@pytest_asyncio.fixture
async def article(session: AsyncSession, project: Project) -> Article:
    """Article that belongs to ``project``."""
    return await create_article(session, project.id)
