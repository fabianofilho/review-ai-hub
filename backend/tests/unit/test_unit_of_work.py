"""Unit tests for UnitOfWork transaction coordination."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.article_author_repository import (
    ArticleAuthorLinkRepository,
    ArticleAuthorRepository,
)
from app.repositories.article_repository import (
    ArticleFileRepository,
    ArticleRepository,
    ArticleSyncEventRepository,
    ArticleSyncRunRepository,
)
from app.repositories.assessment_repository import (
    AIAssessmentRepository,
    AssessmentEvidenceRepository,
    AssessmentInstanceRepository,
    AssessmentInstrumentRepository,
    AssessmentItemRepository,
    AssessmentResponseRepository,
)
from app.repositories.extraction_repository import (
    AISuggestionRepository,
    ExtractionEntityTypeRepository,
    ExtractionInstanceRepository,
    ExtractionTemplateRepository,
    GlobalTemplateRepository,
)
from app.repositories.integration_repository import ZoteroIntegrationRepository
from app.repositories.project_repository import ProjectMemberRepository, ProjectRepository
from app.repositories.unit_of_work import UnitOfWork

EXPECTED_REPOSITORIES = {
    "articles": ArticleRepository,
    "article_files": ArticleFileRepository,
    "article_authors": ArticleAuthorRepository,
    "article_author_links": ArticleAuthorLinkRepository,
    "article_sync_runs": ArticleSyncRunRepository,
    "article_sync_events": ArticleSyncEventRepository,
    "projects": ProjectRepository,
    "project_members": ProjectMemberRepository,
    "assessment_instruments": AssessmentInstrumentRepository,
    "assessment_items": AssessmentItemRepository,
    "assessment_instances": AssessmentInstanceRepository,
    "assessment_responses": AssessmentResponseRepository,
    "assessment_evidence": AssessmentEvidenceRepository,
    "ai_assessments": AIAssessmentRepository,
    "extraction_templates": ExtractionTemplateRepository,
    "global_templates": GlobalTemplateRepository,
    "entity_types": ExtractionEntityTypeRepository,
    "extraction_instances": ExtractionInstanceRepository,
    "ai_suggestions": AISuggestionRepository,
    "zotero_integrations": ZoteroIntegrationRepository,
}


@pytest.fixture
def session() -> AsyncMock:
    return AsyncMock(spec=AsyncSession)


def test_init_wires_every_repository_to_the_same_session(session: AsyncMock) -> None:
    uow = UnitOfWork(session)

    assert uow.session is session
    for attribute, repository_class in EXPECTED_REPOSITORIES.items():
        repository = getattr(uow, attribute)
        assert isinstance(repository, repository_class), attribute
        assert repository.db is session, attribute


async def test_commit_delegates_to_session(session: AsyncMock) -> None:
    await UnitOfWork(session).commit()

    session.commit.assert_awaited_once_with()
    session.rollback.assert_not_awaited()


async def test_rollback_delegates_to_session(session: AsyncMock) -> None:
    await UnitOfWork(session).rollback()

    session.rollback.assert_awaited_once_with()
    session.commit.assert_not_awaited()


async def test_flush_delegates_to_session(session: AsyncMock) -> None:
    await UnitOfWork(session).flush()

    session.flush.assert_awaited_once_with()


async def test_refresh_delegates_to_session(session: AsyncMock) -> None:
    obj = MagicMock()

    await UnitOfWork(session).refresh(obj)

    session.refresh.assert_awaited_once_with(obj)


async def test_context_manager_returns_itself(session: AsyncMock) -> None:
    uow = UnitOfWork(session)

    async with uow as entered:
        assert entered is uow


async def test_clean_exit_neither_commits_nor_rolls_back(session: AsyncMock) -> None:
    async with UnitOfWork(session):
        pass

    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()


async def test_exception_rolls_back_and_propagates(session: AsyncMock) -> None:
    with pytest.raises(RuntimeError, match="boom"):
        async with UnitOfWork(session):
            raise RuntimeError("boom")

    session.rollback.assert_awaited_once_with()
    session.commit.assert_not_awaited()


async def test_exception_after_explicit_commit_still_rolls_back(session: AsyncMock) -> None:
    with pytest.raises(ValueError):
        async with UnitOfWork(session) as uow:
            await uow.commit()
            raise ValueError("after commit")

    session.commit.assert_awaited_once_with()
    session.rollback.assert_awaited_once_with()
