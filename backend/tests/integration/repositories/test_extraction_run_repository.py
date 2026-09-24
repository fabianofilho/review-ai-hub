"""Integration tests for ExtractionRunRepository."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.article import Article
from app.models.extraction import (
    ExtractionRun,
    ExtractionRunStage,
    ExtractionRunStatus,
    ProjectExtractionTemplate,
)
from app.models.project import Project
from app.repositories.extraction_run_repository import ExtractionRunRepository
from tests.integration.repositories.factories import (
    add,
    at,
    create_article,
    create_project,
    create_project_template,
)


@pytest.fixture
def repo(session: AsyncSession) -> ExtractionRunRepository:
    return ExtractionRunRepository(session)


@pytest_asyncio.fixture
async def template(
    session: AsyncSession, project: Project, user_id: UUID
) -> ProjectExtractionTemplate:
    return await create_project_template(session, project.id, user_id)


async def _run(
    session: AsyncSession,
    article: Article,
    template: ProjectExtractionTemplate,
    user_id: UUID,
    *,
    stage: str = "data_suggest",
    status: str = "pending",
    minute: int = 0,
    project_id: UUID | None = None,
) -> ExtractionRun:
    return await add(
        session,
        ExtractionRun(
            project_id=project_id or article.project_id,
            article_id=article.id,
            template_id=template.id,
            stage=stage,
            status=status,
            created_by=user_id,
            created_at=at(minute),
        ),
    )


class TestCreateRun:
    async def test_creates_pending_run_from_enum_stage(
        self,
        repo: ExtractionRunRepository,
        project: Project,
        article: Article,
        template: ProjectExtractionTemplate,
        user_id: UUID,
    ) -> None:
        run = await repo.create_run(
            project_id=project.id,
            article_id=article.id,
            template_id=template.id,
            stage=ExtractionRunStage.DATA_SUGGEST,
            created_by=user_id,
            parameters={"model": "gpt-4o"},
        )

        assert run.id is not None
        assert run.stage == "data_suggest"
        assert run.status == ExtractionRunStatus.PENDING.value
        assert run.parameters == {"model": "gpt-4o"}
        assert run.results == {}
        assert run.created_at is not None

    async def test_accepts_plain_string_stage_and_defaults_parameters(
        self,
        repo: ExtractionRunRepository,
        project: Project,
        article: Article,
        template: ProjectExtractionTemplate,
        user_id: UUID,
    ) -> None:
        run = await repo.create_run(
            project_id=project.id,
            article_id=article.id,
            template_id=template.id,
            stage="parsing",  # a plain string exercises the non-enum branch
            created_by=user_id,
        )

        assert run.stage == "parsing"
        assert run.parameters == {}


class TestLifecycle:
    async def test_start_complete_sequence(
        self,
        repo: ExtractionRunRepository,
        session: AsyncSession,
        article: Article,
        template: ProjectExtractionTemplate,
        user_id: UUID,
    ) -> None:
        run = await _run(session, article, template, user_id)
        before = datetime.now(UTC)

        started = await repo.start_run(run.id)
        assert started is not None
        assert started.id == run.id
        assert started.status == ExtractionRunStatus.RUNNING.value
        assert started.started_at is not None and started.started_at >= before

        completed = await repo.complete_run(run.id, {"suggestions": 3})
        assert completed is not None
        assert completed.status == ExtractionRunStatus.COMPLETED.value
        assert completed.results == {"suggestions": 3}
        assert completed.completed_at is not None
        assert completed.completed_at >= completed.started_at

    async def test_fail_run_records_error(
        self,
        repo: ExtractionRunRepository,
        session: AsyncSession,
        article: Article,
        template: ProjectExtractionTemplate,
        user_id: UUID,
    ) -> None:
        run = await _run(session, article, template, user_id, status="running")

        failed = await repo.fail_run(run.id, "OpenAI timeout")

        assert failed is not None
        assert failed.status == ExtractionRunStatus.FAILED.value
        assert failed.error_message == "OpenAI timeout"
        assert failed.completed_at is not None

    async def test_lifecycle_methods_return_none_for_unknown_run(
        self, repo: ExtractionRunRepository
    ) -> None:
        missing = uuid4()

        assert await repo.start_run(missing) is None
        assert await repo.complete_run(missing, {}) is None
        assert await repo.fail_run(missing, "boom") is None


class TestQueries:
    async def test_get_by_article_orders_newest_first_and_filters(
        self,
        repo: ExtractionRunRepository,
        session: AsyncSession,
        project: Project,
        article: Article,
        template: ProjectExtractionTemplate,
        user_id: UUID,
    ) -> None:
        other_article = await create_article(session, project.id)
        oldest = await _run(session, article, template, user_id, minute=1, status="completed")
        middle = await _run(session, article, template, user_id, minute=2, stage="parsing")
        newest = await _run(session, article, template, user_id, minute=3, status="failed")
        await _run(session, other_article, template, user_id, minute=4)

        all_runs = await repo.get_by_article(article.id)
        assert [r.id for r in all_runs] == [newest.id, middle.id, oldest.id]

        by_stage = await repo.get_by_article(article.id, stage=ExtractionRunStage.DATA_SUGGEST)
        assert [r.id for r in by_stage] == [newest.id, oldest.id]

        by_status = await repo.get_by_article(article.id, status=ExtractionRunStatus.COMPLETED)
        assert [r.id for r in by_status] == [oldest.id]

        combined = await repo.get_by_article(
            article.id, stage=ExtractionRunStage.PARSING, status=ExtractionRunStatus.FAILED
        )
        assert combined == []

    async def test_get_latest_by_article(
        self,
        repo: ExtractionRunRepository,
        session: AsyncSession,
        article: Article,
        template: ProjectExtractionTemplate,
        user_id: UUID,
    ) -> None:
        await _run(session, article, template, user_id, minute=1)
        latest = await _run(session, article, template, user_id, minute=5)
        await _run(session, article, template, user_id, minute=9, stage="parsing")

        found = await repo.get_latest_by_article(article.id, ExtractionRunStage.DATA_SUGGEST)

        assert found is latest
        assert await repo.get_latest_by_article(article.id, ExtractionRunStage.CONSENSUS) is None

    async def test_get_by_project_filters_status_and_limits(
        self,
        repo: ExtractionRunRepository,
        session: AsyncSession,
        project: Project,
        article: Article,
        template: ProjectExtractionTemplate,
        user_id: UUID,
    ) -> None:
        other_project = await create_project(session, user_id)
        other_article = await create_article(session, other_project.id)
        other_template = await create_project_template(session, other_project.id, user_id)
        runs = [
            await _run(session, article, template, user_id, minute=i, status=status)
            for i, status in enumerate(["completed", "failed", "completed"])
        ]
        await _run(session, other_article, other_template, user_id, minute=10)

        everything = await repo.get_by_project(project.id)
        assert [r.id for r in everything] == [r.id for r in reversed(runs)]

        completed = await repo.get_by_project(project.id, status=ExtractionRunStatus.COMPLETED)
        assert [r.id for r in completed] == [runs[2].id, runs[0].id]

        limited = await repo.get_by_project(project.id, limit=1)
        assert [r.id for r in limited] == [runs[2].id]
