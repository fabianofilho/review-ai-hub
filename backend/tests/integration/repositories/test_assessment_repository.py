"""Integration tests for the assessment repositories."""

from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.article import Article
from app.models.assessment import (
    AIAssessment,
    AIAssessmentConfig,
    AIAssessmentPrompt,
    AIAssessmentRun,
    AssessmentEvidence,
    AssessmentInstance,
    AssessmentInstrument,
    AssessmentItem,
    AssessmentResponse,
    ProjectAssessmentInstrument,
    ProjectAssessmentItem,
)
from app.models.project import Project
from app.repositories.assessment_repository import (
    AIAssessmentConfigRepository,
    AIAssessmentPromptRepository,
    AIAssessmentRepository,
    AIAssessmentRunRepository,
    AssessmentEvidenceRepository,
    AssessmentInstanceRepository,
    AssessmentInstrumentRepository,
    AssessmentItemRepository,
    AssessmentResponseRepository,
    ProjectAssessmentInstrumentRepository,
    ProjectAssessmentItemRepository,
)
from tests.integration.repositories.factories import (
    add,
    at,
    create_article,
    create_assessment_instance,
    create_entity_type,
    create_extraction_instance,
    create_instrument,
    create_item,
    create_project,
    create_project_instrument,
    create_project_template,
    create_user,
)


@pytest_asyncio.fixture
async def instrument(session: AsyncSession) -> AssessmentInstrument:
    return await create_instrument(session)


@pytest_asyncio.fixture
async def item(session: AsyncSession, instrument: AssessmentInstrument) -> AssessmentItem:
    return await create_item(session, instrument.id, "1.1")


@pytest_asyncio.fixture
async def instance(
    session: AsyncSession,
    project: Project,
    article: Article,
    instrument: AssessmentInstrument,
    user_id: UUID,
) -> AssessmentInstance:
    return await create_assessment_instance(
        session, project.id, article.id, user_id, instrument_id=instrument.id
    )


@pytest_asyncio.fixture
async def project_instrument(
    session: AsyncSession, project: Project, user_id: UUID
) -> ProjectAssessmentInstrument:
    return await create_project_instrument(session, project.id, user_id)


# =================== GLOBAL INSTRUMENTS AND ITEMS ===================


class TestAssessmentInstrumentRepository:
    @pytest.fixture
    def repo(self, session: AsyncSession) -> AssessmentInstrumentRepository:
        return AssessmentInstrumentRepository(session)

    async def test_get_with_items_loads_items(
        self,
        repo: AssessmentInstrumentRepository,
        session: AsyncSession,
        instrument: AssessmentInstrument,
    ) -> None:
        items = [await create_item(session, instrument.id, code) for code in ("1.1", "1.2")]

        loaded = await repo.get_with_items(str(instrument.id))

        assert loaded is instrument
        assert {i.id for i in loaded.items} == {i.id for i in items}
        assert await repo.get_with_items(uuid4()) is None

    async def test_get_all_active_with_items_skips_inactive_and_orders_newest_first(
        self, repo: AssessmentInstrumentRepository, session: AsyncSession
    ) -> None:
        older = await create_instrument(session, created_at=at(1))
        newer = await create_instrument(session, created_at=at(2))
        inactive = await create_instrument(session, is_active=False, created_at=at(3))
        item = await create_item(session, newer.id, "1.1")

        result = await repo.get_all_active_with_items()

        ids = [i.id for i in result]
        assert inactive.id not in ids
        assert ids.index(newer.id) < ids.index(older.id)
        loaded_newer = result[ids.index(newer.id)]
        assert [i.id for i in loaded_newer.items] == [item.id]


