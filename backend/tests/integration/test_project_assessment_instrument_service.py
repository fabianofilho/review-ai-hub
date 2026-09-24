"""
Integration tests for ProjectAssessmentInstrumentService.

The service runs against the real database session (db_session fixture). Each test
seeds its own auth user (the handle_new_user trigger creates the profile), project
and global instruments on a separate connection, and removes them afterwards, so
tests are independent and leave no rows behind.
"""

import json
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, create_async_engine

from app.core.config import settings
from app.schemas.assessment import (
    ProjectAssessmentInstrumentCreate,
    ProjectAssessmentInstrumentUpdate,
    ProjectAssessmentItemCreate,
    ProjectAssessmentItemUpdate,
)
from app.services.project_assessment_instrument_service import (
    ProjectAssessmentInstrumentService,
)

LEVELS = ["low", "high", "unclear"]


@dataclass
class GlobalItemRow:
    id: uuid.UUID
    domain: str
    item_code: str
    question: str
    sort_order: int
    required: bool
    description: str | None = None
    llm_prompt: str | None = None


@dataclass
class Seed:
    user_id: uuid.UUID
    project_id: uuid.UUID
    other_project_id: uuid.UUID
    global_id: uuid.UUID
    bare_global_id: uuid.UUID
    inactive_global_id: uuid.UUID
    global_items: list[GlobalItemRow] = field(default_factory=list)


async def _insert_global_instrument(
    conn: AsyncConnection,
    *,
    tool_type: str,
    name: str,
    is_active: bool = True,
    schema: dict[str, Any] | None = None,
    aggregation_rules: dict[str, Any] | None = None,
    target_mode: str = "per_article",
) -> uuid.UUID:
    instrument_id = uuid.uuid4()
    await conn.execute(
        text(
            """
            INSERT INTO assessment_instruments
                (id, tool_type, name, version, mode, target_mode, is_active,
                 aggregation_rules, schema)
            VALUES
                (:id, :tool_type, :name, '2.0.0', 'hybrid', :target_mode, :is_active,
                 CAST(:aggregation_rules AS jsonb), CAST(:schema AS jsonb))
            """
        ),
        {
            "id": instrument_id,
            "tool_type": tool_type,
            "name": name,
            "target_mode": target_mode,
            "is_active": is_active,
            "aggregation_rules": json.dumps(aggregation_rules) if aggregation_rules else None,
            "schema": json.dumps(schema) if schema else None,
        },
    )
    return instrument_id


async def _insert_global_item(
    conn: AsyncConnection, instrument_id: uuid.UUID, row: GlobalItemRow
) -> None:
    await conn.execute(
        text(
            """
            INSERT INTO assessment_items
                (id, instrument_id, domain, item_code, question, description,
                 sort_order, required, allowed_levels, llm_prompt)
            VALUES
                (:id, :instrument_id, :domain, :item_code, :question, :description,
                 :sort_order, :required, CAST(:allowed_levels AS jsonb), :llm_prompt)
            """
        ),
        {
            "id": row.id,
            "instrument_id": instrument_id,
            "domain": row.domain,
            "item_code": row.item_code,
            "question": row.question,
            "description": row.description,
            "sort_order": row.sort_order,
            "required": row.required,
            "allowed_levels": json.dumps(LEVELS),
            "llm_prompt": row.llm_prompt,
        },
    )


