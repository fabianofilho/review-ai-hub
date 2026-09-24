"""
Screening Repositories.

Data access layer for the screening workflow models.
"""

from datetime import UTC
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.screening import (
    ScreeningConfig,
    ScreeningConflict,
    ScreeningDecision,
    ScreeningRun,
)
from app.repositories.base import BaseRepository


class ScreeningConfigRepository(BaseRepository[ScreeningConfig]):
    """Repository for screening configuration."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, ScreeningConfig)

    async def get_by_project_and_phase(
        self, project_id: UUID | str, phase: str
    ) -> ScreeningConfig | None:
        """Get config for a project and phase."""
        result = await self.db.execute(
            select(ScreeningConfig).where(
                and_(
                    ScreeningConfig.project_id == project_id,
                    ScreeningConfig.phase == phase,
                )
            )
        )
        return result.scalar_one_or_none()


class ScreeningDecisionRepository(BaseRepository[ScreeningDecision]):
    """Repository for screening decisions."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, ScreeningDecision)

    async def get_by_article(
        self, project_id: UUID | str, article_id: UUID | str, phase: str
    ) -> list[ScreeningDecision]:
        """Get all decisions for an article in a phase."""
        result = await self.db.execute(
            select(ScreeningDecision).where(
                and_(
                    ScreeningDecision.project_id == project_id,
                    ScreeningDecision.article_id == article_id,
                    ScreeningDecision.phase == phase,
                )
            )
        )
        return list(result.scalars().all())

    async def get_by_reviewer(
        self, project_id: UUID | str, reviewer_id: UUID | str, phase: str
    ) -> list[ScreeningDecision]:
        """Get all decisions by a reviewer."""
        result = await self.db.execute(
            select(ScreeningDecision).where(
                and_(
                    ScreeningDecision.project_id == project_id,
                    ScreeningDecision.reviewer_id == reviewer_id,
                    ScreeningDecision.phase == phase,
                )
            )
        )
        return list(result.scalars().all())

    async def get_existing_decision(
        self,
        project_id: UUID | str,
        article_id: UUID | str,
        reviewer_id: UUID | str,
        phase: str,
    ) -> ScreeningDecision | None:
        """Get existing decision for a specific article/reviewer/phase."""
        result = await self.db.execute(
            select(ScreeningDecision).where(
                and_(
                    ScreeningDecision.project_id == project_id,
                    ScreeningDecision.article_id == article_id,
                    ScreeningDecision.reviewer_id == reviewer_id,
                    ScreeningDecision.phase == phase,
                )
            )
        )
        return result.scalar_one_or_none()

    async def count_by_decision(self, project_id: UUID | str, phase: str) -> dict[str, int]:
        """Count decisions grouped by decision value."""
        result = await self.db.execute(
            select(
                ScreeningDecision.decision,
                func.count(ScreeningDecision.id),
            )
            .where(
                and_(
                    ScreeningDecision.project_id == project_id,
                    ScreeningDecision.phase == phase,
                )
            )
            .group_by(ScreeningDecision.decision)
        )
        return {row[0]: row[1] for row in result.all()}

    async def count_screened_articles(self, project_id: UUID | str, phase: str) -> int:
        """Count distinct articles that have been screened."""
        result = await self.db.execute(
            select(func.count(func.distinct(ScreeningDecision.article_id))).where(
                and_(
                    ScreeningDecision.project_id == project_id,
                    ScreeningDecision.phase == phase,
                )
            )
        )
        return result.scalar_one()


class ScreeningConflictRepository(BaseRepository[ScreeningConflict]):
    """Repository for screening conflicts."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, ScreeningConflict)

    async def get_unresolved(self, project_id: UUID | str, phase: str) -> list[ScreeningConflict]:
        """Get all unresolved conflicts."""
        result = await self.db.execute(
            select(ScreeningConflict).where(
                and_(
                    ScreeningConflict.project_id == project_id,
                    ScreeningConflict.phase == phase,
                    ScreeningConflict.status == "conflict",
                )
            )
        )
        return list(result.scalars().all())

    async def get_by_article(
        self, project_id: UUID | str, article_id: UUID | str, phase: str
    ) -> ScreeningConflict | None:
        """Get conflict for a specific article/phase."""
        result = await self.db.execute(
            select(ScreeningConflict).where(
                and_(
                    ScreeningConflict.project_id == project_id,
                    ScreeningConflict.article_id == article_id,
                    ScreeningConflict.phase == phase,
                )
            )
        )
        return result.scalar_one_or_none()

    async def count_unresolved(self, project_id: UUID | str, phase: str) -> int:
        """Count unresolved conflicts."""
        result = await self.db.execute(
            select(func.count()).where(
                and_(
                    ScreeningConflict.project_id == project_id,
                    ScreeningConflict.phase == phase,
                    ScreeningConflict.status == "conflict",
                )
            )
        )
        return result.scalar_one()


class ScreeningRunRepository(BaseRepository[ScreeningRun]):
    """Repository for AI screening runs."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, ScreeningRun)

    async def create_run(
        self,
        project_id: UUID | str,
        phase: str,
        stage: str,
        created_by: UUID | str,
        parameters: dict | None = None,
    ) -> ScreeningRun:
        """Create a new screening run."""
        run = ScreeningRun(
            project_id=project_id,
            phase=phase,
            stage=stage,
            status="pending",
            parameters=parameters or {},
            results={},
            created_by=created_by,
        )
        return await self.create(run)

    async def start_run(self, run_id: UUID | str) -> ScreeningRun | None:
        """Mark a run as started."""
        from datetime import datetime

        run = await self.get_by_id(run_id)
        if run:
            return await self.update(run, {"status": "running", "started_at": datetime.now(UTC)})
        return None

    async def complete_run(self, run_id: UUID | str, results: dict) -> ScreeningRun | None:
        """Mark a run as completed."""
        from datetime import datetime

        run = await self.get_by_id(run_id)
        if run:
            return await self.update(
                run,
                {
                    "status": "completed",
                    "results": results,
                    "completed_at": datetime.now(UTC),
                },
            )
        return None

    async def fail_run(self, run_id: UUID | str, error_message: str) -> ScreeningRun | None:
        """Mark a run as failed."""
        from datetime import datetime

        run = await self.get_by_id(run_id)
        if run:
            return await self.update(
                run,
                {
                    "status": "failed",
                    "error_message": error_message,
                    "completed_at": datetime.now(UTC),
                },
            )
        return None