class TestAssessmentItemRepository:
    @pytest.fixture
    def repo(self, session: AsyncSession) -> AssessmentItemRepository:
        return AssessmentItemRepository(session)

    async def test_get_by_instrument_sorted_by_sort_order(
        self,
        repo: AssessmentItemRepository,
        session: AsyncSession,
        instrument: AssessmentInstrument,
    ) -> None:
        other_instrument = await create_instrument(session)
        second = await create_item(session, instrument.id, "1.2", sort_order=2)
        first = await create_item(session, instrument.id, "1.1", sort_order=1)
        await create_item(session, other_instrument.id, "1.1")

        result = await repo.get_by_instrument(str(instrument.id))

        assert [i.id for i in result] == [first.id, second.id]

    async def test_get_item_with_levels(
        self, repo: AssessmentItemRepository, item: AssessmentItem
    ) -> None:
        found = await repo.get_item_with_levels(str(item.id))

        assert found is item
        assert found.allowed_levels == ["low", "high", "unclear"]
        assert await repo.get_item_with_levels(uuid4()) is None


# =================== AI ASSESSMENTS ===================


class TestAIAssessmentRepository:
    @pytest.fixture
    def repo(self, session: AsyncSession) -> AIAssessmentRepository:
        return AIAssessmentRepository(session)

    async def _ai_assessment(
        self,
        session: AsyncSession,
        article: Article,
        item: AssessmentItem,
        user_id: UUID,
        *,
        minute: int = 0,
        status: str = "pending_review",
    ) -> AIAssessment:
        return await add(
            session,
            AIAssessment(
                project_id=article.project_id,
                article_id=article.id,
                assessment_item_id=item.id,
                instrument_id=item.instrument_id,
                user_id=user_id,
                selected_level="low",
                justification="Clear eligibility criteria.",
                ai_model_used="gpt-4o-mini",
                status=status,
                created_at=at(minute),
            ),
        )

    async def test_get_by_article_and_item_returns_latest(
        self,
        repo: AIAssessmentRepository,
        session: AsyncSession,
        article: Article,
        item: AssessmentItem,
        user_id: UUID,
    ) -> None:
        await self._ai_assessment(session, article, item, user_id, minute=1)
        latest = await self._ai_assessment(session, article, item, user_id, minute=5)
        other_item = await create_item(session, item.instrument_id, "9.9")
        await self._ai_assessment(session, article, other_item, user_id, minute=9)

        found = await repo.get_by_article_and_item(str(article.id), str(item.id))

        assert found is latest
        assert await repo.get_by_article_and_item(article.id, uuid4()) is None

    async def test_get_by_article_orders_newest_first(
        self,
        repo: AIAssessmentRepository,
        session: AsyncSession,
        project: Project,
        article: Article,
        item: AssessmentItem,
        user_id: UUID,
    ) -> None:
        older = await self._ai_assessment(session, article, item, user_id, minute=1)
        newer = await self._ai_assessment(session, article, item, user_id, minute=2)
        other_article = await create_article(session, project.id)
        await self._ai_assessment(session, other_article, item, user_id)

        result = await repo.get_by_article(str(article.id))

        assert [a.id for a in result] == [newer.id, older.id]

    async def test_get_pending_review_filters_status_and_project(
        self,
        repo: AIAssessmentRepository,
        session: AsyncSession,
        project: Project,
        article: Article,
        item: AssessmentItem,
        user_id: UUID,
    ) -> None:
        pending = await self._ai_assessment(session, article, item, user_id)
        await self._ai_assessment(session, article, item, user_id, status="accepted")
        other_project = await create_project(session, user_id)
        other_article = await create_article(session, other_project.id)
        await self._ai_assessment(session, other_article, item, user_id)

        result = await repo.get_pending_review(str(project.id))

        assert [a.id for a in result] == [pending.id]