@pytest_asyncio.fixture
async def seed_engine() -> AsyncGenerator[AsyncEngine, None]:
    engine = create_async_engine(settings.async_database_url)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def seed(db_session: AsyncSession, seed_engine: AsyncEngine) -> AsyncGenerator[Seed, None]:
    suffix = uuid.uuid4().hex[:8]
    user_id = uuid.uuid4()
    project_id = uuid.uuid4()
    other_project_id = uuid.uuid4()
    # Inserted out of sort order on purpose, to check that listings sort items.
    global_items = [
        GlobalItemRow(
            id=uuid.uuid4(),
            domain="Analysis",
            item_code="4.1",
            question="Were there enough participants?",
            sort_order=2,
            required=False,
            llm_prompt="Check the sample size.",
        ),
        GlobalItemRow(
            id=uuid.uuid4(),
            domain="Participants",
            item_code="1.1",
            question="Were appropriate data sources used?",
            sort_order=0,
            required=True,
            description="Cohort, RCT or registry data.",
        ),
        GlobalItemRow(
            id=uuid.uuid4(),
            domain="Participants",
            item_code="1.2",
            question="Were all inclusions appropriate?",
            sort_order=1,
            required=True,
        ),
    ]

    async with seed_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO auth.users (id, email) VALUES (:id, :email)"),
            {"id": user_id, "email": f"instrument-{suffix}@example.com"},
        )
        for pid, name in ((project_id, "Instrument project"), (other_project_id, "Empty project")):
            await conn.execute(
                text("INSERT INTO projects (id, name, created_by_id) VALUES (:id, :name, :user)"),
                {"id": pid, "name": f"{name} {suffix}", "user": user_id},
            )
        global_id = await _insert_global_instrument(
            conn,
            tool_type=f"PROBAST_TEST_{suffix}",
            name=f"PROBAST test {suffix}",
            schema={"description": "Prediction model risk of bias", "domains": 4},
            aggregation_rules={"overall": "worst_domain"},
            target_mode="per_model",
        )
        for row in global_items:
            await _insert_global_item(conn, global_id, row)
        bare_global_id = await _insert_global_instrument(
            conn, tool_type=f"BARE_TEST_{suffix}", name=f"Bare test {suffix}"
        )
        inactive_global_id = await _insert_global_instrument(
            conn,
            tool_type=f"INACTIVE_TEST_{suffix}",
            name=f"Inactive test {suffix}",
            is_active=False,
        )

    yield Seed(
        user_id=user_id,
        project_id=project_id,
        other_project_id=other_project_id,
        global_id=global_id,
        bare_global_id=bare_global_id,
        inactive_global_id=inactive_global_id,
        global_items=global_items,
    )

    # Release any locks held by the service session before deleting the seed rows.
    await db_session.rollback()
    async with seed_engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM projects WHERE id IN (:a, :b)"),
            {"a": project_id, "b": other_project_id},
        )
        await conn.execute(
            text("DELETE FROM assessment_instruments WHERE id IN (:a, :b, :c)"),
            {"a": global_id, "b": bare_global_id, "c": inactive_global_id},
        )
        await conn.execute(text("DELETE FROM auth.users WHERE id = :id"), {"id": user_id})


@pytest_asyncio.fixture
async def service(db_session: AsyncSession, seed: Seed) -> ProjectAssessmentInstrumentService:
    return ProjectAssessmentInstrumentService(
        db=db_session, user_id=str(seed.user_id), trace_id="trace-instruments"
    )


async def _scalar(engine: AsyncEngine, sql: str, **params: Any) -> Any:
    """Read a value on a fresh connection, i.e. only what was committed."""
    async with engine.connect() as conn:
        return (await conn.execute(text(sql), params)).scalar_one()


def _custom_create(project_id: uuid.UUID, **overrides: Any) -> ProjectAssessmentInstrumentCreate:
    values: dict[str, Any] = {
        "project_id": project_id,
        "name": "Custom checklist",
        "description": "Home made checklist",
        "tool_type": "CUSTOM",
        "mode": "human",
        "items": [],
    }
    values.update(overrides)
    return ProjectAssessmentInstrumentCreate(**values)


# =================== CLONING ===================


