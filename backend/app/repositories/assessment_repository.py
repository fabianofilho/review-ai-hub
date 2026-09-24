"""
Assessment Repository.

Manages access to assessment and instrument data.
"""

from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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
from app.repositories.base import BaseRepository


class AssessmentInstrumentRepository(BaseRepository[AssessmentInstrument]):
    """
    Repository for assessment instruments.
    Manages ROBINS-I, RoB 2, etc.
    """

    def __init__(self, db: AsyncSession):
        super().__init__(db, AssessmentInstrument)

    async def get_with_items(
        self,
        instrument_id: UUID | str,
    ) -> AssessmentInstrument | None:
        """
        Fetch instrument with its items.
        Args:
            instrument_id: Instrument ID.
        Returns:
            Instrument with items or None.
        """
        if isinstance(instrument_id, str):
            instrument_id = UUID(instrument_id)

        result = await self.db.execute(
            select(AssessmentInstrument)
            .options(selectinload(AssessmentInstrument.items))
            .where(AssessmentInstrument.id == instrument_id)
        )
        return result.scalar_one_or_none()

    async def get_all_active_with_items(self) -> list[AssessmentInstrument]:
        """
        List all active global instruments with items (single query).
        Returns:
            List of active instruments with items loaded.
        """
        result = await self.db.execute(
            select(AssessmentInstrument)
            .options(selectinload(AssessmentInstrument.items))
            .where(AssessmentInstrument.is_active == True)  # noqa: E712
            .order_by(AssessmentInstrument.created_at.desc())
        )
        return list(result.scalars().all())


class AssessmentItemRepository(BaseRepository[AssessmentItem]):
    """
    Repository for assessment items.
    Manages questions/evaluation criteria.
    """

    def __init__(self, db: AsyncSession):
        super().__init__(db, AssessmentItem)

    async def get_by_instrument(
        self,
        instrument_id: UUID | str,
    ) -> list[AssessmentItem]:
        """
        List items of an instrument.
        Args:
            instrument_id: Instrument ID.
        Returns:
            Sorted list of items.
        """
        if isinstance(instrument_id, str):
            instrument_id = UUID(instrument_id)

        result = await self.db.execute(
            select(AssessmentItem)
            .where(AssessmentItem.instrument_id == instrument_id)
            .order_by(AssessmentItem.sort_order)
        )
        return list(result.scalars().all())

    async def get_item_with_levels(
        self,
        item_id: UUID | str,
    ) -> AssessmentItem | None:
        """
        Fetch item with allowed levels.
        Args:
            item_id: Item ID.
        Returns:
            Item or None.
        """
        if isinstance(item_id, str):
            item_id = UUID(item_id)

        result = await self.db.execute(select(AssessmentItem).where(AssessmentItem.id == item_id))
        return result.scalar_one_or_none()


# =================== REMOVED: LEGACY AssessmentRepository ===================
# The "assessments" table was removed in migration 0032 (2026-01-28).
# Use:
# - AssessmentInstanceRepository (for instances)
# - AssessmentResponseRepository (for individual responses)
# - AssessmentEvidenceRepository (for evidence)
#
# See new repositories below (line ~520)
# =============================================================================