class TestAIAssessmentRunRepository:
    @pytest.fixture
    def repo(self, session: AsyncSession) -> AIAssessmentRunRepository:
        return AIAssessmentRunRepository(session)

    async def test_create_run_for_global_instrument(
        self,
        repo: AIAssessmentRunRepository,
        session: AsyncSession,
        project: Project,
        article: Article,
        instrument: AssessmentInstrument,
        user_id: UUID,
    ) -> None:
        template = await create_project_template(session, project.id, user_id)
        entity_type = await create_entity_type(session, "model", project_template_id=template.id)
        extraction_instance = await create_extraction_instance(
            session, project.id, template.id, entity_type.id, user_id, article_id=article.id
        )

        run = await repo.create_run(
            project_id=project.id,
            article_id=article.id,
            instrument_id=instrument.id,
            created_by=user_id,
            stage="assess_single",
            parameters={"model": "gpt-4o"},
            extraction_instance_id=extraction_instance.id,
        )

        assert run.id is not None
        assert run.status == "pending"
        assert run.instrument_id == instrument.id
        assert run.project_instrument_id is None
        assert run.extraction_instance_id == extraction_instance.id
        assert run.parameters == {"model": "gpt-4o"}
        assert run.created_at is not None

    async def test_create_run_for_project_instrument(
        self,
        repo: AIAssessmentRunRepository,
        project: Project,
        article: Article,
        project_instrument: ProjectAssessmentInstrument,
        user_id: UUID,
    ) -> None:
        run = await repo.create_run(
            project_id=project.id,
            article_id=article.id,
            instrument_id=project_instrument.id,
            created_by=user_id,
            stage="assess_batch",
            parameters={},
            is_project_instrument=True,
        )

        assert run.instrument_id is None
        assert run.project_instrument_id == project_instrument.id
        assert run.extraction_instance_id is None
        assert run.stage == "assess_batch"

    async def test_run_lifecycle_updates_status_and_timestamps(
        self,
        repo: AIAssessmentRunRepository,
        session: AsyncSession,
        project: Project,
        article: Article,
        instrument: AssessmentInstrument,
        user_id: UUID,
    ) -> None:
        run = await repo.create_run(
            project.id, article.id, instrument.id, user_id, "assess_single", {}
        )

        await repo.start_run(run.id)
        await session.refresh(run)
        assert run.status == "running"
        assert run.started_at is not None
        assert run.completed_at is None

        await repo.complete_run(run.id, {"tokens": 120})
        await session.refresh(run)
        assert run.status == "completed"
        assert run.results == {"tokens": 120}
        assert run.completed_at is not None

    async def test_fail_run_stores_error(
        self,
        repo: AIAssessmentRunRepository,
        session: AsyncSession,
        project: Project,
        article: Article,
        instrument: AssessmentInstrument,
        user_id: UUID,
    ) -> None:
        run = await repo.create_run(
            project.id, article.id, instrument.id, user_id, "assess_single", {}
        )

        await repo.fail_run(run.id, "PDF not found")
        await session.refresh(run)

        assert run.status == "failed"
        assert run.error_message == "PDF not found"
        assert run.completed_at is not None

    async def test_get_by_project_orders_newest_first_and_filters_status(
        self,
        repo: AIAssessmentRunRepository,
        session: AsyncSession,
        project: Project,
        article: Article,
        instrument: AssessmentInstrument,
        user_id: UUID,
    ) -> None:
        def run(minute: int, status: str, project_id: UUID, article_id: UUID) -> AIAssessmentRun:
            return AIAssessmentRun(
                project_id=project_id,
                article_id=article_id,
                instrument_id=instrument.id,
                stage="assess_single",
                status=status,
                created_by=user_id,
                created_at=at(minute),
            )

        older = await add(session, run(1, "completed", project.id, article.id))
        newer = await add(session, run(2, "failed", project.id, article.id))
        other_project = await create_project(session, user_id)
        other_article = await create_article(session, other_project.id)
        await add(session, run(3, "completed", other_project.id, other_article.id))

        everything = await repo.get_by_project(project.id)
        assert [r.id for r in everything] == [newer.id, older.id]

        completed = await repo.get_by_project(project.id, status="completed")
        assert [r.id for r in completed] == [older.id]