class TestCloneGlobalInstrument:
    async def test_clone_copies_metadata_and_all_items(
        self,
        service: ProjectAssessmentInstrumentService,
        seed: Seed,
        seed_engine: AsyncEngine,
    ) -> None:
        cloned = await service.clone_global_instrument(seed.project_id, seed.global_id)

        assert cloned.project_id == seed.project_id
        assert cloned.global_instrument_id == seed.global_id
        assert cloned.name.startswith("PROBAST test")
        assert cloned.tool_type.startswith("PROBAST_TEST_")
        assert cloned.description == "Prediction model risk of bias"
        assert cloned.version == "2.0.0"
        assert cloned.mode == "hybrid"
        assert cloned.target_mode == "per_model"
        assert cloned.is_active is True
        assert cloned.aggregation_rules == {"overall": "worst_domain"}
        assert cloned.schema_config == {
            "description": "Prediction model risk of bias",
            "domains": 4,
        }
        assert cloned.created_by == seed.user_id

        by_code = {item.item_code: item for item in cloned.items}
        assert set(by_code) == {"1.1", "1.2", "4.1"}
        for source in seed.global_items:
            item = by_code[source.item_code]
            assert item.global_item_id == source.id
            assert item.project_instrument_id == cloned.id
            assert item.domain == source.domain
            assert item.question == source.question
            assert item.description == source.description
            assert item.sort_order == source.sort_order
            assert item.required == source.required
            assert item.allowed_levels == LEVELS
            assert item.llm_prompt == source.llm_prompt

        committed_items = await _scalar(
            seed_engine,
            "SELECT count(*) FROM project_assessment_items WHERE project_instrument_id = :id",
            id=cloned.id,
        )
        assert committed_items == 3

    async def test_clone_uses_custom_name(
        self, service: ProjectAssessmentInstrumentService, seed: Seed
    ) -> None:
        cloned = await service.clone_global_instrument(
            seed.project_id, seed.global_id, custom_name="PROBAST for sepsis models"
        )

        assert cloned.name == "PROBAST for sepsis models"

    async def test_clone_twice_returns_the_existing_copy(
        self,
        service: ProjectAssessmentInstrumentService,
        seed: Seed,
        seed_engine: AsyncEngine,
    ) -> None:
        first = await service.clone_global_instrument(seed.project_id, seed.global_id)
        second = await service.clone_global_instrument(
            seed.project_id, seed.global_id, custom_name="Ignored name"
        )

        assert second.id == first.id
        assert second.name == first.name
        assert len(second.items) == 3
        clones = await _scalar(
            seed_engine,
            "SELECT count(*) FROM project_assessment_instruments WHERE project_id = :id",
            id=seed.project_id,
        )
        assert clones == 1

    async def test_clone_of_instrument_without_schema_or_items(
        self, service: ProjectAssessmentInstrumentService, seed: Seed
    ) -> None:
        cloned = await service.clone_global_instrument(seed.project_id, seed.bare_global_id)

        assert cloned.description is None
        assert cloned.schema_config is None
        assert cloned.aggregation_rules is None
        assert cloned.target_mode == "per_article"
        assert cloned.items == []

    async def test_clone_unknown_global_instrument_raises(
        self,
        service: ProjectAssessmentInstrumentService,
        seed: Seed,
        seed_engine: AsyncEngine,
    ) -> None:
        missing_id = uuid.uuid4()

        with pytest.raises(ValueError, match=f"Global instrument not found: {missing_id}"):
            await service.clone_global_instrument(seed.project_id, missing_id)

        created = await _scalar(
            seed_engine,
            "SELECT count(*) FROM project_assessment_instruments WHERE project_id = :id",
            id=seed.project_id,
        )
        assert created == 0


# =================== CUSTOM INSTRUMENTS ===================


