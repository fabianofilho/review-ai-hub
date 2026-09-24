"""Integration tests for the extraction repositories."""

from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.article import Article
from app.models.extraction import (
    AISuggestion,
    ExtractedValue,
    ExtractionEntityType,
    ExtractionField,
    ExtractionInstance,
    ExtractionTemplateGlobal,
    ProjectExtractionTemplate,
)
from app.models.project import Project
from app.repositories.extraction_repository import (
    AISuggestionRepository,
    ExtractionEntityTypeRepository,
    ExtractionInstanceRepository,
    ExtractionTemplateRepository,
)
from tests.integration.repositories.factories import (
    add,
    create_article,
    create_entity_type,
    create_extraction_instance,
    create_project,
    create_project_template,
)


@pytest_asyncio.fixture
async def template(
    session: AsyncSession, project: Project, user_id: UUID
) -> ProjectExtractionTemplate:
    return await create_project_template(session, project.id, user_id)


@pytest_asyncio.fixture
async def entity_type(
    session: AsyncSession, template: ProjectExtractionTemplate
) -> ExtractionEntityType:
    return await create_entity_type(session, "prediction_model", project_template_id=template.id)


async def _field(session: AsyncSession, entity_type_id: UUID, name: str) -> ExtractionField:
    return await add(
        session,
        ExtractionField(entity_type_id=entity_type_id, name=name, label=name, field_type="text"),
    )


class TestExtractionTemplateRepository:
    async def test_get_by_project(
        self,
        session: AsyncSession,
        project: Project,
        user_id: UUID,
        template: ProjectExtractionTemplate,
    ) -> None:
        repo = ExtractionTemplateRepository(session)
        second = await create_project_template(session, project.id, user_id)
        other_project = await create_project(session, user_id)
        await create_project_template(session, other_project.id, user_id)

        result = await repo.get_by_project(str(project.id))

        assert {t.id for t in result} == {template.id, second.id}

    async def test_get_with_entity_types(
        self,
        session: AsyncSession,
        template: ProjectExtractionTemplate,
        entity_type: ExtractionEntityType,
    ) -> None:
        repo = ExtractionTemplateRepository(session)
        second = await create_entity_type(session, "outcome", project_template_id=template.id)

        loaded = await repo.get_with_entity_types(str(template.id))

        assert loaded is template
        assert {et.id for et in loaded.entity_types} == {entity_type.id, second.id}
        assert await repo.get_with_entity_types(uuid4()) is None