class TestAIAssessmentConfigRepository:
    @pytest.fixture
    def repo(self, session: AsyncSession) -> AIAssessmentConfigRepository:
        return AIAssessmentConfigRepository(session)

    async def _config(
        self,
        session: AsyncSession,
        project_id: UUID,
        minute: int,
        *,
        instrument_id: UUID | None = None,
        is_active: bool = True,
    ) -> AIAssessmentConfig:
        return await add(
            session,
            AIAssessmentConfig(
                project_id=project_id,
                instrument_id=instrument_id,
                is_active=is_active,
                created_at=at(minute),
            ),
        )

    async def test_get_active_returns_newest_active_config(
        self,
        repo: AIAssessmentConfigRepository,
        session: AsyncSession,
        project: Project,
        user_id: UUID,
    ) -> None:
        await self._config(session, project.id, 1)
        newest_active = await self._config(session, project.id, 2)
        await self._config(session, project.id, 3, is_active=False)
        other_project = await create_project(session, user_id)
        await self._config(session, other_project.id, 4)

        assert await repo.get_active(project.id) is newest_active

    async def test_get_active_filters_by_instrument(
        self,
        repo: AIAssessmentConfigRepository,
        session: AsyncSession,
        project: Project,
        instrument: AssessmentInstrument,
    ) -> None:
        for_instrument = await self._config(session, project.id, 1, instrument_id=instrument.id)
        await self._config(session, project.id, 2)

        assert await repo.get_active(project.id, instrument.id) is for_instrument
        assert await repo.get_active(project.id, uuid4()) is None

    async def test_get_active_returns_none_without_configs(
        self, repo: AIAssessmentConfigRepository, project: Project
    ) -> None:
        assert await repo.get_active(project.id) is None


class TestAIAssessmentPromptRepository:
    @pytest.fixture
    def repo(self, session: AsyncSession) -> AIAssessmentPromptRepository:
        return AIAssessmentPromptRepository(session)

    async def test_get_by_item(
        self, repo: AIAssessmentPromptRepository, session: AsyncSession, item: AssessmentItem
    ) -> None:
        prompt = await add(
            session,
            AIAssessmentPrompt(
                assessment_item_id=item.id,
                system_prompt="custom system",
                user_prompt_template="custom {{question}}",
            ),
        )

        assert await repo.get_by_item(item.id) is prompt
        assert await repo.get_by_item(uuid4()) is None

    async def test_get_or_create_default_returns_existing_prompt(
        self, repo: AIAssessmentPromptRepository, session: AsyncSession, item: AssessmentItem
    ) -> None:
        existing = await add(
            session, AIAssessmentPrompt(assessment_item_id=item.id, system_prompt="kept")
        )

        prompt = await repo.get_or_create_default(item.id)

        assert prompt is existing
        assert prompt.system_prompt == "kept"

    async def test_get_or_create_default_creates_prompt_with_defaults(
        self, repo: AIAssessmentPromptRepository, item: AssessmentItem
    ) -> None:
        prompt = await repo.get_or_create_default(item.id)

        assert prompt.id is not None
        assert prompt.assessment_item_id == item.id
        assert prompt.system_prompt.startswith("You are an expert research quality assessor")
        assert "{{question}}" in prompt.user_prompt_template
        assert await repo.get_by_item(item.id) is prompt


# =================== ASSESSMENT INSTANCES, RESPONSES, EVIDENCE ===================