class TestCreateCustomInstrument:
    async def test_creates_instrument_with_items_and_default_ordering(
        self,
        service: ProjectAssessmentInstrumentService,
        seed: Seed,
        seed_engine: AsyncEngine,
    ) -> None:
        data = _custom_create(
            seed.project_id,
            global_instrument_id=seed.global_id,
            mode="ai",
            target_mode="per_model",
            aggregation_rules={"overall": "majority"},
            schema_config={"levels": LEVELS},
            items=[
                ProjectAssessmentItemCreate(
                    domain="Bias",
                    item_code="B1",
                    question="Was allocation concealed?",
                    allowed_levels=["yes", "no"],
                ),
                ProjectAssessmentItemCreate(
                    domain="Bias",
                    item_code="B2",
                    question="Were assessors blinded?",
                    allowed_levels=["yes", "no", "unclear"],
                    llm_prompt="Look for blinding statements.",
                    required=False,
                ),
                ProjectAssessmentItemCreate(
                    domain="Reporting",
                    item_code="R1",
                    question="Was the protocol registered?",
                    allowed_levels=["yes", "no"],
                    sort_order=7,
                    global_item_id=seed.global_items[0].id,
                ),
            ],
        )

        created = await service.create_custom_instrument(data)

        assert created.project_id == seed.project_id
        assert created.global_instrument_id == seed.global_id
        assert created.name == "Custom checklist"
        assert created.description == "Home made checklist"
        assert created.tool_type == "CUSTOM"
        assert created.mode == "ai"
        assert created.target_mode == "per_model"
        assert created.aggregation_rules == {"overall": "majority"}
        assert created.schema_config == {"levels": LEVELS}
        assert created.created_by == seed.user_id

        by_code = {item.item_code: item for item in created.items}
        # A zero sort order falls back to the item position; explicit orders are kept.
        assert {code: item.sort_order for code, item in by_code.items()} == {
            "B1": 0,
            "B2": 1,
            "R1": 7,
        }
        assert by_code["B2"].llm_prompt == "Look for blinding statements."
        assert by_code["B2"].required is False
        assert by_code["B2"].allowed_levels == ["yes", "no", "unclear"]
        assert by_code["R1"].global_item_id == seed.global_items[0].id
        assert by_code["B1"].global_item_id is None

        committed = await _scalar(
            seed_engine,
            "SELECT count(*) FROM project_assessment_items WHERE project_instrument_id = :id",
            id=created.id,
        )
        assert committed == 3

    async def test_creates_instrument_without_items(
        self,
        service: ProjectAssessmentInstrumentService,
        seed: Seed,
        seed_engine: AsyncEngine,
    ) -> None:
        created = await service.create_custom_instrument(_custom_create(seed.project_id))

        assert created.items == []
        assert created.global_instrument_id is None
        assert created.version == "1.0.0"
        name = await _scalar(
            seed_engine,
            "SELECT name FROM project_assessment_instruments WHERE id = :id",
            id=created.id,
        )
        assert name == "Custom checklist"


# =================== READING ===================


class TestReadInstruments:
    async def test_list_filters_inactive_and_sorts_items(
        self, service: ProjectAssessmentInstrumentService, seed: Seed
    ) -> None:
        cloned = await service.clone_global_instrument(seed.project_id, seed.global_id)
        inactive = await service.create_custom_instrument(
            _custom_create(seed.project_id, name="Retired checklist", is_active=False)
        )

        active_only = await service.list_project_instruments(seed.project_id)
        everything = await service.list_project_instruments(seed.project_id, active_only=False)

        assert [instrument.id for instrument in active_only] == [cloned.id]
        assert [item.item_code for item in active_only[0].items] == ["1.1", "1.2", "4.1"]
        assert {instrument.id for instrument in everything} == {cloned.id, inactive.id}

    async def test_list_for_project_without_instruments_is_empty(
        self, service: ProjectAssessmentInstrumentService, seed: Seed
    ) -> None:
        await service.clone_global_instrument(seed.project_id, seed.global_id)

        assert await service.list_project_instruments(seed.other_project_id) == []

    async def test_get_unknown_instrument_returns_none(
        self, service: ProjectAssessmentInstrumentService
    ) -> None:
        assert await service.get_project_instrument(uuid.uuid4()) is None

    async def test_list_global_instruments_summarizes_active_ones(
        self, service: ProjectAssessmentInstrumentService, seed: Seed
    ) -> None:
        summaries = {entry["id"]: entry for entry in await service.list_global_instruments()}

        assert str(seed.inactive_global_id) not in summaries

        probast = summaries[str(seed.global_id)]
        assert probast["toolType"].startswith("PROBAST_TEST_")
        assert probast["name"].startswith("PROBAST test")
        assert probast["version"] == "2.0.0"
        assert probast["mode"] == "hybrid"
        assert probast["targetMode"] == "per_model"
        assert probast["itemsCount"] == 3
        assert sorted(probast["domains"]) == ["Analysis", "Participants"]

        bare = summaries[str(seed.bare_global_id)]
        assert bare["itemsCount"] == 0
        assert bare["domains"] == []
        assert bare["targetMode"] == "per_article"


