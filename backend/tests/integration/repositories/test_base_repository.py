"""Integration tests for the generic BaseRepository CRUD operations."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.repositories.base import BaseRepository
from tests.integration.repositories.factories import create_project


@pytest.fixture
def repo(session: AsyncSession) -> BaseRepository[Project]:
    return BaseRepository(session, Project)


async def _stored_name(session: AsyncSession, project_id: UUID) -> str | None:
    """Read the name column straight from the database, bypassing the identity map."""
    result = await session.execute(select(Project.name).where(Project.id == project_id))
    return result.scalar_one_or_none()


async def test_get_by_id_accepts_uuid_and_string(
    repo: BaseRepository[Project], project: Project
) -> None:
    assert await repo.get_by_id(project.id) is project
    assert await repo.get_by_id(str(project.id)) is project


async def test_get_by_id_returns_none_when_missing(repo: BaseRepository[Project]) -> None:
    assert await repo.get_by_id(uuid4()) is None


async def test_create_flushes_and_loads_server_defaults(
    repo: BaseRepository[Project], session: AsyncSession, user_id: UUID
) -> None:
    project = Project(name="Created via repository", created_by_id=user_id)

    created = await repo.create(project)

    assert created is project
    assert isinstance(created.id, UUID)
    # created_at comes from the database default, so refresh() must have run.
    assert created.created_at is not None
    assert await _stored_name(session, created.id) == "Created via repository"


async def test_create_from_dict_builds_model(
    repo: BaseRepository[Project], session: AsyncSession, user_id: UUID
) -> None:
    created = await repo.create_from_dict(
        {"name": "From dict", "created_by_id": user_id, "description": "desc"}
    )

    assert isinstance(created, Project)
    assert created.description == "desc"
    assert await _stored_name(session, created.id) == "From dict"


async def test_update_sets_known_attributes_and_ignores_unknown_keys(
    repo: BaseRepository[Project], session: AsyncSession, project: Project
) -> None:
    updated = await repo.update(project, {"name": "Renamed", "not_a_column": "ignored"})

    assert updated is project
    assert updated.name == "Renamed"
    assert not hasattr(updated, "not_a_column")
    assert await _stored_name(session, project.id) == "Renamed"


async def test_delete_removes_row(
    repo: BaseRepository[Project], session: AsyncSession, project: Project
) -> None:
    await repo.delete(project)

    assert await _stored_name(session, project.id) is None


async def test_delete_by_id_reports_whether_row_existed(
    repo: BaseRepository[Project], session: AsyncSession, project: Project
) -> None:
    assert await repo.delete_by_id(str(project.id)) is True
    assert await _stored_name(session, project.id) is None

    assert await repo.delete_by_id(uuid4()) is False


async def test_exists_accepts_uuid_and_string(
    repo: BaseRepository[Project], project: Project
) -> None:
    assert await repo.exists(project.id) is True
    assert await repo.exists(str(project.id)) is True
    assert await repo.exists(uuid4()) is False
    assert await repo.exists(str(uuid4())) is False


async def test_count_and_get_all_paginate(
    repo: BaseRepository[Project], session: AsyncSession, user_id: UUID
) -> None:
    before = await repo.count()
    created = [await create_project(session, user_id) for _ in range(3)]

    total = await repo.count()
    assert total == before + 3

    everything = await repo.get_all(limit=total)
    assert len(everything) == total
    assert {p.id for p in created} <= {p.id for p in everything}

    assert len(await repo.get_all(limit=2)) == 2
    assert len(await repo.get_all(skip=total - 1, limit=10)) == 1
    assert await repo.get_all(skip=total) == []