class TestAssessmentInstanceRepository:
    @pytest.fixture
    def repo(self, session: AsyncSession) -> AssessmentInstanceRepository:
        return AssessmentInstanceRepository(session)

    async def test_get_by_article_orders_newest_first_and_filters_instrument(
        self,
        repo: AssessmentInstanceRepository,
        session: AsyncSession,
        project: Project,
        article: Article,
        instrument: AssessmentInstrument,
        user_id: UUID,
    ) -> None:
        other_instrument = await create_instrument(session)
        # Root instances are unique per (project, article, reviewer).
        second_reviewer = await create_user(session)
        older = await create_assessment_instance(
            session, project.id, article.id, user_id, instrument_id=instrument.id, created_at=at(1)
        )
        newer = await create_assessment_instance(
            session,
            project.id,
            article.id,
            second_reviewer,
            instrument_id=other_instrument.id,
            created_at=at(2),
        )
        other_article = await create_article(session, project.id)
        await create_assessment_instance(
            session, project.id, other_article.id, user_id, instrument_id=instrument.id
        )

        everything = await repo.get_by_article(str(article.id))
        assert [i.id for i in everything] == [newer.id, older.id]

        filtered = await repo.get_by_article(article.id, instrument_id=str(instrument.id))
        assert [i.id for i in filtered] == [older.id]

    async def test_get_by_extraction_instance(
        self,
        repo: AssessmentInstanceRepository,
        session: AsyncSession,
        project: Project,
        article: Article,
        instrument: AssessmentInstrument,
        user_id: UUID,
    ) -> None:
        template = await create_project_template(session, project.id, user_id)
        entity_type = await create_entity_type(session, "model", project_template_id=template.id)
        model_a, model_b = [
            await create_extraction_instance(
                session, project.id, template.id, entity_type.id, user_id, article_id=article.id
            )
            for _ in range(2)
        ]
        probast_a = await create_assessment_instance(
            session,
            project.id,
            article.id,
            user_id,
            instrument_id=instrument.id,
            extraction_instance_id=model_a.id,
        )
        await create_assessment_instance(
            session,
            project.id,
            article.id,
            await create_user(session),
            instrument_id=instrument.id,
            extraction_instance_id=model_b.id,
        )

        result = await repo.get_by_extraction_instance(str(model_a.id))

        assert [i.id for i in result] == [probast_a.id]

    async def test_get_with_responses_loads_responses(
        self,
        repo: AssessmentInstanceRepository,
        session: AsyncSession,
        instance: AssessmentInstance,
        item: AssessmentItem,
        user_id: UUID,
    ) -> None:
        response = await add(
            session,
            AssessmentResponse(
                project_id=instance.project_id,
                article_id=instance.article_id,
                assessment_instance_id=instance.id,
                assessment_item_id=item.id,
                selected_level="low",
                reviewer_id=user_id,
            ),
        )

        loaded = await repo.get_with_responses(str(instance.id))

        assert loaded is instance
        assert [r.id for r in loaded.responses] == [response.id]
        assert await repo.get_with_responses(uuid4()) is None

    async def test_get_children_orders_oldest_first(
        self,
        repo: AssessmentInstanceRepository,
        session: AsyncSession,
        instance: AssessmentInstance,
        user_id: UUID,
    ) -> None:
        def child(label: str, minute: int) -> AssessmentInstance:
            return AssessmentInstance(
                project_id=instance.project_id,
                article_id=instance.article_id,
                instrument_id=instance.instrument_id,
                parent_instance_id=instance.id,
                reviewer_id=user_id,
                label=label,
                created_at=at(minute),
            )

        later = await add(session, child("Domain 2", 2))
        earlier = await add(session, child("Domain 1", 1))

        result = await repo.get_children(str(instance.id))

        assert [c.id for c in result] == [earlier.id, later.id]
        assert await repo.get_children(earlier.id) == []

    async def test_get_by_project_and_reviewer(
        self,
        repo: AssessmentInstanceRepository,
        session: AsyncSession,
        project: Project,
        article: Article,
        user_id: UUID,
    ) -> None:
        other_reviewer = await create_user(session)
        second_article = await create_article(session, project.id)
        submitted = await create_assessment_instance(
            session, project.id, article.id, user_id, status="submitted", updated_at=at(1)
        )
        in_progress = await create_assessment_instance(
            session, project.id, second_article.id, user_id, updated_at=at(2)
        )
        await create_assessment_instance(session, project.id, article.id, other_reviewer)

        mine = await repo.get_by_project_and_reviewer(str(project.id), str(user_id))
        assert [i.id for i in mine] == [in_progress.id, submitted.id]

        only_submitted = await repo.get_by_project_and_reviewer(
            project.id, user_id, status="submitted"
        )
        assert [i.id for i in only_submitted] == [submitted.id]