class TestExtractionEntityTypeRepository:
    @pytest.fixture
    def repo(self, session: AsyncSession) -> ExtractionEntityTypeRepository:
        return ExtractionEntityTypeRepository(session)

    async def test_get_by_template_for_project_template_is_sorted(
        self,
        repo: ExtractionEntityTypeRepository,
        session: AsyncSession,
        template: ProjectExtractionTemplate,
    ) -> None:
        third = await create_entity_type(
            session, "c_entity", project_template_id=template.id, sort_order=3
        )
        first = await create_entity_type(
            session, "a_entity", project_template_id=template.id, sort_order=1
        )
        second = await create_entity_type(
            session, "b_entity", project_template_id=template.id, sort_order=2
        )

        result = await repo.get_by_template(str(template.id))

        assert [et.id for et in result] == [first.id, second.id, third.id]

    async def test_get_by_template_for_global_template(
        self,
        repo: ExtractionEntityTypeRepository,
        session: AsyncSession,
        template: ProjectExtractionTemplate,
    ) -> None:
        global_template = await add(
            session, ExtractionTemplateGlobal(name="CHARMS", framework="CHARMS")
        )
        global_entity = await create_entity_type(
            session, "participants", template_id=global_template.id
        )
        await create_entity_type(session, "participants", project_template_id=template.id)

        result = await repo.get_by_template(global_template.id, is_project_template=False)
        assert [et.id for et in result] == [global_entity.id]

        # The same id looked up as a project template matches nothing.
        assert await repo.get_by_template(global_template.id) == []

    async def test_get_with_fields(
        self,
        repo: ExtractionEntityTypeRepository,
        session: AsyncSession,
        entity_type: ExtractionEntityType,
    ) -> None:
        fields = [await _field(session, entity_type.id, name) for name in ("auc", "n")]

        loaded = await repo.get_with_fields(str(entity_type.id))

        assert loaded is entity_type
        assert {f.id for f in loaded.fields} == {f.id for f in fields}
        assert await repo.get_with_fields(uuid4()) is None

    async def test_get_by_name_in_project_and_global_templates(
        self,
        repo: ExtractionEntityTypeRepository,
        session: AsyncSession,
        template: ProjectExtractionTemplate,
        entity_type: ExtractionEntityType,
    ) -> None:
        global_template = await add(
            session, ExtractionTemplateGlobal(name="CHARMS", framework="CHARMS")
        )
        global_entity = await create_entity_type(
            session, "prediction_model", template_id=global_template.id
        )

        assert await repo.get_by_name("prediction_model", str(template.id)) is entity_type
        assert (
            await repo.get_by_name(
                "prediction_model", global_template.id, is_project_template=False
            )
            is global_entity
        )
        assert await repo.get_by_name("unknown", template.id) is None

    async def test_get_children_filters_cardinality_and_loads_fields(
        self,
        repo: ExtractionEntityTypeRepository,
        session: AsyncSession,
        template: ProjectExtractionTemplate,
        entity_type: ExtractionEntityType,
    ) -> None:
        many_child = await create_entity_type(
            session,
            "predictors",
            project_template_id=template.id,
            parent_entity_type_id=entity_type.id,
            cardinality="many",
            sort_order=2,
        )
        one_child = await create_entity_type(
            session,
            "performance",
            project_template_id=template.id,
            parent_entity_type_id=entity_type.id,
            cardinality="one",
            sort_order=1,
        )
        await create_entity_type(session, "unrelated", project_template_id=template.id)
        field = await _field(session, many_child.id, "predictor_name")

        children = await repo.get_children(str(entity_type.id))
        assert [c.id for c in children] == [one_child.id, many_child.id]
        # Fields are eager loaded, so reading them needs no further IO.
        assert [f.id for f in children[1].fields] == [field.id]
        assert children[0].fields == []

        only_many = await repo.get_children(entity_type.id, cardinality="many")
        assert [c.id for c in only_many] == [many_child.id]


