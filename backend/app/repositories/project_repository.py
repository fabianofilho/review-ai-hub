"""
Project Repository.

Gerencia acesso a dados de projetos e membros.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.project import Project, ProjectMember, ProjectMemberRole
from app.repositories.base import BaseRepository


class ProjectRepository(BaseRepository[Project]):
    """
    Repository para operações com projetos.

    Encapsula queries de projetos e relacionamentos.
    """

    def __init__(self, db: AsyncSession):
        super().__init__(db, Project)

    async def get_by_user(
        self,
        user_id: UUID | str,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Project]:
        """
        Lista projetos acessíveis por um usuário.

        Args:
            user_id: ID do usuário.
            skip: Offset para paginação.
            limit: Limite de resultados.

        Returns:
            Lista de projetos.
        """
        if isinstance(user_id, str):
            user_id = UUID(user_id)

        # Projetos onde o usuário é membro
        result = await self.db.execute(
            select(Project)
            .join(ProjectMember)
            .where(ProjectMember.user_id == user_id)
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_with_members(self, project_id: UUID | str) -> Project | None:
        """
        Busca projeto com seus membros.

        Args:
            project_id: ID do projeto.

        Returns:
            Projeto com membros ou None.
        """
        if isinstance(project_id, str):
            project_id = UUID(project_id)

        result = await self.db.execute(
            select(Project).options(selectinload(Project.members)).where(Project.id == project_id)
        )
        return result.scalar_one_or_none()

    async def get_summary(self, project_id: UUID | str) -> dict[str, Any]:
        """
        Busca resumo do projeto com contexto.

        Args:
            project_id: ID do projeto.

        Returns:
            Dict com dados do projeto para contexto de AI.
        """
        project = await self.get_by_id(project_id)

        if not project:
            raise ValueError(f"Project not found: {project_id}")

        return {
            "review_title": project.review_title,
            "description": project.description,
            "condition_studied": project.condition_studied,
            "eligibility_criteria": project.eligibility_criteria,
            "study_design": project.study_design,
        }


class ProjectMemberRepository(BaseRepository[ProjectMember]):
    """
    Repository para membros de projetos.

    Gerencia associações usuário-projeto.
    """

    def __init__(self, db: AsyncSession):
        super().__init__(db, ProjectMember)

    async def get_by_project(
        self,
        project_id: UUID | str,
    ) -> list[ProjectMember]:
        """
        Lista membros de um projeto.

        Args:
            project_id: ID do projeto.

        Returns:
            Lista de membros.
        """
        if isinstance(project_id, str):
            project_id = UUID(project_id)

        result = await self.db.execute(
            select(ProjectMember).where(ProjectMember.project_id == project_id)
        )
        return list(result.scalars().all())

    async def get_member(
        self,
        project_id: UUID | str,
        user_id: UUID | str,
    ) -> ProjectMember | None:
        """
        Busca membro específico de um projeto.

        Args:
            project_id: ID do projeto.
            user_id: ID do usuário.

        Returns:
            Membro ou None.
        """
        if isinstance(project_id, str):
            project_id = UUID(project_id)
        if isinstance(user_id, str):
            user_id = UUID(user_id)

        result = await self.db.execute(
            select(ProjectMember)
            .where(ProjectMember.project_id == project_id)
            .where(ProjectMember.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def is_member(
        self,
        project_id: UUID | str,
        user_id: UUID | str,
    ) -> bool:
        """
        Verifica se usuário é membro do projeto.

        Args:
            project_id: ID do projeto.
            user_id: ID do usuário.

        Returns:
            True se é membro.
        """
        member = await self.get_member(project_id, user_id)
        return member is not None

    async def has_role(
        self,
        project_id: UUID | str,
        user_id: UUID | str,
        role: ProjectMemberRole,
    ) -> bool:
        """
        Verifica se usuário tem role específico.

        Args:
            project_id: ID do projeto.
            user_id: ID do usuário.
            role: Role a verificar.

        Returns:
            True se tem o role.
        """
        member = await self.get_member(project_id, user_id)
        return member is not None and member.role == role
