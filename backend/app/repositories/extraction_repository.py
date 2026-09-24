"""
Extraction Repository.

Gerencia acesso a dados de extração de dados.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.extraction import (
    AISuggestion,
    ExtractionEntityType,
    ExtractionInstance,
    ExtractionTemplateGlobal,
    ProjectExtractionTemplate,
)
from app.repositories.base import BaseRepository


class ExtractionTemplateRepository(BaseRepository[ProjectExtractionTemplate]):
    """
    Repository para templates de extração de projetos.
    """

    def __init__(self, db: AsyncSession):
        super().__init__(db, ProjectExtractionTemplate)

    async def get_by_project(
        self,
        project_id: UUID | str,
    ) -> list[ProjectExtractionTemplate]:
        """
        Lista templates de um projeto.

        Args:
            project_id: ID do projeto.

        Returns:
            Lista de templates.
        """
        if isinstance(project_id, str):
            project_id = UUID(project_id)

        result = await self.db.execute(
            select(ProjectExtractionTemplate).where(
                ProjectExtractionTemplate.project_id == project_id
            )
        )
        return list(result.scalars().all())

    async def get_with_entity_types(
        self,
        template_id: UUID | str,
    ) -> ProjectExtractionTemplate | None:
        """
        Busca template com entity types.

        Args:
            template_id: ID do template.

        Returns:
            Template com entity types ou None.
        """
        if isinstance(template_id, str):
            template_id = UUID(template_id)

        result = await self.db.execute(
            select(ProjectExtractionTemplate)
            .options(selectinload(ProjectExtractionTemplate.entity_types))
            .where(ProjectExtractionTemplate.id == template_id)
        )
        return result.scalar_one_or_none()


class GlobalTemplateRepository(BaseRepository[ExtractionTemplateGlobal]):
    """
    Repository para templates globais de extração.
    """

    def __init__(self, db: AsyncSession):
        super().__init__(db, ExtractionTemplateGlobal)

    async def get_active(self) -> list[ExtractionTemplateGlobal]:
        """
        Lista templates globais ativos.

        Returns:
            Lista de templates ativos.
        """
        # extraction_templates_global has no is_active column; the templates offered
        # to projects are the ones flagged is_global (same filter as the frontend).
        result = await self.db.execute(
            select(ExtractionTemplateGlobal).where(ExtractionTemplateGlobal.is_global.is_(True))
        )
        return list(result.scalars().all())


class ExtractionEntityTypeRepository(BaseRepository[ExtractionEntityType]):
    """
    Repository para entity types de extração.
    """

    def __init__(self, db: AsyncSession):
        super().__init__(db, ExtractionEntityType)

    async def get_by_template(
        self,
        template_id: UUID | str,
        is_project_template: bool = True,
    ) -> list[ExtractionEntityType]:
        """
        Lista entity types de um template.

        Args:
            template_id: ID do template.
            is_project_template: Se é template de projeto.

        Returns:
            Lista de entity types.
        """
        if isinstance(template_id, str):
            template_id = UUID(template_id)

        if is_project_template:
            query = select(ExtractionEntityType).where(
                ExtractionEntityType.project_template_id == template_id
            )
        else:
            query = select(ExtractionEntityType).where(
                ExtractionEntityType.template_id == template_id
            )

        query = query.order_by(ExtractionEntityType.sort_order)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_with_fields(
        self,
        entity_type_id: UUID | str,
    ) -> ExtractionEntityType | None:
        """
        Busca entity type com seus fields.

        Args:
            entity_type_id: ID do entity type.

        Returns:
            Entity type com fields ou None.
        """
        if isinstance(entity_type_id, str):
            entity_type_id = UUID(entity_type_id)

        result = await self.db.execute(
            select(ExtractionEntityType)
            .options(selectinload(ExtractionEntityType.fields))
            .where(ExtractionEntityType.id == entity_type_id)
        )
        return result.scalar_one_or_none()

    async def get_by_name(
        self,
        name: str,
        template_id: UUID | str,
        is_project_template: bool = True,
    ) -> ExtractionEntityType | None:
        """
        Busca entity type por nome em um template.

        Args:
            name: Nome do entity type.
            template_id: ID do template.
            is_project_template: Se é template de projeto.

        Returns:
            Entity type ou None.
        """
        if isinstance(template_id, str):
            template_id = UUID(template_id)

        query = select(ExtractionEntityType).where(ExtractionEntityType.name == name)

        if is_project_template:
            query = query.where(ExtractionEntityType.project_template_id == template_id)
        else:
            query = query.where(ExtractionEntityType.template_id == template_id)

        result = await self.db.execute(query.limit(1))
        return result.scalar_one_or_none()

    async def get_children(
        self,
        parent_entity_type_id: UUID | str,
        cardinality: str | None = None,
    ) -> list[ExtractionEntityType]:
        """
        Fetch child entity types with eager loading of fields.

        Args:
            parent_entity_type_id: Parent entity type ID.
            cardinality: Optional cardinality filter.

        Returns:
            List of child entity types with fields preloaded.
        """
        if isinstance(parent_entity_type_id, str):
            parent_entity_type_id = UUID(parent_entity_type_id)

        query = (
            select(ExtractionEntityType)
            .where(ExtractionEntityType.parent_entity_type_id == parent_entity_type_id)
            .options(selectinload(ExtractionEntityType.fields))  # Eager load fields
        )

        if cardinality:
            query = query.where(ExtractionEntityType.cardinality == cardinality)

        query = query.order_by(ExtractionEntityType.sort_order)

        result = await self.db.execute(query)
        return list(result.scalars().all())


class ExtractionInstanceRepository(BaseRepository[ExtractionInstance]):
    """
    Repository para instâncias de extração.
    """

    def __init__(self, db: AsyncSession):
        super().__init__(db, ExtractionInstance)

    async def get_by_article(
        self,
        article_id: UUID | str,
        entity_type_id: UUID | str | None = None,
    ) -> list[ExtractionInstance]:
        """
        Lista instâncias de um artigo.

        Args:
            article_id: ID do artigo.
            entity_type_id: Filtro por entity type (opcional).

        Returns:
            Lista de instâncias.
        """
        if isinstance(article_id, str):
            article_id = UUID(article_id)

        query = select(ExtractionInstance).where(ExtractionInstance.article_id == article_id)

        if entity_type_id:
            if isinstance(entity_type_id, str):
                entity_type_id = UUID(entity_type_id)
            query = query.where(ExtractionInstance.entity_type_id == entity_type_id)

        query = query.order_by(ExtractionInstance.sort_order)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_children(
        self,
        parent_instance_id: UUID | str,
    ) -> list[ExtractionInstance]:
        """
        Lista instâncias filhas.

        Args:
            parent_instance_id: ID da instância pai.

        Returns:
            Lista de instâncias filhas.
        """
        if isinstance(parent_instance_id, str):
            parent_instance_id = UUID(parent_instance_id)

        result = await self.db.execute(
            select(ExtractionInstance)
            .where(ExtractionInstance.parent_instance_id == parent_instance_id)
            .order_by(ExtractionInstance.sort_order)
        )
        return list(result.scalars().all())

    async def get_with_values(
        self,
        instance_id: UUID | str,
    ) -> ExtractionInstance | None:
        """
        Busca instância com valores extraídos.

        Args:
            instance_id: ID da instância.

        Returns:
            Instância com valores ou None.
        """
        if isinstance(instance_id, str):
            instance_id = UUID(instance_id)

        result = await self.db.execute(
            select(ExtractionInstance)
            .options(selectinload(ExtractionInstance.values))
            .where(ExtractionInstance.id == instance_id)
        )
        return result.scalar_one_or_none()


class AISuggestionRepository(BaseRepository[AISuggestion]):
    """
    Repository para sugestões de AI.
    """

    def __init__(self, db: AsyncSession):
        super().__init__(db, AISuggestion)

    async def get_by_instance(
        self,
        instance_id: UUID | str,
        status: str | None = None,
    ) -> list[AISuggestion]:
        """
        Lista sugestões de uma instância.

        Args:
            instance_id: ID da instância.
            status: Filtro por status (opcional).

        Returns:
            Lista de sugestões.
        """
        if isinstance(instance_id, str):
            instance_id = UUID(instance_id)

        query = select(AISuggestion).where(AISuggestion.instance_id == instance_id)

        if status:
            query = query.where(AISuggestion.status == status)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_pending_by_article(
        self,
        article_id: UUID | str,
    ) -> list[AISuggestion]:
        """
        Lista sugestões pendentes de um artigo.

        Args:
            article_id: ID do artigo.

        Returns:
            Lista de sugestões pendentes.
        """
        if isinstance(article_id, str):
            article_id = UUID(article_id)

        result = await self.db.execute(
            select(AISuggestion)
            .join(ExtractionInstance)
            .where(ExtractionInstance.article_id == article_id)
            .where(AISuggestion.status == "pending")
        )
        return list(result.scalars().all())
