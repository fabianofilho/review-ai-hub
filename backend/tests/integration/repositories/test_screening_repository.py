"""Integration tests for the screening repositories."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.article import Article
from app.models.project import Project
from app.models.screening import ScreeningConfig, ScreeningConflict, ScreeningDecision, ScreeningRun
from app.repositories.screening_repository import (
    ScreeningConfigRepository,
    ScreeningConflictRepository,
    ScreeningDecisionRepository,
    ScreeningRunRepository,
)
from tests.integration.repositories.factories import add, create_article, create_user

TA = "title_abstract"
FT = "full_text"


async def _decision(
    session: AsyncSession,
    project: Project,
    article: Article,
    reviewer_id: UUID,
    decision: str,
    phase: str = TA,
) -> ScreeningDecision:
    return await add(
        session,
        ScreeningDecision(
            project_id=project.id,
            article_id=article.id,
            reviewer_id=reviewer_id,
            phase=phase,
            decision=decision,
        ),
    )


async def _conflict(
    session: AsyncSession,
    project: Project,
    article: Article,
    decisions: tuple[ScreeningDecision, ScreeningDecision],
    status: str = "conflict",
    phase: str = TA,
) -> ScreeningConflict:
    return await add(
        session,
        ScreeningConflict(
            project_id=project.id,
            article_id=article.id,
            phase=phase,
            decision_1_id=decisions[0].id,
            decision_2_id=decisions[1].id,
            status=status,
        ),
    )


class TestScreeningConfigRepository:
    async def test_get_by_project_and_phase(
        self, session: AsyncSession, project: Project, user_id: UUID
    ) -> None:
        repo = ScreeningConfigRepository(session)
        ta_config = await add(
            session, ScreeningConfig(project_id=project.id, phase=TA, created_by=user_id)
        )
        await add(session, ScreeningConfig(project_id=project.id, phase=FT, created_by=user_id))

        assert await repo.get_by_project_and_phase(project.id, TA) is ta_config

    async def test_get_by_project_and_phase_returns_none_when_missing(
        self, session: AsyncSession, project: Project
    ) -> None:
        repo = ScreeningConfigRepository(session)

        assert await repo.get_by_project_and_phase(project.id, FT) is None


class TestScreeningDecisionRepository:
    @pytest.fixture
    def repo(self, session: AsyncSession) -> ScreeningDecisionRepository:
        return ScreeningDecisionRepository(session)

    async def test_get_by_article_filters_article_and_phase(
        self,
        repo: ScreeningDecisionRepository,
        session: AsyncSession,
        project: Project,
        article: Article,
        user_id: UUID,
    ) -> None:
        second_reviewer = await create_user(session)
        other_article = await create_article(session, project.id)
        first = await _decision(session, project, article, user_id, "include")
        second = await _decision(session, project, article, second_reviewer, "exclude")
        await _decision(session, project, article, user_id, "include", phase=FT)
        await _decision(session, project, other_article, user_id, "maybe")

        result = await repo.get_by_article(project.id, article.id, TA)

        assert {d.id for d in result} == {first.id, second.id}

    async def test_get_by_reviewer_filters_reviewer_and_phase(
        self,
        repo: ScreeningDecisionRepository,
        session: AsyncSession,
        project: Project,
        article: Article,
        user_id: UUID,
    ) -> None:
        other_reviewer = await create_user(session)
        other_article = await create_article(session, project.id)
        mine = [
            await _decision(session, project, article, user_id, "include"),
            await _decision(session, project, other_article, user_id, "exclude"),
        ]
        await _decision(session, project, article, other_reviewer, "include")
        await _decision(session, project, article, user_id, "include", phase=FT)

        result = await repo.get_by_reviewer(project.id, user_id, TA)

        assert {d.id for d in result} == {d.id for d in mine}

    async def test_get_existing_decision(
        self,
        repo: ScreeningDecisionRepository,
        session: AsyncSession,
        project: Project,
        article: Article,
        user_id: UUID,
    ) -> None:
        decision = await _decision(session, project, article, user_id, "maybe")

        found = await repo.get_existing_decision(project.id, article.id, user_id, TA)
        assert found is decision
        assert await repo.get_existing_decision(project.id, article.id, user_id, FT) is None
        assert await repo.get_existing_decision(project.id, article.id, uuid4(), TA) is None

    async def test_count_by_decision_groups_values(
        self,
        repo: ScreeningDecisionRepository,
        session: AsyncSession,
        project: Project,
        user_id: UUID,
    ) -> None:
        reviewer_2 = await create_user(session)
        article_1 = await create_article(session, project.id)
        article_2 = await create_article(session, project.id)
        await _decision(session, project, article_1, user_id, "include")
        await _decision(session, project, article_1, reviewer_2, "include")
        await _decision(session, project, article_2, user_id, "exclude")
        await _decision(session, project, article_2, user_id, "maybe", phase=FT)

        assert await repo.count_by_decision(project.id, TA) == {"include": 2, "exclude": 1}
        assert await repo.count_by_decision(project.id, FT) == {"maybe": 1}

    async def test_count_by_decision_is_empty_without_decisions(
        self, repo: ScreeningDecisionRepository, project: Project
    ) -> None:
        assert await repo.count_by_decision(project.id, TA) == {}

    async def test_count_screened_articles_counts_distinct_articles(
        self,
        repo: ScreeningDecisionRepository,
        session: AsyncSession,
        project: Project,
        user_id: UUID,
    ) -> None:
        reviewer_2 = await create_user(session)
        article_1 = await create_article(session, project.id)
        article_2 = await create_article(session, project.id)
        await _decision(session, project, article_1, user_id, "include")
        await _decision(session, project, article_1, reviewer_2, "exclude")
        await _decision(session, project, article_2, user_id, "include")

        assert await repo.count_screened_articles(project.id, TA) == 2
        assert await repo.count_screened_articles(project.id, FT) == 0


class TestScreeningConflictRepository:
    @pytest.fixture
    def repo(self, session: AsyncSession) -> ScreeningConflictRepository:
        return ScreeningConflictRepository(session)

    async def _decision_pair(
        self, session: AsyncSession, project: Project, article: Article, phase: str = TA
    ) -> tuple[ScreeningDecision, ScreeningDecision]:
        reviewer_1 = await create_user(session)
        reviewer_2 = await create_user(session)
        return (
            await _decision(session, project, article, reviewer_1, "include", phase=phase),
            await _decision(session, project, article, reviewer_2, "exclude", phase=phase),
        )

    async def test_get_unresolved_and_count_unresolved(
        self,
        repo: ScreeningConflictRepository,
        session: AsyncSession,
        project: Project,
    ) -> None:
        open_articles = [await create_article(session, project.id) for _ in range(2)]
        resolved_article = await create_article(session, project.id)
        open_conflicts = [
            await _conflict(session, project, a, await self._decision_pair(session, project, a))
            for a in open_articles
        ]
        await _conflict(
            session,
            project,
            resolved_article,
            await self._decision_pair(session, project, resolved_article),
            status="resolved",
        )

        unresolved = await repo.get_unresolved(project.id, TA)

        assert {c.id for c in unresolved} == {c.id for c in open_conflicts}
        assert await repo.count_unresolved(project.id, TA) == 2
        assert await repo.get_unresolved(project.id, FT) == []
        assert await repo.count_unresolved(project.id, FT) == 0

    async def test_get_by_article(
        self,
        repo: ScreeningConflictRepository,
        session: AsyncSession,
        project: Project,
        article: Article,
    ) -> None:
        conflict = await _conflict(
            session, project, article, await self._decision_pair(session, project, article)
        )

        assert await repo.get_by_article(project.id, article.id, TA) is conflict
        assert await repo.get_by_article(project.id, article.id, FT) is None


class TestScreeningRunRepository:
    @pytest.fixture
    def repo(self, session: AsyncSession) -> ScreeningRunRepository:
        return ScreeningRunRepository(session)

    async def _stored(self, session: AsyncSession, run_id: UUID) -> ScreeningRun:
        result = await session.execute(
            select(ScreeningRun)
            .where(ScreeningRun.id == run_id)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one()

    async def test_create_run_starts_pending_with_defaults(
        self, repo: ScreeningRunRepository, project: Project, user_id: UUID
    ) -> None:
        run = await repo.create_run(project.id, TA, "ai_screening", user_id)

        assert run.id is not None
        assert run.status == "pending"
        assert run.parameters == {}
        assert run.results == {}
        assert run.created_at is not None

    async def test_create_run_keeps_parameters(
        self, repo: ScreeningRunRepository, project: Project, user_id: UUID
    ) -> None:
        run = await repo.create_run(
            project.id, FT, "ai_screening", user_id, parameters={"model": "gpt-4o-mini"}
        )

        assert run.phase == FT
        assert run.parameters == {"model": "gpt-4o-mini"}

    async def test_run_lifecycle_to_completed(
        self,
        repo: ScreeningRunRepository,
        session: AsyncSession,
        project: Project,
        user_id: UUID,
    ) -> None:
        run = await repo.create_run(project.id, TA, "ai_screening", user_id)
        before = datetime.now(UTC)

        started = await repo.start_run(run.id)
        assert started is run
        stored = await self._stored(session, run.id)
        assert stored.status == "running"
        assert stored.started_at is not None and stored.started_at >= before

        completed = await repo.complete_run(str(run.id), {"screened": 10})
        assert completed is run
        stored = await self._stored(session, run.id)
        assert stored.status == "completed"
        assert stored.results == {"screened": 10}
        assert stored.completed_at is not None and stored.completed_at >= stored.started_at

    async def test_fail_run_stores_error(
        self,
        repo: ScreeningRunRepository,
        session: AsyncSession,
        project: Project,
        user_id: UUID,
    ) -> None:
        run = await repo.create_run(project.id, TA, "ai_screening", user_id)

        failed = await repo.fail_run(run.id, "rate limited")

        assert failed is run
        stored = await self._stored(session, run.id)
        assert stored.status == "failed"
        assert stored.error_message == "rate limited"
        assert stored.completed_at is not None

    async def test_lifecycle_methods_return_none_for_unknown_run(
        self, repo: ScreeningRunRepository
    ) -> None:
        missing = uuid4()

        assert await repo.start_run(missing) is None
        assert await repo.complete_run(missing, {}) is None
        assert await repo.fail_run(missing, "boom") is None