class TestAssessmentResponseRepository:
    @pytest.fixture
    def repo(self, session: AsyncSession) -> AssessmentResponseRepository:
        return AssessmentResponseRepository(session)

    def _response(
        self,
        instance: AssessmentInstance,
        item: AssessmentItem,
        reviewer_id: UUID,
        *,
        level: str = "low",
        minute: int = 0,
    ) -> AssessmentResponse:
        return AssessmentResponse(
            project_id=instance.project_id,
            article_id=instance.article_id,
            assessment_instance_id=instance.id,
            assessment_item_id=item.id,
            selected_level=level,
            reviewer_id=reviewer_id,
            created_at=at(minute),
        )

    async def test_get_by_instance_orders_oldest_first(
        self,
        repo: AssessmentResponseRepository,
        session: AsyncSession,
        instance: AssessmentInstance,
        instrument: AssessmentInstrument,
        item: AssessmentItem,
        user_id: UUID,
    ) -> None:
        item_2 = await create_item(session, instrument.id, "1.2")
        later = await add(session, self._response(instance, item_2, user_id, minute=2))
        earlier = await add(session, self._response(instance, item, user_id, minute=1))

        result = await repo.get_by_instance(str(instance.id))

        assert [r.id for r in result] == [earlier.id, later.id]

    async def test_get_by_instance_and_item(
        self,
        repo: AssessmentResponseRepository,
        session: AsyncSession,
        instance: AssessmentInstance,
        item: AssessmentItem,
        user_id: UUID,
    ) -> None:
        response = await add(session, self._response(instance, item, user_id))

        assert await repo.get_by_instance_and_item(str(instance.id), str(item.id)) is response
        assert await repo.get_by_instance_and_item(instance.id, uuid4()) is None

    async def test_get_by_article_with_optional_reviewer(
        self,
        repo: AssessmentResponseRepository,
        session: AsyncSession,
        project: Project,
        article: Article,
        instance: AssessmentInstance,
        instrument: AssessmentInstrument,
        item: AssessmentItem,
        user_id: UUID,
    ) -> None:
        other_reviewer = await create_user(session)
        other_instance = await create_assessment_instance(
            session, project.id, article.id, other_reviewer, instrument_id=instrument.id
        )
        mine = await add(session, self._response(instance, item, user_id, minute=1))
        theirs = await add(session, self._response(other_instance, item, other_reviewer, minute=2))

        everything = await repo.get_by_article(str(article.id))
        assert [r.id for r in everything] == [theirs.id, mine.id]

        filtered = await repo.get_by_article(article.id, reviewer_id=str(user_id))
        assert [r.id for r in filtered] == [mine.id]

    async def test_get_by_level_with_optional_instrument_filter(
        self,
        repo: AssessmentResponseRepository,
        session: AsyncSession,
        project: Project,
        article: Article,
        instance: AssessmentInstance,
        item: AssessmentItem,
        user_id: UUID,
    ) -> None:
        other_instrument = await create_instrument(session)
        other_item = await create_item(session, other_instrument.id, "2.1")
        other_instance = await create_assessment_instance(
            session,
            project.id,
            article.id,
            await create_user(session),
            instrument_id=other_instrument.id,
        )
        high_here = await add(
            session, self._response(instance, item, user_id, level="high", minute=1)
        )
        high_there = await add(
            session, self._response(other_instance, other_item, user_id, level="high", minute=2)
        )
        low_item = await create_item(session, item.instrument_id, "1.9")
        await add(session, self._response(instance, low_item, user_id, level="low"))
        other_project = await create_project(session, user_id)
        foreign_instance = await create_assessment_instance(
            session,
            other_project.id,
            (await create_article(session, other_project.id)).id,
            user_id,
            instrument_id=item.instrument_id,
        )
        await add(session, self._response(foreign_instance, item, user_id, level="high"))

        all_high = await repo.get_by_level(str(project.id), "high")
        assert [r.id for r in all_high] == [high_there.id, high_here.id]

        high_for_instrument = await repo.get_by_level(
            project.id, "high", instrument_id=str(item.instrument_id)
        )
        assert [r.id for r in high_for_instrument] == [high_here.id]

    async def test_bulk_create_persists_all_responses(
        self,
        repo: AssessmentResponseRepository,
        session: AsyncSession,
        instance: AssessmentInstance,
        instrument: AssessmentInstrument,
        user_id: UUID,
    ) -> None:
        items = [await create_item(session, instrument.id, code) for code in ("3.1", "3.2")]
        responses = [
            AssessmentResponse(
                project_id=instance.project_id,
                article_id=instance.article_id,
                assessment_instance_id=instance.id,
                assessment_item_id=i.id,
                selected_level="unclear",
                reviewer_id=user_id,
                source="ai",
            )
            for i in items
        ]

        created = await repo.bulk_create(responses)

        assert created == responses
        assert all(r.id is not None and r.created_at is not None for r in created)
        stored = await repo.get_by_instance(instance.id)
        assert {r.id for r in stored} == {r.id for r in responses}
        assert {r.source for r in stored} == {"ai"}