class AIAssessmentRepository(BaseRepository[AIAssessment]):
    """
    Repository for AI assessments.
    Manages automated assessments via OpenAI.
    """

    def __init__(self, db: AsyncSession):
        super().__init__(db, AIAssessment)

    async def get_by_article_and_item(
        self,
        article_id: UUID | str,
        assessment_item_id: UUID | str,
    ) -> AIAssessment | None:
        """
        Fetch specific AI assessment.
        Args:
            article_id: Article ID.
            assessment_item_id: Item ID.
        Returns:
            AI assessment or None.
        """
        if isinstance(article_id, str):
            article_id = UUID(article_id)
        if isinstance(assessment_item_id, str):
            assessment_item_id = UUID(assessment_item_id)

        result = await self.db.execute(
            select(AIAssessment)
            .where(AIAssessment.article_id == article_id)
            .where(AIAssessment.assessment_item_id == assessment_item_id)
            .order_by(AIAssessment.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_by_article(
        self,
        article_id: UUID | str,
    ) -> list[AIAssessment]:
        """
        List all AI assessments for an article.
        Args:
            article_id: Article ID.
        Returns:
            List of AI assessments.
        """
        if isinstance(article_id, str):
            article_id = UUID(article_id)

        result = await self.db.execute(
            select(AIAssessment)
            .where(AIAssessment.article_id == article_id)
            .order_by(AIAssessment.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_pending_review(
        self,
        project_id: UUID | str,
    ) -> list[AIAssessment]:
        """
        List AI assessments pending review.
        Args:
            project_id: Project ID.
        Returns:
            List of pending AI assessments.
        """
        if isinstance(project_id, str):
            project_id = UUID(project_id)

        result = await self.db.execute(
            select(AIAssessment)
            .where(AIAssessment.project_id == project_id)
            .where(AIAssessment.status == "pending_review")
        )
        return list(result.scalars().all())


class AIAssessmentRunRepository(BaseRepository[AIAssessmentRun]):
    """
    Repository for AI assessment runs.
    Manages tracking of AI assessment runs, similar to ExtractionRunRepository.
    """

    def __init__(self, db: AsyncSession):
        super().__init__(db, AIAssessmentRun)

    async def create_run(
        self,
        project_id: UUID,
        article_id: UUID,
        instrument_id: UUID,
        created_by: UUID,
        stage: str,
        parameters: dict,
        extraction_instance_id: UUID | None = None,
        is_project_instrument: bool = False,
    ) -> AIAssessmentRun:
        """
        Create a new assessment run with status 'pending'.
        Args:
            project_id: Project ID.
            article_id: Article ID.
            instrument_id: Instrument ID (global or project).
            created_by: User ID who created.
            stage: Run stage ('assess_single', 'assess_batch', 'assess_hierarchical').
            parameters: Input parameters (model, temperature, item_ids, etc.).
            extraction_instance_id: Extraction instance ID (for PROBAST per model).
            is_project_instrument: True if instrument_id is from project_assessment_instruments.
        Returns:
            Created run.
        """
        if is_project_instrument:
            run = AIAssessmentRun(
                project_id=project_id,
                article_id=article_id,
                instrument_id=None,
                project_instrument_id=instrument_id,
                extraction_instance_id=extraction_instance_id,
                stage=stage,
                status="pending",
                parameters=parameters,
                created_by=created_by,
            )
        else:
            run = AIAssessmentRun(
                project_id=project_id,
                article_id=article_id,
                instrument_id=instrument_id,
                project_instrument_id=None,
                extraction_instance_id=extraction_instance_id,
                stage=stage,
                status="pending",
                parameters=parameters,
                created_by=created_by,
            )

        self.db.add(run)
        await self.db.flush()
        await self.db.refresh(run)

        return run

    async def start_run(self, run_id: UUID) -> None:
        """
        Mark run as 'running' and set started_at.
        Args:
            run_id: Run ID.
        """
        await self.db.execute(
            update(AIAssessmentRun)
            .where(AIAssessmentRun.id == run_id)
            .values(status="running", started_at=func.now())
        )
        await self.db.flush()

    async def complete_run(self, run_id: UUID, results: dict) -> None:
        """
        Mark run as 'completed' and store results.
        Args:
            run_id: Run ID.
            results: Dict with metrics (tokens, duration, etc.).
        """
        await self.db.execute(
            update(AIAssessmentRun)
            .where(AIAssessmentRun.id == run_id)
            .values(
                status="completed",
                completed_at=func.now(),
                results=results,
            )
        )
        await self.db.flush()

    async def fail_run(self, run_id: UUID, error: str) -> None:
        """
        Mark run as 'failed' with error message.
        Args:
            run_id: Run ID.
            error: Error message.
        """
        await self.db.execute(
            update(AIAssessmentRun)
            .where(AIAssessmentRun.id == run_id)
            .values(
                status="failed",
                completed_at=func.now(),
                error_message=error,
            )
        )
        await self.db.flush()

    async def get_by_project(
        self,
        project_id: UUID,
        status: str | None = None,
    ) -> list[AIAssessmentRun]:
        """
        List runs for a project.

        Args:
            project_id: Project ID.
            status: Filtro por status (opcional).

        Returns:
            List of runs.
        """
        query = (
            select(AIAssessmentRun)
            .where(AIAssessmentRun.project_id == project_id)
            .order_by(AIAssessmentRun.created_at.desc())
        )

        if status:
            query = query.where(AIAssessmentRun.status == status)

        result = await self.db.execute(query)
        return list(result.scalars().all())


class AIAssessmentConfigRepository(BaseRepository[AIAssessmentConfig]):
    """
    Repository para AI assessment configs.

    Manages AI settings per project/instrument.
    """

    def __init__(self, db: AsyncSession):
        super().__init__(db, AIAssessmentConfig)

    async def get_active(
        self,
        project_id: UUID,
        instrument_id: UUID | None = None,
    ) -> AIAssessmentConfig | None:
        """
        Fetch active config for project/instrument.
        Args:
            project_id: Project ID.
            instrument_id: Instrument ID (optional).
        Returns:
            Active config or None.
        """
        query = (
            select(AIAssessmentConfig)
            .where(
                AIAssessmentConfig.project_id == project_id,
                AIAssessmentConfig.is_active == True,  # noqa: E712
            )
            .order_by(AIAssessmentConfig.created_at.desc())
        )

        if instrument_id:
            query = query.where(AIAssessmentConfig.instrument_id == instrument_id)

        result = await self.db.execute(query.limit(1))
        return result.scalar_one_or_none()


class AIAssessmentPromptRepository(BaseRepository[AIAssessmentPrompt]):
    """
    Repository for AI assessment prompts.
    Manages custom prompts per assessment item.
    """

    def __init__(self, db: AsyncSession):
        super().__init__(db, AIAssessmentPrompt)

    async def get_by_item(
        self,
        assessment_item_id: UUID,
    ) -> AIAssessmentPrompt | None:
        """
        Fetch custom prompt for an assessment item.
        Args:
            assessment_item_id: Assessment item ID.
        Returns:
            Custom prompt or None.
        """
        result = await self.db.execute(
            select(AIAssessmentPrompt).where(
                AIAssessmentPrompt.assessment_item_id == assessment_item_id
            )
        )
        return result.scalar_one_or_none()

    async def get_or_create_default(
        self,
        assessment_item_id: UUID,
    ) -> AIAssessmentPrompt:
        """
        Fetch existing prompt or create one with default values.
        Args:
            assessment_item_id: Assessment item ID.
        Returns:
            Prompt (existing or new with defaults).
        """
        prompt = await self.get_by_item(assessment_item_id)

        if not prompt:
            prompt = AIAssessmentPrompt(assessment_item_id=assessment_item_id)
            self.db.add(prompt)
            await self.db.flush()
            await self.db.refresh(prompt)

        return prompt


# =================== NEW REPOSITORIES (Assessment 2.0 - Extraction Pattern) ===================


class AssessmentInstanceRepository(BaseRepository[AssessmentInstance]):
    """
    Repository for assessment instances.
    Analogous to ExtractionInstanceRepository. Manages assessment instances
    (PROBAST per article or per model).
    """

    def __init__(self, db: AsyncSession):
        super().__init__(db, AssessmentInstance)

    async def get_by_article(
        self,
        article_id: UUID | str,
        instrument_id: UUID | str | None = None,
    ) -> list[AssessmentInstance]:
        """
        List instances for an article.
        Args:
            article_id: Article ID.
            instrument_id: Filter by instrument (optional).
        Returns:
            List of assessment instances.
        """
        if isinstance(article_id, str):
            article_id = UUID(article_id)

        query = select(AssessmentInstance).where(AssessmentInstance.article_id == article_id)

        if instrument_id:
            if isinstance(instrument_id, str):
                instrument_id = UUID(instrument_id)
            query = query.where(AssessmentInstance.instrument_id == instrument_id)

        query = query.order_by(AssessmentInstance.created_at.desc())

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_extraction_instance(
        self,
        extraction_instance_id: UUID | str,
    ) -> list[AssessmentInstance]:
        """
        List assessment instances linked to an extraction instance.
        Useful to fetch PROBAST for a specific model.
        Args:
            extraction_instance_id: Extraction instance ID (model).
        Returns:
            List of assessment instances (e.g. PROBAST for the model).
        """
        if isinstance(extraction_instance_id, str):
            extraction_instance_id = UUID(extraction_instance_id)

        result = await self.db.execute(
            select(AssessmentInstance)
            .where(AssessmentInstance.extraction_instance_id == extraction_instance_id)
            .order_by(AssessmentInstance.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_with_responses(
        self,
        instance_id: UUID | str,
    ) -> AssessmentInstance | None:
        """
        Fetch instance with its responses loaded.
        Args:
            instance_id: Instance ID.
        Returns:
            AssessmentInstance with responses or None.
        """
        if isinstance(instance_id, str):
            instance_id = UUID(instance_id)

        result = await self.db.execute(
            select(AssessmentInstance)
            .options(selectinload(AssessmentInstance.responses))
            .where(AssessmentInstance.id == instance_id)
        )
        return result.scalar_one_or_none()

    async def get_children(
        self,
        parent_instance_id: UUID | str,
    ) -> list[AssessmentInstance]:
        """
        List child instances of an instance.
        Useful for hierarchies (e.g. PROBAST root → Domain instances).
        Args:
            parent_instance_id: Parent instance ID.
        Returns:
            List of child instances.
        """
        if isinstance(parent_instance_id, str):
            parent_instance_id = UUID(parent_instance_id)

        result = await self.db.execute(
            select(AssessmentInstance)
            .where(AssessmentInstance.parent_instance_id == parent_instance_id)
            .order_by(AssessmentInstance.created_at)
        )
        return list(result.scalars().all())

    async def get_by_project_and_reviewer(
        self,
        project_id: UUID | str,
        reviewer_id: UUID | str,
        status: str | None = None,
    ) -> list[AssessmentInstance]:
        """
        List instances for a reviewer in a project.
        Args:
            project_id: Project ID.
            reviewer_id: Reviewer ID.
            status: Filter by status (optional).
        Returns:
            List of assessment instances.
        """
        if isinstance(project_id, str):
            project_id = UUID(project_id)
        if isinstance(reviewer_id, str):
            reviewer_id = UUID(reviewer_id)

        query = (
            select(AssessmentInstance)
            .where(AssessmentInstance.project_id == project_id)
            .where(AssessmentInstance.reviewer_id == reviewer_id)
        )

        if status:
            query = query.where(AssessmentInstance.status == status)

        query = query.order_by(AssessmentInstance.updated_at.desc())

        result = await self.db.execute(query)
        return list(result.scalars().all())


class AssessmentResponseRepository(BaseRepository[AssessmentResponse]):
    """
    Repository for assessment responses.
    Analogous to ExtractedValueRepository. Manages individual responses
    to assessment items (full granularity: 1 row = 1 response).
    """

    def __init__(self, db: AsyncSession):
        super().__init__(db, AssessmentResponse)

    async def get_by_instance(
        self,
        assessment_instance_id: UUID | str,
    ) -> list[AssessmentResponse]:
        """
        List responses for an assessment instance.
        Args:
            assessment_instance_id: Instance ID.
        Returns:
            List of responses.
        """
        if isinstance(assessment_instance_id, str):
            assessment_instance_id = UUID(assessment_instance_id)

        result = await self.db.execute(
            select(AssessmentResponse)
            .where(AssessmentResponse.assessment_instance_id == assessment_instance_id)
            .order_by(AssessmentResponse.created_at)
        )
        return list(result.scalars().all())

    async def get_by_instance_and_item(
        self,
        assessment_instance_id: UUID | str,
        assessment_item_id: UUID | str,
    ) -> AssessmentResponse | None:
        """
        Fetch specific response of an instance for an item.
        Args:
            assessment_instance_id: Instance ID.
            assessment_item_id: Item ID.
        Returns:
            Response or None.
        """
        if isinstance(assessment_instance_id, str):
            assessment_instance_id = UUID(assessment_instance_id)
        if isinstance(assessment_item_id, str):
            assessment_item_id = UUID(assessment_item_id)

        result = await self.db.execute(
            select(AssessmentResponse).where(
                AssessmentResponse.assessment_instance_id == assessment_instance_id,
                AssessmentResponse.assessment_item_id == assessment_item_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_article(
        self,
        article_id: UUID | str,
        reviewer_id: UUID | str | None = None,
    ) -> list[AssessmentResponse]:
        """
        List responses for an article.
        Args:
            article_id: Article ID.
            reviewer_id: Filter by reviewer (optional).
        Returns:
            List of responses.
        """
        if isinstance(article_id, str):
            article_id = UUID(article_id)

        query = select(AssessmentResponse).where(AssessmentResponse.article_id == article_id)

        if reviewer_id:
            if isinstance(reviewer_id, str):
                reviewer_id = UUID(reviewer_id)
            query = query.where(AssessmentResponse.reviewer_id == reviewer_id)

        query = query.order_by(AssessmentResponse.created_at.desc())

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_level(
        self,
        project_id: UUID | str,
        selected_level: str,
        instrument_id: UUID | str | None = None,
    ) -> list[AssessmentResponse]:
        """
        List responses for a project with specific level.
        Useful for queries like "all High risk" or "all Low risk".
        Args:
            project_id: Project ID.
            selected_level: Selected level (e.g. "Low", "High", "Unclear").
            instrument_id: Filter by instrument (optional).
        Returns:
            List of responses.
        """
        if isinstance(project_id, str):
            project_id = UUID(project_id)

        query = (
            select(AssessmentResponse)
            .where(AssessmentResponse.project_id == project_id)
            .where(AssessmentResponse.selected_level == selected_level)
        )

        if instrument_id:
            if isinstance(instrument_id, str):
                instrument_id = UUID(instrument_id)
            # Join with assessment_instances to filter by instrument
            query = query.join(AssessmentInstance).where(
                AssessmentInstance.instrument_id == instrument_id
            )

        query = query.order_by(AssessmentResponse.created_at.desc())

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def bulk_create(
        self,
        responses: list[AssessmentResponse],
    ) -> list[AssessmentResponse]:
        """
        Create multiple responses in batch.
        Useful to accept multiple AI suggestions at once.
        Args:
            responses: List of responses to create.
        Returns:
            List of created responses.
        """
        self.db.add_all(responses)
        await self.db.flush()

        # Refresh to load IDs and timestamps
        for response in responses:
            await self.db.refresh(response)

        return responses


class AssessmentEvidenceRepository(BaseRepository[AssessmentEvidence]):
    """
    Repository for assessment evidence.
    Analogous to ExtractionEvidenceRepository. Manages evidence
    supporting responses or instances.
    """

    def __init__(self, db: AsyncSession):
        super().__init__(db, AssessmentEvidence)

    async def get_by_response(
        self,
        response_id: UUID | str,
    ) -> list[AssessmentEvidence]:
        """
        List evidence for a response.
        Args:
            response_id: Response ID.
        Returns:
            List of evidence.
        """
        if isinstance(response_id, str):
            response_id = UUID(response_id)

        result = await self.db.execute(
            select(AssessmentEvidence).where(
                AssessmentEvidence.target_type == "response",
                AssessmentEvidence.target_id == response_id,
            )
        )
        return list(result.scalars().all())

    async def get_by_instance(
        self,
        instance_id: UUID | str,
    ) -> list[AssessmentEvidence]:
        """
        List evidence for an instance.
        Args:
            instance_id: Instance ID.
        Returns:
            List of evidence.
        """
        if isinstance(instance_id, str):
            instance_id = UUID(instance_id)

        result = await self.db.execute(
            select(AssessmentEvidence).where(
                AssessmentEvidence.target_type == "instance",
                AssessmentEvidence.target_id == instance_id,
            )
        )
        return list(result.scalars().all())

    async def get_by_article(
        self,
        article_id: UUID | str,
    ) -> list[AssessmentEvidence]:
        """
        List all evidence for an article.
        Args:
            article_id: Article ID.
        Returns:
            List of evidence.
        """
        if isinstance(article_id, str):
            article_id = UUID(article_id)

        result = await self.db.execute(
            select(AssessmentEvidence)
            .where(AssessmentEvidence.article_id == article_id)
            .order_by(AssessmentEvidence.created_at.desc())
        )
        return list(result.scalars().all())


# =================== PROJECT INSTRUMENT REPOSITORIES ===================


class ProjectAssessmentInstrumentRepository(BaseRepository[ProjectAssessmentInstrument]):
    """
    Repository for project assessment instruments.
    Manages custom instruments per project (cloned or created).
    """

    def __init__(self, db: AsyncSession):
        super().__init__(db, ProjectAssessmentInstrument)

    async def get_by_project(
        self,
        project_id: UUID | str,
        active_only: bool = True,
    ) -> list[ProjectAssessmentInstrument]:
        """
        Lista instrumentos de um projeto.

        Args:
            project_id: Project ID.
            active_only: Se True, retorna apenas instrumentos ativos.

        Returns:
            Lista de instrumentos do projeto.
        """
        if isinstance(project_id, str):
            project_id = UUID(project_id)

        query = (
            select(ProjectAssessmentInstrument)
            .options(selectinload(ProjectAssessmentInstrument.items))
            .where(ProjectAssessmentInstrument.project_id == project_id)
        )

        if active_only:
            query = query.where(ProjectAssessmentInstrument.is_active == True)  # noqa: E712

        query = query.order_by(ProjectAssessmentInstrument.created_at.desc())

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_with_items(
        self,
        instrument_id: UUID | str,
    ) -> ProjectAssessmentInstrument | None:
        """
        Busca instrumento com seus items carregados.

        Args:
            instrument_id: ID do instrumento.

        Returns:
            Instrumento com items ou None.
        """
        if isinstance(instrument_id, str):
            instrument_id = UUID(instrument_id)

        result = await self.db.execute(
            select(ProjectAssessmentInstrument)
            .options(selectinload(ProjectAssessmentInstrument.items))
            .where(ProjectAssessmentInstrument.id == instrument_id)
        )
        return result.scalar_one_or_none()

    async def get_by_tool_type(
        self,
        project_id: UUID | str,
        tool_type: str,
    ) -> ProjectAssessmentInstrument | None:
        """
        Busca instrumento por tipo em um projeto.

        Args:
            project_id: Project ID.
            tool_type: Tipo do instrumento (PROBAST, ROBIS, etc.).

        Returns:
            Instrumento ou None.
        """
        if isinstance(project_id, str):
            project_id = UUID(project_id)

        result = await self.db.execute(
            select(ProjectAssessmentInstrument)
            .where(
                ProjectAssessmentInstrument.project_id == project_id,
                ProjectAssessmentInstrument.tool_type == tool_type,
                ProjectAssessmentInstrument.is_active == True,  # noqa: E712
            )
            .order_by(ProjectAssessmentInstrument.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_by_global_instrument(
        self,
        project_id: UUID | str,
        global_instrument_id: UUID | str,
    ) -> ProjectAssessmentInstrument | None:
        """
        Busca instrumento clonado de um global em um projeto.

        Args:
            project_id: Project ID.
            global_instrument_id: ID do instrumento global.

        Returns:
            Instrumento do projeto ou None.
        """
        if isinstance(project_id, str):
            project_id = UUID(project_id)
        if isinstance(global_instrument_id, str):
            global_instrument_id = UUID(global_instrument_id)

        result = await self.db.execute(
            select(ProjectAssessmentInstrument).where(
                ProjectAssessmentInstrument.project_id == project_id,
                ProjectAssessmentInstrument.global_instrument_id == global_instrument_id,
            )
        )
        return result.scalar_one_or_none()


class ProjectAssessmentItemRepository(BaseRepository[ProjectAssessmentItem]):
    """
    Repository for project assessment items.
    Manages custom instrument items.
    """

    def __init__(self, db: AsyncSession):
        super().__init__(db, ProjectAssessmentItem)

    async def get_by_instrument(
        self,
        project_instrument_id: UUID | str,
    ) -> list[ProjectAssessmentItem]:
        """
        Lista items de um instrumento.

        Args:
            project_instrument_id: ID do instrumento do projeto.

        Returns:
            Lista de items ordenados por sort_order.
        """
        if isinstance(project_instrument_id, str):
            project_instrument_id = UUID(project_instrument_id)

        result = await self.db.execute(
            select(ProjectAssessmentItem)
            .where(ProjectAssessmentItem.project_instrument_id == project_instrument_id)
            .order_by(ProjectAssessmentItem.sort_order)
        )
        return list(result.scalars().all())

    async def get_by_domain(
        self,
        project_instrument_id: UUID | str,
        domain: str,
    ) -> list[ProjectAssessmentItem]:
        """
        List items for a specific domain.
        Args:
            project_instrument_id: Project instrument ID.
            domain: Domain name (e.g. "participants", "predictors").
        Returns:
            Sorted list of domain items.
        """
        if isinstance(project_instrument_id, str):
            project_instrument_id = UUID(project_instrument_id)

        result = await self.db.execute(
            select(ProjectAssessmentItem)
            .where(
                ProjectAssessmentItem.project_instrument_id == project_instrument_id,
                ProjectAssessmentItem.domain == domain,
            )
            .order_by(ProjectAssessmentItem.sort_order)
        )
        return list(result.scalars().all())

    async def get_by_item_code(
        self,
        project_instrument_id: UUID | str,
        item_code: str,
    ) -> ProjectAssessmentItem | None:
        """
        Fetch item by unique code within the instrument.
        Args:
            project_instrument_id: Project instrument ID.
            item_code: Item code (e.g. "1.1", "2.3").
        Returns:
            Item or None.
        """
        if isinstance(project_instrument_id, str):
            project_instrument_id = UUID(project_instrument_id)

        result = await self.db.execute(
            select(ProjectAssessmentItem).where(
                ProjectAssessmentItem.project_instrument_id == project_instrument_id,
                ProjectAssessmentItem.item_code == item_code,
            )
        )
        return result.scalar_one_or_none()

    async def bulk_create(
        self,
        items: list[ProjectAssessmentItem],
    ) -> list[ProjectAssessmentItem]:
        """
        Create multiple items in batch.
        Useful to clone all items from a global instrument.
        Args:
            items: List of items to create.
        Returns:
            List of created items.
        """
        self.db.add_all(items)
        await self.db.flush()

        for item in items:
            await self.db.refresh(item)

        return items
