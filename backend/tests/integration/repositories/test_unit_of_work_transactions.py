"""Integration tests for UnitOfWork against a real database transaction."""

from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project, ProjectMember
from app.repositories.unit_of_work import UnitOfWork


async def _count_projects(session: AsyncSession, owner_id: UUID) -> int:
    result = await session.execute(
        select(func.count()).select_from(Project).where(Project.created_by_id == owner_id)
    )
    return result.scalar_one()


async def test_error_inside_context_discards_flushed_changes(
    session: AsyncSession, user_id: UUID
) -> None:
    with pytest.raises(RuntimeError, match="abort"):
        async with UnitOfWork(session) as uow:
            await uow.projects.create(Project(name="Discarded", created_by_id=user_id))
            assert await _count_projects(session, user_id) == 1
            raise RuntimeError("abort")

    # The automatic rollback discarded the flushed project.
    assert await _count_projects(session, user_id) == 0


async def test_repositories_share_the_unit_of_work_transaction(
    session: AsyncSession, user_id: UUID
) -> None:
    async with UnitOfWork(session) as uow:
        project = await uow.projects.create(Project(name="Shared", created_by_id=user_id))
        await uow.project_members.create(
            ProjectMember(project_id=project.id, user_id=user_id, role="manager")
        )

        # Rows flushed through one repository are visible to the others before commit.
        assert [p.id for p in await uow.projects.get_by_user(user_id)] == [project.id]
        assert await uow.project_members.is_member(project.id, user_id) is True