class TestAssessmentEvidenceRepository:
    @pytest.fixture
    def repo(self, session: AsyncSession) -> AssessmentEvidenceRepository:
        return AssessmentEvidenceRepository(session)

    def _evidence(
        self, target_type: str, target_id: UUID, article: Article, user_id: UUID, minute: int = 0
    ) -> AssessmentEvidence:
        return AssessmentEvidence(
            project_id=article.project_id,
            article_id=article.id,
            target_type=target_type,
            target_id=target_id,
            text_content=f"Evidence for {target_type}",
            page_number=1,
            created_by=user_id,
            created_at=at(minute),
        )

    async def test_get_by_response_and_instance_use_target_type(
        self,
        repo: AssessmentEvidenceRepository,
        session: AsyncSession,
        article: Article,
        user_id: UUID,
    ) -> None:
        # The same target id under both types proves the target_type filter is applied.
        target_id = uuid4()
        for_response = await add(session, self._evidence("response", target_id, article, user_id))
        for_instance = await add(session, self._evidence("instance", target_id, article, user_id))

        by_response = await repo.get_by_response(str(target_id))
        assert [e.id for e in by_response] == [for_response.id]

        by_instance = await repo.get_by_instance(str(target_id))
        assert [e.id for e in by_instance] == [for_instance.id]

        assert await repo.get_by_response(uuid4()) == []

    async def test_get_by_article_orders_newest_first(
        self,
        repo: AssessmentEvidenceRepository,
        session: AsyncSession,
        project: Project,
        article: Article,
        user_id: UUID,
    ) -> None:
        older = await add(session, self._evidence("response", uuid4(), article, user_id, 1))
        newer = await add(session, self._evidence("instance", uuid4(), article, user_id, 2))
        other_article = await create_article(session, project.id)
        await add(session, self._evidence("response", uuid4(), other_article, user_id))

        result = await repo.get_by_article(str(article.id))

        assert [e.id for e in result] == [newer.id, older.id]


# =================== PROJECT INSTRUMENTS AND ITEMS ===================


class TestProjectAssessmentInstrumentRepository:
    @pytest.fixture
    def repo(self, session: AsyncSession) -> ProjectAssessmentInstrumentRepository:
        return ProjectAssessmentInstrumentRepository(session)

    async def test_get_by_project_active_only_by_default(
        self,
        repo: ProjectAssessmentInstrumentRepository,
        session: AsyncSession,
        project: Project,
        user_id: UUID,
    ) -> None:
        older = await create_project_instrument(session, project.id, user_id, created_at=at(1))
        newer = await create_project_instrument(session, project.id, user_id, created_at=at(2))
        inactive = await create_project_instrument(
            session, project.id, user_id, is_active=False, created_at=at(3)
        )
        other_project = await create_project(session, user_id)
        await create_project_instrument(session, other_project.id, user_id)

        active = await repo.get_by_project(str(project.id))
        assert [i.id for i in active] == [newer.id, older.id]
        # Items are eager loaded.
        assert active[0].items == []

        everything = await repo.get_by_project(project.id, active_only=False)
        assert [i.id for i in everything] == [inactive.id, newer.id, older.id]

    async def test_get_with_items(
        self,
        repo: ProjectAssessmentInstrumentRepository,
        session: AsyncSession,
        project_instrument: ProjectAssessmentInstrument,
    ) -> None:
        item = await add(
            session,
            ProjectAssessmentItem(
                project_instrument_id=project_instrument.id,
                domain="participants",
                item_code="1.1",
                question="Appropriate data sources?",
                allowed_levels=["yes", "no"],
            ),
        )

        loaded = await repo.get_with_items(str(project_instrument.id))

        assert loaded is project_instrument
        assert [i.id for i in loaded.items] == [item.id]
        assert await repo.get_with_items(uuid4()) is None

    async def test_get_by_tool_type_returns_newest_active(
        self,
        repo: ProjectAssessmentInstrumentRepository,
        session: AsyncSession,
        project: Project,
        user_id: UUID,
    ) -> None:
        await create_project_instrument(
            session, project.id, user_id, tool_type="ROBIS", created_at=at(1)
        )
        newest = await create_project_instrument(
            session, project.id, user_id, tool_type="ROBIS", created_at=at(2)
        )
        await create_project_instrument(
            session, project.id, user_id, tool_type="ROBIS", is_active=False, created_at=at(3)
        )

        assert await repo.get_by_tool_type(str(project.id), "ROBIS") is newest
        assert await repo.get_by_tool_type(project.id, "CUSTOM") is None

    async def test_get_by_global_instrument(
        self,
        repo: ProjectAssessmentInstrumentRepository,
        session: AsyncSession,
        project: Project,
        instrument: AssessmentInstrument,
        user_id: UUID,
    ) -> None:
        clone = await create_project_instrument(
            session, project.id, user_id, global_instrument_id=instrument.id
        )
        other_project = await create_project(session, user_id)
        await create_project_instrument(
            session, other_project.id, user_id, global_instrument_id=instrument.id
        )

        found = await repo.get_by_global_instrument(str(project.id), str(instrument.id))

        assert found is clone
        assert await repo.get_by_global_instrument(project.id, uuid4()) is None