class TestExtractionInstanceRepository:
    @pytest.fixture
    def repo(self, session: AsyncSession) -> ExtractionInstanceRepository:
        return ExtractionInstanceRepository(session)

    async def test_get_by_article_sorts_and_filters_entity_type(
        self,
        repo: ExtractionInstanceRepository,
        session: AsyncSession,
        project: Project,
        article: Article,
        template: ProjectExtractionTemplate,
        entity_type: ExtractionEntityType,
        user_id: UUID,
    ) -> None:
        other_type = await create_entity_type(session, "outcome", project_template_id=template.id)
        other_article = await create_article(session, project.id)

        async def instance(type_id: UUID, sort_order: int, article_id: UUID) -> ExtractionInstance:
            return await create_extraction_instance(
                session,
                project.id,
                template.id,
                type_id,
                user_id,
                article_id=article_id,
                sort_order=sort_order,
            )

        second = await instance(entity_type.id, 2, article.id)
        first = await instance(entity_type.id, 1, article.id)
        outcome = await instance(other_type.id, 0, article.id)
        await instance(entity_type.id, 0, other_article.id)

        result = await repo.get_by_article(str(article.id))
        assert [i.id for i in result] == [outcome.id, first.id, second.id]

        filtered = await repo.get_by_article(article.id, entity_type_id=str(entity_type.id))
        assert [i.id for i in filtered] == [first.id, second.id]

    async def test_get_children_sorted(
        self,
        repo: ExtractionInstanceRepository,
        session: AsyncSession,
        project: Project,
        article: Article,
        template: ProjectExtractionTemplate,
        entity_type: ExtractionEntityType,
        user_id: UUID,
    ) -> None:
        parent = await create_extraction_instance(
            session, project.id, template.id, entity_type.id, user_id, article_id=article.id
        )
        children = [
            await create_extraction_instance(
                session,
                project.id,
                template.id,
                entity_type.id,
                user_id,
                article_id=article.id,
                parent_instance_id=parent.id,
                sort_order=order,
            )
            for order in (2, 1)
        ]

        result = await repo.get_children(str(parent.id))

        assert [c.id for c in result] == [children[1].id, children[0].id]
        assert await repo.get_children(children[0].id) == []

    async def test_get_with_values(
        self,
        repo: ExtractionInstanceRepository,
        session: AsyncSession,
        project: Project,
        article: Article,
        template: ProjectExtractionTemplate,
        entity_type: ExtractionEntityType,
        user_id: UUID,
    ) -> None:
        instance = await create_extraction_instance(
            session, project.id, template.id, entity_type.id, user_id, article_id=article.id
        )
        field = await _field(session, entity_type.id, "auc")
        value = await add(
            session,
            ExtractedValue(
                project_id=project.id,
                article_id=article.id,
                instance_id=instance.id,
                field_id=field.id,
                value={"value": 0.81},
                source="human",
            ),
        )

        loaded = await repo.get_with_values(str(instance.id))

        assert loaded is instance
        assert [v.id for v in loaded.values] == [value.id]
        assert await repo.get_with_values(uuid4()) is None


class TestAISuggestionRepository:
    @pytest.fixture
    def repo(self, session: AsyncSession) -> AISuggestionRepository:
        return AISuggestionRepository(session)

    async def _suggestion(
        self, session: AsyncSession, instance: ExtractionInstance, status: str
    ) -> AISuggestion:
        return await add(
            session,
            AISuggestion(instance_id=instance.id, suggested_value={"value": 1}, status=status),
        )

    async def test_get_by_instance_with_optional_status(
        self,
        repo: AISuggestionRepository,
        session: AsyncSession,
        project: Project,
        article: Article,
        template: ProjectExtractionTemplate,
        entity_type: ExtractionEntityType,
        user_id: UUID,
    ) -> None:
        instance = await create_extraction_instance(
            session, project.id, template.id, entity_type.id, user_id, article_id=article.id
        )
        other = await create_extraction_instance(
            session, project.id, template.id, entity_type.id, user_id, article_id=article.id
        )
        pending = await self._suggestion(session, instance, "pending")
        accepted = await self._suggestion(session, instance, "accepted")
        await self._suggestion(session, other, "pending")

        everything = await repo.get_by_instance(str(instance.id))
        assert {s.id for s in everything} == {pending.id, accepted.id}

        only_accepted = await repo.get_by_instance(instance.id, status="accepted")
        assert [s.id for s in only_accepted] == [accepted.id]

    async def test_get_pending_by_article(
        self,
        repo: AISuggestionRepository,
        session: AsyncSession,
        project: Project,
        article: Article,
        template: ProjectExtractionTemplate,
        entity_type: ExtractionEntityType,
        user_id: UUID,
    ) -> None:
        other_article = await create_article(session, project.id)
        instances = [
            await create_extraction_instance(
                session, project.id, template.id, entity_type.id, user_id, article_id=a_id
            )
            for a_id in (article.id, article.id, other_article.id)
        ]
        pending = [
            await self._suggestion(session, instances[0], "pending"),
            await self._suggestion(session, instances[1], "pending"),
        ]
        await self._suggestion(session, instances[0], "rejected")
        await self._suggestion(session, instances[2], "pending")

        result = await repo.get_pending_by_article(str(article.id))

        assert {s.id for s in result} == {s.id for s in pending}