# =================== UPDATING AND DELETING INSTRUMENTS ===================


class TestUpdateAndDeleteInstrument:
    async def test_update_changes_only_the_fields_that_were_sent(
        self,
        service: ProjectAssessmentInstrumentService,
        seed: Seed,
        seed_engine: AsyncEngine,
    ) -> None:
        cloned = await service.clone_global_instrument(seed.project_id, seed.global_id)

        updated = await service.update_instrument(
            cloned.id,
            ProjectAssessmentInstrumentUpdate(
                name="PROBAST (adapted)",
                mode="ai",
                is_active=False,
                schema_config={"description": "Adapted", "domains": 3},
            ),
        )

        assert updated is not None
        assert updated.id == cloned.id
        assert updated.name == "PROBAST (adapted)"
        assert updated.mode == "ai"
        assert updated.is_active is False
        assert updated.schema_config == {"description": "Adapted", "domains": 3}
        # Fields that were not sent keep their values.
        assert updated.description == cloned.description
        assert updated.target_mode == "per_model"
        assert updated.aggregation_rules == {"overall": "worst_domain"}

        stored_schema = await _scalar(
            seed_engine,
            "SELECT schema::text FROM project_assessment_instruments WHERE id = :id",
            id=cloned.id,
        )
        assert json.loads(stored_schema) == {"description": "Adapted", "domains": 3}
        assert await service.list_project_instruments(seed.project_id) == []

    async def test_update_unknown_instrument_returns_none(
        self, service: ProjectAssessmentInstrumentService
    ) -> None:
        result = await service.update_instrument(
            uuid.uuid4(), ProjectAssessmentInstrumentUpdate(name="Nothing")
        )

        assert result is None

    async def test_delete_removes_instrument_and_its_items(
        self,
        service: ProjectAssessmentInstrumentService,
        seed: Seed,
        seed_engine: AsyncEngine,
    ) -> None:
        cloned = await service.clone_global_instrument(seed.project_id, seed.global_id)

        assert await service.delete_instrument(cloned.id) is True

        assert await service.get_project_instrument(cloned.id) is None
        remaining_items = await _scalar(
            seed_engine,
            "SELECT count(*) FROM project_assessment_items WHERE project_instrument_id = :id",
            id=cloned.id,
        )
        assert remaining_items == 0

    async def test_delete_unknown_instrument_returns_false(
        self, service: ProjectAssessmentInstrumentService
    ) -> None:
        assert await service.delete_instrument(uuid.uuid4()) is False


# =================== ITEMS ===================


