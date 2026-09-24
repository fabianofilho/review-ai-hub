"""Integration tests for ProjectRepository and ProjectMemberRepository."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project, ProjectMember, ProjectMemberRole
from app.repositories.project_repository import ProjectMemberRepository, ProjectRepository
from tests.integration.repositories.factories import add, create_project, create_user


@pytest.fixture
def projects(session: AsyncSession) -> ProjectRepository:
    return ProjectRepository(session)


@pytest.fixture
def members(session: AsyncSession) -> ProjectMemberRepository:
    return ProjectMemberRepository(session)


async def _add_member(
    session: AsyncSession, project_id: UUID, user_id: UUID, role: str = "reviewer"
) -> ProjectMember:
    return await add(session, ProjectMember(project_id=project_id, user_id=user_id, role=role))


class TestProjectRepository:
    async def test_get_by_user_returns_only_member_projects(
        self, projects: ProjectRepository, session: AsyncSession, user_id: UUID
    ) -> None:
        member_of = [await create_project(session, user_id) for _ in range(2)]
        await create_project(session, user_id)  # owned but not a member
        for project in member_of:
            await _add_member(session, project.id, user_id)

        result = await projects.get_by_user(str(user_id))

        assert {p.id for p in result} == {p.id for p in member_of}

    async def test_get_by_user_paginates(
        self, projects: ProjectRepository, session: AsyncSession, user_id: UUID
    ) -> None:
        for _ in range(3):
            project = await create_project(session, user_id)
            await _add_member(session, project.id, user_id)

        assert len(await projects.get_by_user(user_id, limit=2)) == 2
        assert len(await projects.get_by_user(user_id, skip=2)) == 1

    async def test_get_by_user_without_memberships_is_empty(
        self, projects: ProjectRepository
    ) -> None:
        assert await projects.get_by_user(uuid4()) == []

    async def test_get_with_members_loads_members(
        self,
        projects: ProjectRepository,
        session: AsyncSession,
        project: Project,
        user_id: UUID,
    ) -> None:
        other_user = await create_user(session)
        await _add_member(session, project.id, user_id, role="manager")
        await _add_member(session, project.id, other_user)

        loaded = await projects.get_with_members(str(project.id))

        assert loaded is not None
        assert {m.user_id for m in loaded.members} == {user_id, other_user}

    async def test_get_with_members_returns_none_when_missing(
        self, projects: ProjectRepository
    ) -> None:
        assert await projects.get_with_members(uuid4()) is None

    async def test_get_summary_returns_review_context(
        self, projects: ProjectRepository, session: AsyncSession, user_id: UUID
    ) -> None:
        project = await create_project(
            session,
            user_id,
            review_title="Prognostic models for sepsis",
            description="A review",
            condition_studied="Sepsis",
            eligibility_criteria={"inclusion": ["adults"]},
            study_design={"type": "cohort"},
        )

        summary = await projects.get_summary(project.id)

        assert summary == {
            "review_title": "Prognostic models for sepsis",
            "description": "A review",
            "condition_studied": "Sepsis",
            "eligibility_criteria": {"inclusion": ["adults"]},
            "study_design": {"type": "cohort"},
        }

    async def test_get_summary_raises_for_unknown_project(
        self, projects: ProjectRepository
    ) -> None:
        missing = uuid4()
        with pytest.raises(ValueError, match=f"Project not found: {missing}"):
            await projects.get_summary(missing)


class TestProjectMemberRepository:
    async def test_get_by_project_lists_members(
        self,
        members: ProjectMemberRepository,
        session: AsyncSession,
        project: Project,
        user_id: UUID,
    ) -> None:
        other_user = await create_user(session)
        other_project = await create_project(session, user_id)
        await _add_member(session, project.id, user_id)
        await _add_member(session, project.id, other_user)
        await _add_member(session, other_project.id, user_id)

        result = await members.get_by_project(str(project.id))

        assert {m.user_id for m in result} == {user_id, other_user}
        assert all(m.project_id == project.id for m in result)

    async def test_get_member_and_is_member(
        self,
        members: ProjectMemberRepository,
        session: AsyncSession,
        project: Project,
        user_id: UUID,
    ) -> None:
        membership = await _add_member(session, project.id, user_id)
        outsider = await create_user(session)

        assert await members.get_member(str(project.id), str(user_id)) is membership
        assert await members.get_member(project.id, outsider) is None
        assert await members.is_member(project.id, user_id) is True
        assert await members.is_member(project.id, outsider) is False

    async def test_has_role_matches_exact_role(
        self,
        members: ProjectMemberRepository,
        session: AsyncSession,
        project: Project,
        user_id: UUID,
    ) -> None:
        await _add_member(session, project.id, user_id, role="manager")

        assert await members.has_role(project.id, user_id, ProjectMemberRole.MANAGER) is True
        assert await members.has_role(project.id, user_id, ProjectMemberRole.REVIEWER) is False

    async def test_has_role_is_false_for_non_member(
        self, members: ProjectMemberRepository, project: Project
    ) -> None:
        assert await members.has_role(project.id, uuid4(), ProjectMemberRole.MANAGER) is False
