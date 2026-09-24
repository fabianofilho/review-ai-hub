"""
Row factories for repository integration tests.

Each helper adds rows to the caller's session and flushes them, but never
commits. The ``session`` fixture in this package rolls the transaction back
after every test, so the tests leave no data behind and can run in any order.

PostgreSQL returns the same ``now()`` for every statement of a transaction,
so tests that check ordering pass explicit timestamps built with ``at()``.
"""

from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.article import Article
from app.models.assessment import (
    AssessmentInstance,
    AssessmentInstrument,
    AssessmentItem,
    ProjectAssessmentInstrument,
)
from app.models.base import Base
from app.models.extraction import (
    ExtractionEntityType,
    ExtractionInstance,
    ProjectExtractionTemplate,
)
from app.models.project import Project

ModelT = TypeVar("ModelT", bound=Base)

BASE_TIME = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)


def at(minutes: int) -> datetime:
    """Return a deterministic timestamp ``minutes`` after BASE_TIME."""
    return BASE_TIME + timedelta(minutes=minutes)


async def add(session: AsyncSession, obj: ModelT) -> ModelT:
    """Add an ORM object to the session and flush it."""
    session.add(obj)
    await session.flush()
    return obj


async def create_user(session: AsyncSession) -> UUID:
    """
    Create an auth user and return its id.

    The handle_new_user trigger on auth.users creates the matching profile row,
    which is the FK target used by the application tables.
    """
    user_id = uuid4()
    await session.execute(
        text("INSERT INTO auth.users (id, email) VALUES (:id, :email)"),
        {"id": user_id, "email": f"{user_id}@example.com"},
    )
    return user_id


async def create_project(session: AsyncSession, owner_id: UUID, **fields: Any) -> Project:
    """Create a project owned by ``owner_id``."""
    fields.setdefault("name", f"Project {uuid4().hex[:8]}")
    return await add(session, Project(created_by_id=owner_id, **fields))


async def create_article(session: AsyncSession, project_id: UUID, **fields: Any) -> Article:
    """Create an article in ``project_id``."""
    fields.setdefault("title", f"Article {uuid4().hex[:8]}")
    return await add(session, Article(project_id=project_id, **fields))


async def create_instrument(session: AsyncSession, **fields: Any) -> AssessmentInstrument:
    """Create a global assessment instrument."""
    fields.setdefault("tool_type", "PROBAST")
    fields.setdefault("name", f"Instrument {uuid4().hex[:8]}")
    fields.setdefault("version", "1.0.0")
    return await add(session, AssessmentInstrument(**fields))


async def create_item(
    session: AsyncSession, instrument_id: UUID, item_code: str, **fields: Any
) -> AssessmentItem:
    """Create an item of a global assessment instrument."""
    fields.setdefault("domain", "participants")
    fields.setdefault("question", f"Question {item_code}?")
    fields.setdefault("sort_order", 0)
    fields.setdefault("allowed_levels", ["low", "high", "unclear"])
    return await add(
        session, AssessmentItem(instrument_id=instrument_id, item_code=item_code, **fields)
    )


async def create_project_instrument(
    session: AsyncSession, project_id: UUID, created_by: UUID, **fields: Any
) -> ProjectAssessmentInstrument:
    """Create a project assessment instrument."""
    fields.setdefault("name", f"Project instrument {uuid4().hex[:8]}")
    fields.setdefault("tool_type", "PROBAST")
    return await add(
        session,
        ProjectAssessmentInstrument(project_id=project_id, created_by=created_by, **fields),
    )


async def create_assessment_instance(
    session: AsyncSession,
    project_id: UUID,
    article_id: UUID,
    reviewer_id: UUID,
    **fields: Any,
) -> AssessmentInstance:
    """Create an assessment instance."""
    fields.setdefault("label", f"Assessment {uuid4().hex[:8]}")
    return await add(
        session,
        AssessmentInstance(
            project_id=project_id, article_id=article_id, reviewer_id=reviewer_id, **fields
        ),
    )


async def create_project_template(
    session: AsyncSession, project_id: UUID, created_by: UUID, **fields: Any
) -> ProjectExtractionTemplate:
    """Create a project extraction template."""
    fields.setdefault("name", f"Template {uuid4().hex[:8]}")
    fields.setdefault("framework", "CHARMS")
    return await add(
        session,
        ProjectExtractionTemplate(project_id=project_id, created_by=created_by, **fields),
    )


async def create_entity_type(
    session: AsyncSession, name: str, **fields: Any
) -> ExtractionEntityType:
    """Create an extraction entity type (attach it with template_id or project_template_id)."""
    fields.setdefault("label", name.title())
    return await add(session, ExtractionEntityType(name=name, **fields))


async def create_extraction_instance(
    session: AsyncSession,
    project_id: UUID,
    template_id: UUID,
    entity_type_id: UUID,
    created_by: UUID,
    **fields: Any,
) -> ExtractionInstance:
    """Create an extraction instance."""
    fields.setdefault("label", f"Instance {uuid4().hex[:8]}")
    return await add(
        session,
        ExtractionInstance(
            project_id=project_id,
            template_id=template_id,
            entity_type_id=entity_type_id,
            created_by=created_by,
            **fields,
        ),
    )