class TestInstrumentItems:
    async def test_add_item_appends_after_the_highest_sort_order(
        self,
        service: ProjectAssessmentInstrumentService,
        seed: Seed,
        seed_engine: AsyncEngine,
    ) -> None:
        cloned = await service.clone_global_instrument(seed.project_id, seed.global_id)

        appended = await service.add_item(
            cloned.id,
            ProjectAssessmentItemCreate(
                domain="Analysis",
                item_code="4.2",
                question="Were missing data handled appropriately?",
                description="Imputation or complete case analysis.",
                allowed_levels=LEVELS,
                llm_prompt="Look for imputation.",
            ),
        )
        pinned = await service.add_item(
            cloned.id,
            ProjectAssessmentItemCreate(
                domain="Analysis",
                item_code="4.9",
                question="Pinned question",
                allowed_levels=LEVELS,
                sort_order=42,
                global_item_id=seed.global_items[0].id,
            ),
        )

        assert appended.project_instrument_id == cloned.id
        assert appended.sort_order == 3
        assert appended.description == "Imputation or complete case analysis."
        assert appended.llm_prompt == "Look for imputation."
        assert appended.global_item_id is None
        assert pinned.sort_order == 42
        assert pinned.global_item_id == seed.global_items[0].id

        committed = await _scalar(
            seed_engine,
            "SELECT count(*) FROM project_assessment_items WHERE project_instrument_id = :id",
            id=cloned.id,
        )
        assert committed == 5

    async def test_first_item_of_empty_instrument_gets_sort_order_zero(
        self,
        service: ProjectAssessmentInstrumentService,
        seed: Seed,
        seed_engine: AsyncEngine,
    ) -> None:
        created = await service.create_custom_instrument(_custom_create(seed.project_id))

        item = await service.add_item(
            created.id,
            ProjectAssessmentItemCreate(
                domain="General", item_code="G1", question="First?", allowed_levels=["yes"]
            ),
        )

        assert item.sort_order == 0
        assert item.project_instrument_id == created.id
        stored_order = await _scalar(
            seed_engine,
            "SELECT sort_order FROM project_assessment_items WHERE id = :id",
            id=item.id,
        )
        assert stored_order == 0

    async def test_update_item_changes_only_the_fields_that_were_sent(
        self,
        service: ProjectAssessmentInstrumentService,
        seed: Seed,
        seed_engine: AsyncEngine,
    ) -> None:
        cloned = await service.clone_global_instrument(seed.project_id, seed.global_id)
        target = next(item for item in cloned.items if item.item_code == "1.1")

        updated = await service.update_item(
            target.id,
            ProjectAssessmentItemUpdate(
                question="Were the data sources appropriate for the model?",
                required=False,
                allowed_levels=["yes", "probably yes", "no"],
                llm_prompt="Focus on the data source.",
            ),
        )

        assert updated is not None
        assert updated.id == target.id
        assert updated.question == "Were the data sources appropriate for the model?"
        assert updated.required is False
        assert updated.allowed_levels == ["yes", "probably yes", "no"]
        assert updated.llm_prompt == "Focus on the data source."
        assert updated.domain == "Participants"
        assert updated.item_code == "1.1"
        assert updated.description == "Cohort, RCT or registry data."

        stored_question = await _scalar(
            seed_engine,
            "SELECT question FROM project_assessment_items WHERE id = :id",
            id=target.id,
        )
        assert stored_question == "Were the data sources appropriate for the model?"

    async def test_update_unknown_item_returns_none(
        self, service: ProjectAssessmentInstrumentService
    ) -> None:
        result = await service.update_item(
            uuid.uuid4(), ProjectAssessmentItemUpdate(question="Nothing")
        )

        assert result is None

    async def test_delete_item_removes_only_that_item(
        self,
        service: ProjectAssessmentInstrumentService,
        seed: Seed,
        seed_engine: AsyncEngine,
    ) -> None:
        cloned = await service.clone_global_instrument(seed.project_id, seed.global_id)
        target = next(item for item in cloned.items if item.item_code == "4.1")

        assert await service.delete_item(target.id) is True

        codes = await _scalar(
            seed_engine,
            "SELECT array_agg(item_code ORDER BY item_code) FROM project_assessment_items"
            " WHERE project_instrument_id = :id",
            id=cloned.id,
        )
        assert codes == ["1.1", "1.2"]

    async def test_delete_unknown_item_returns_false(
        self, service: ProjectAssessmentInstrumentService
    ) -> None:
        assert await service.delete_item(uuid.uuid4()) is False
