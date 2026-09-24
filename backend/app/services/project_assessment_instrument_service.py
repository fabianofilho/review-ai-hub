"""
Project Assessment Instrument Service.

Service to manage assessment instruments per project.
Allows cloning global instruments (PROBAST, ROBIS, etc.) to
projects or creating custom instruments.
"""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import LoggerMixin
from app.models.assessment import (
    ProjectAssessmentInstrument,
    ProjectAssessmentItem,
)
from app.repositories.assessment_repository import (
    AssessmentInstrumentRepository,
    AssessmentItemRepository,
    ProjectAssessmentInstrumentRepository,
    ProjectAssessmentItemRepository,
)
from app.schemas.assessment import (
    ProjectAssessmentInstrumentCreate,
    ProjectAssessmentInstrumentSchema,
    ProjectAssessmentInstrumentUpdate,
    ProjectAssessmentItemCreate,
    ProjectAssessmentItemSchema,
    ProjectAssessmentItemUpdate,
)


class ProjectAssessmentInstrumentService(LoggerMixin):
    """
    Service to manage assessment instruments per project.

    Allows:
    - Cloning global instruments (PROBAST, ROBIS)
    - Creating custom instruments
    - Managing items of each instrument
    - Updating settings per project
    """

    def __init__(
        self,
        db: AsyncSession,
        user_id: str,
        trace_id: str | None = None,
    ):
        self.db = db
        self.user_id = user_id
        self.trace_id = trace_id

        # Repositories
        self._global_instruments = AssessmentInstrumentRepository(db)
        self._global_items = AssessmentItemRepository(db)
        self._project_instruments = ProjectAssessmentInstrumentRepository(db)
        self._project_items = ProjectAssessmentItemRepository(db)

    async def list_project_instruments(
        self,
        project_id: UUID,
        active_only: bool = True,
    ) -> list[ProjectAssessmentInstrumentSchema]:
        """
        List instruments for a project.

        Args:
            project_id: Project ID.
            active_only: If True, return only active instruments.

        Returns:
            List of project instruments.
        """
        instruments = await self._project_instruments.get_by_project(
            project_id, active_only=active_only
        )

        result = []
        for instrument in instruments:
            # Items already loaded via selectinload in get_by_project
            raw_items = getattr(instrument, "items", None) or []
            items = sorted(raw_items, key=lambda i: i.sort_order or 0)
            schema = ProjectAssessmentInstrumentSchema.model_validate(instrument)
            schema.items = [ProjectAssessmentItemSchema.model_validate(item) for item in items]
            result.append(schema)

        return result

    async def get_project_instrument(
        self,
        instrument_id: UUID,
    ) -> ProjectAssessmentInstrumentSchema | None:
        """
        Fetch instrument by ID with items.

        Args:
            instrument_id: Instrument ID.

        Returns:
            Instrument with items or None.
        """
        instrument = await self._project_instruments.get_with_items(instrument_id)
        if not instrument:
            return None

        return ProjectAssessmentInstrumentSchema.model_validate(instrument)

    async def clone_global_instrument(
        self,
        project_id: UUID,
        global_instrument_id: UUID,
        custom_name: str | None = None,
    ) -> ProjectAssessmentInstrumentSchema:
        """
        Clone a global instrument to a project.

        Creates a copy of the global instrument (PROBAST, ROBIS, etc.)
        with all its items, allowing per-project customization.

        Args:
            project_id: Project ID.
            global_instrument_id: ID of global instrument to clone.
            custom_name: Custom name (optional).

        Returns:
            Cloned instrument.

        Raises:
            ValueError: If global instrument not found.
        """
        # Check if already cloned
        existing = await self._project_instruments.get_by_global_instrument(
            project_id, global_instrument_id
        )
        if existing:
            self.logger.warning(
                "Instrument already cloned to project",
                project_id=str(project_id),
                global_instrument_id=str(global_instrument_id),
            )
            return await self.get_project_instrument(existing.id)  # type: ignore

        # Get global instrument with items
        global_instrument = await self._global_instruments.get_with_items(global_instrument_id)
        if not global_instrument:
            raise ValueError(f"Global instrument not found: {global_instrument_id}")

        # Create project instrument
        project_instrument = ProjectAssessmentInstrument(
            project_id=project_id,
            global_instrument_id=global_instrument_id,
            name=custom_name or global_instrument.name,
            description=global_instrument.schema_.get("description")
            if global_instrument.schema_
            else None,
            tool_type=global_instrument.tool_type,
            version=global_instrument.version,
            mode=global_instrument.mode,
            target_mode=getattr(global_instrument, "target_mode", "per_article"),
            is_active=True,
            aggregation_rules=global_instrument.aggregation_rules,
            schema_=global_instrument.schema_,
            created_by=UUID(self.user_id),
        )

        self.db.add(project_instrument)
        await self.db.flush()
        await self.db.refresh(project_instrument)

        # Clone all items
        project_items = []
        for global_item in global_instrument.items:
            project_item = ProjectAssessmentItem(
                project_instrument_id=project_instrument.id,
                global_item_id=global_item.id,
                domain=global_item.domain,
                item_code=global_item.item_code,
                question=global_item.question,
                description=global_item.description,
                sort_order=global_item.sort_order,
                required=global_item.required,
                allowed_levels=global_item.allowed_levels,
                llm_prompt=global_item.llm_prompt,
            )
            project_items.append(project_item)

        if project_items:
            await self._project_items.bulk_create(project_items)

        await self.db.commit()

        self.logger.info(
            "Cloned global instrument to project",
            project_id=str(project_id),
            global_instrument_id=str(global_instrument_id),
            project_instrument_id=str(project_instrument.id),
            items_count=len(project_items),
        )

        return await self.get_project_instrument(project_instrument.id)  # type: ignore

    async def create_custom_instrument(
        self,
        data: ProjectAssessmentInstrumentCreate,
    ) -> ProjectAssessmentInstrumentSchema:
        """
        Cria um instrumento customizado para um projeto.

        Args:
            data: Dados do instrumento a criar.

        Returns:
            Instrumento criado.
        """
        # Create instrument
        instrument = ProjectAssessmentInstrument(
            project_id=data.project_id,
            global_instrument_id=data.global_instrument_id,
            name=data.name,
            description=data.description,
            tool_type=data.tool_type,
            version=data.version,
            mode=data.mode,
            target_mode=data.target_mode,
            is_active=data.is_active,
            aggregation_rules=data.aggregation_rules,
            schema_=data.schema_config,
            created_by=UUID(self.user_id),
        )

        self.db.add(instrument)
        await self.db.flush()
        await self.db.refresh(instrument)

        # Create items if provided
        if data.items:
            project_items = []
            for i, item_data in enumerate(data.items):
                project_item = ProjectAssessmentItem(
                    project_instrument_id=instrument.id,
                    global_item_id=item_data.global_item_id,
                    domain=item_data.domain,
                    item_code=item_data.item_code,
                    question=item_data.question,
                    description=item_data.description,
                    sort_order=item_data.sort_order if item_data.sort_order else i,
                    required=item_data.required,
                    allowed_levels=item_data.allowed_levels,
                    llm_prompt=item_data.llm_prompt,
                )
                project_items.append(project_item)

            if project_items:
                await self._project_items.bulk_create(project_items)

        await self.db.commit()

        self.logger.info(
            "Created custom instrument",
            project_id=str(data.project_id),
            instrument_id=str(instrument.id),
            items_count=len(data.items) if data.items else 0,
        )

        return await self.get_project_instrument(instrument.id)  # type: ignore

    async def update_instrument(
        self,
        instrument_id: UUID,
        data: ProjectAssessmentInstrumentUpdate,
    ) -> ProjectAssessmentInstrumentSchema | None:
        """
        Atualiza um instrumento de projeto.

        Args:
            instrument_id: ID do instrumento.
            data: Dados a atualizar.

        Returns:
            Instrumento atualizado ou None.
        """
        instrument = await self._project_instruments.get_by_id(instrument_id)
        if not instrument:
            return None

        # Update fields
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if field == "schema_config":
                instrument.schema_ = value
            else:
                setattr(instrument, field, value)

        await self.db.flush()
        await self.db.commit()

        return await self.get_project_instrument(instrument_id)

    async def delete_instrument(
        self,
        instrument_id: UUID,
    ) -> bool:
        """
        Deleta um instrumento de projeto.

        Args:
            instrument_id: ID do instrumento.

        Returns:
            True if deleted, False if not found.
        """
        instrument = await self._project_instruments.get_by_id(instrument_id)
        if not instrument:
            return False

        await self._project_instruments.delete(instrument)
        await self.db.commit()

        self.logger.info(
            "Deleted project instrument",
            instrument_id=str(instrument_id),
        )

        return True

    async def add_item(
        self,
        instrument_id: UUID,
        data: ProjectAssessmentItemCreate,
    ) -> ProjectAssessmentItemSchema:
        """
        Adiciona um item a um instrumento.

        Args:
            instrument_id: ID do instrumento.
            data: Dados do item.

        Returns:
            Item criado.
        """
        # Get max sort_order
        items = await self._project_items.get_by_instrument(instrument_id)
        max_order = max([item.sort_order for item in items], default=-1)

        item = ProjectAssessmentItem(
            project_instrument_id=instrument_id,
            global_item_id=data.global_item_id,
            domain=data.domain,
            item_code=data.item_code,
            question=data.question,
            description=data.description,
            sort_order=data.sort_order if data.sort_order else max_order + 1,
            required=data.required,
            allowed_levels=data.allowed_levels,
            llm_prompt=data.llm_prompt,
        )

        self.db.add(item)
        await self.db.flush()
        await self.db.refresh(item)
        await self.db.commit()

        return ProjectAssessmentItemSchema.model_validate(item)

    async def update_item(
        self,
        item_id: UUID,
        data: ProjectAssessmentItemUpdate,
    ) -> ProjectAssessmentItemSchema | None:
        """
        Atualiza um item de instrumento.

        Args:
            item_id: ID do item.
            data: Dados a atualizar.

        Returns:
            Item atualizado ou None.
        """
        item = await self._project_items.get_by_id(item_id)
        if not item:
            return None

        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(item, field, value)

        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(item)

        return ProjectAssessmentItemSchema.model_validate(item)

    async def delete_item(
        self,
        item_id: UUID,
    ) -> bool:
        """
        Deleta um item de instrumento.

        Args:
            item_id: ID do item.

        Returns:
            True if deleted, False if not found.
        """
        item = await self._project_items.get_by_id(item_id)
        if not item:
            return False

        await self._project_items.delete(item)
        await self.db.commit()

        return True

    async def list_global_instruments(
        self,
    ) -> list[dict[str, Any]]:
        """
        List global instruments available for cloning.

        Returns:
            Lista de instrumentos globais com seus items.
        """
        instruments = await self._global_instruments.get_all_active_with_items()

        result = []
        for instrument in instruments:
            items = getattr(instrument, "items", None) or []
            result.append(
                {
                    "id": str(instrument.id),
                    "toolType": instrument.tool_type,
                    "name": instrument.name,
                    "version": instrument.version,
                    "mode": instrument.mode,
                    "targetMode": getattr(instrument, "target_mode", "per_article"),
                    "itemsCount": len(items),
                    "domains": list({item.domain for item in items if item.domain}),
                }
            )

        return result