class TestProjectAssessmentItemRepository:
    @pytest.fixture
    def repo(self, session: AsyncSession) -> ProjectAssessmentItemRepository:
        return ProjectAssessmentItemRepository(session)

    def _item(
        self,
        project_instrument: ProjectAssessmentInstrument,
        item_code: str,
        *,
        domain: str = "participants",
        sort_order: int = 0,
    ) -> ProjectAssessmentItem:
        return ProjectAssessmentItem(
            project_instrument_id=project_instrument.id,
            domain=domain,
            item_code=item_code,
            question=f"Question {item_code}?",
            sort_order=sort_order,
            allowed_levels=["yes", "no", "unclear"],
        )

    async def test_get_by_instrument_sorted(
        self,
        repo: ProjectAssessmentItemRepository,
        session: AsyncSession,
        project: Project,
        user_id: UUID,
        project_instrument: ProjectAssessmentInstrument,
    ) -> None:
        other_instrument = await create_project_instrument(session, project.id, user_id)
        second = await add(session, self._item(project_instrument, "1.2", sort_order=2))
        first = await add(session, self._item(project_instrument, "1.1", sort_order=1))
        await add(session, self._item(other_instrument, "1.1"))

        result = await repo.get_by_instrument(str(project_instrument.id))

        assert [i.id for i in result] == [first.id, second.id]

    async def test_get_by_domain(
        self,
        repo: ProjectAssessmentItemRepository,
        session: AsyncSession,
        project_instrument: ProjectAssessmentInstrument,
    ) -> None:
        predictors_2 = await add(
            session, self._item(project_instrument, "2.2", domain="predictors", sort_order=2)
        )
        predictors_1 = await add(
            session, self._item(project_instrument, "2.1", domain="predictors", sort_order=1)
        )
        await add(session, self._item(project_instrument, "1.1", domain="participants"))

        result = await repo.get_by_domain(str(project_instrument.id), "predictors")

        assert [i.id for i in result] == [predictors_1.id, predictors_2.id]
        assert await repo.get_by_domain(project_instrument.id, "analysis") == []

    async def test_get_by_item_code(
        self,
        repo: ProjectAssessmentItemRepository,
        session: AsyncSession,
        project_instrument: ProjectAssessmentInstrument,
    ) -> None:
        item = await add(session, self._item(project_instrument, "4.1"))

        assert await repo.get_by_item_code(str(project_instrument.id), "4.1") is item
        assert await repo.get_by_item_code(project_instrument.id, "9.9") is None

    async def test_bulk_create_persists_items(
        self,
        repo: ProjectAssessmentItemRepository,
        project_instrument: ProjectAssessmentInstrument,
    ) -> None:
        items = [self._item(project_instrument, code, sort_order=n) for n, code in enumerate("ab")]

        created = await repo.bulk_create(items)

        assert created == items
        assert all(i.id is not None for i in created)
        # updated_at is a server default, so it is only loaded by the refresh.
        assert all(i.updated_at is not None for i in created)
        stored = await repo.get_by_instrument(project_instrument.id)
        assert [i.item_code for i in stored] == ["a", "b"]
