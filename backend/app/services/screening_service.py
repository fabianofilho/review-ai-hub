"""
Screening Service.

Core business logic for the article screening workflow:
decisions, conflicts, progress, inter-rater reliability.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import LoggerMixin
from app.models.article import Article
from app.models.screening import (
    ScreeningConfig,
    ScreeningConflict,
    ScreeningDecision,
)
from app.repositories.article_repository import ArticleRepository
from app.repositories.screening_repository import (
    ScreeningConfigRepository,
    ScreeningConflictRepository,
    ScreeningDecisionRepository,
)
from app.schemas.screening import (
    PRISMAFlowData,
    ScreeningProgressStats,
)


class ScreeningService(LoggerMixin):
    """Service for managing screening workflow."""

    def __init__(self, db: AsyncSession, user_id: str | UUID):
        self.db = db
        self.user_id = str(user_id)
        self.config_repo = ScreeningConfigRepository(db)
        self.decision_repo = ScreeningDecisionRepository(db)
        self.conflict_repo = ScreeningConflictRepository(db)
        self.article_repo = ArticleRepository(db)

    # =================== CONFIG ===================

    async def upsert_config(
        self,
        project_id: UUID,
        phase: str,
        require_dual_review: bool = False,
        blind_mode: bool = False,
        criteria: list[dict[str, Any]] | None = None,
        ai_model_name: str | None = "gpt-4o-mini",
        ai_system_instruction: str | None = None,
    ) -> ScreeningConfig:
        """Create or update screening config for a project/phase."""
        existing = await self.config_repo.get_by_project_and_phase(project_id, phase)

        if existing:
            return await self.config_repo.update(
                existing,
                {
                    "require_dual_review": require_dual_review,
                    "blind_mode": blind_mode,
                    "criteria": criteria or [],
                    "ai_model_name": ai_model_name,
                    "ai_system_instruction": ai_system_instruction,
                },
            )

        config = ScreeningConfig(
            project_id=project_id,
            phase=phase,
            require_dual_review=require_dual_review,
            blind_mode=blind_mode,
            criteria=criteria or [],
            ai_model_name=ai_model_name,
            ai_system_instruction=ai_system_instruction,
            created_by=UUID(self.user_id),
        )
        return await self.config_repo.create(config)

    # =================== DECISIONS ===================

    async def create_decision(
        self,
        project_id: UUID,
        article_id: UUID,
        phase: str,
        decision: str,
        reason: str | None = None,
        criteria_responses: dict[str, Any] | None = None,
    ) -> ScreeningDecision:
        """
        Submit a screening decision.

        If dual review is active and both reviewers have decided,
        automatically detects conflicts.
        """
        await self.article_repo.ensure_in_project([article_id], project_id)
        reviewer_id = UUID(self.user_id)

        # Check for existing decision (update if exists)
        existing = await self.decision_repo.get_existing_decision(
            project_id, article_id, reviewer_id, phase
        )

        if existing:
            return await self.decision_repo.update(
                existing,
                {
                    "decision": decision,
                    "reason": reason,
                    "criteria_responses": criteria_responses or {},
                },
            )

        # Create new decision
        screening_decision = ScreeningDecision(
            project_id=project_id,
            article_id=article_id,
            reviewer_id=reviewer_id,
            phase=phase,
            decision=decision,
            reason=reason,
            criteria_responses=criteria_responses or {},
        )
        created = await self.decision_repo.create(screening_decision)

        # Check for dual review conflicts
        config = await self.config_repo.get_by_project_and_phase(project_id, phase)
        if config and config.require_dual_review:
            await self._check_and_create_conflict(project_id, article_id, phase)

        # Update article screening_phase (denormalized)
        await self._update_article_screening_phase(article_id, phase, decision)

        return created

    async def _check_and_create_conflict(
        self, project_id: UUID, article_id: UUID, phase: str
    ) -> None:
        """Check if two reviewers disagree and create a conflict."""
        decisions = await self.decision_repo.get_by_article(project_id, article_id, phase)

        if len(decisions) < 2:
            return

        # Compare first two decisions
        d1, d2 = decisions[0], decisions[1]
        if d1.decision != d2.decision:
            # Check if conflict already exists
            existing = await self.conflict_repo.get_by_article(project_id, article_id, phase)
            if not existing:
                conflict = ScreeningConflict(
                    project_id=project_id,
                    article_id=article_id,
                    phase=phase,
                    decision_1_id=d1.id,
                    decision_2_id=d2.id,
                    status="conflict",
                )
                await self.conflict_repo.create(conflict)

    async def _update_article_screening_phase(
        self, article_id: UUID, phase: str, decision: str
    ) -> None:
        """Update the denormalized screening_phase on the article."""
        await self.article_repo.update_screening_phase(article_id, phase, decision)

    # =================== CONFLICTS ===================

    async def resolve_conflict(
        self,
        conflict_id: UUID,
        decision: str,
        reason: str | None = None,
    ) -> ScreeningConflict:
        """Resolve a screening conflict."""
        conflict = await self.conflict_repo.get_by_id(conflict_id)
        if not conflict:
            raise ValueError("Conflict not found")

        updated = await self.conflict_repo.update(
            conflict,
            {
                "status": "resolved",
                "resolved_by": UUID(self.user_id),
                "resolved_decision": decision,
                "resolved_reason": reason,
                "resolved_at": datetime.now(UTC),
            },
        )

        # Update article screening phase based on resolution
        await self._update_article_screening_phase(conflict.article_id, conflict.phase, decision)

        return updated

    # =================== PROGRESS ===================

    async def get_progress(self, project_id: UUID, phase: str) -> ScreeningProgressStats:
        """Get screening progress statistics."""
        # Total articles in project
        total_result = await self.db.execute(
            select(func.count(Article.id)).where(Article.project_id == project_id)
        )
        total = total_result.scalar_one()

        # Count decisions by type
        decision_counts = await self.decision_repo.count_by_decision(project_id, phase)
        screened = await self.decision_repo.count_screened_articles(project_id, phase)
        conflicts = await self.conflict_repo.count_unresolved(project_id, phase)

        return ScreeningProgressStats(
            total_articles=total,
            screened=screened,
            pending=total - screened,
            included=decision_counts.get("include", 0),
            excluded=decision_counts.get("exclude", 0),
            maybe=decision_counts.get("maybe", 0),
            conflicts=conflicts,
        )

    async def get_prisma_counts(self, project_id: UUID) -> PRISMAFlowData:
        """Get PRISMA 2020 flow diagram counts."""
        total_result = await self.db.execute(
            select(func.count(Article.id)).where(Article.project_id == project_id)
        )
        total = total_result.scalar_one()

        # Title/abstract screening
        ta_screened = await self.decision_repo.count_screened_articles(project_id, "title_abstract")
        ta_counts = await self.decision_repo.count_by_decision(project_id, "title_abstract")

        # Full-text screening
        ft_screened = await self.decision_repo.count_screened_articles(project_id, "full_text")
        ft_counts = await self.decision_repo.count_by_decision(project_id, "full_text")

        return PRISMAFlowData(
            total_imported=total,
            duplicates_removed=0,  # TODO: track duplicates
            title_abstract_screened=ta_screened,
            title_abstract_excluded=ta_counts.get("exclude", 0),
            full_text_assessed=ft_screened,
            full_text_excluded=ft_counts.get("exclude", 0),
            included=ft_counts.get("include", 0),
        )

    # =================== INTER-RATER RELIABILITY ===================

    async def compute_cohens_kappa(self, project_id: UUID, phase: str) -> float | None:
        """
        Compute Cohen's Kappa for dual-reviewer agreement.

        Returns None if fewer than 2 reviewers or no overlapping decisions.
        """
        # Get all decisions for this phase
        result = await self.db.execute(
            select(ScreeningDecision).where(
                and_(
                    ScreeningDecision.project_id == project_id,
                    ScreeningDecision.phase == phase,
                )
            )
        )
        decisions = list(result.scalars().all())

        if not decisions:
            return None

        # Group by article
        by_article: dict[UUID, list[ScreeningDecision]] = {}
        for d in decisions:
            by_article.setdefault(d.article_id, []).append(d)

        # Only consider articles with exactly 2 decisions
        pairs = [ds for ds in by_article.values() if len(ds) == 2]
        if len(pairs) < 2:
            return None

        # Build agreement matrix
        categories = ["include", "exclude", "maybe"]
        n = len(pairs)
        agree = sum(1 for p in pairs if p[0].decision == p[1].decision)

        # Observed agreement
        po = agree / n

        # Expected agreement by chance
        cat_counts_1 = dict.fromkeys(categories, 0)
        cat_counts_2 = dict.fromkeys(categories, 0)
        for p in pairs:
            d1, d2 = p[0].decision, p[1].decision
            if d1 in cat_counts_1:
                cat_counts_1[d1] += 1
            if d2 in cat_counts_2:
                cat_counts_2[d2] += 1

        pe = sum((cat_counts_1.get(c, 0) / n) * (cat_counts_2.get(c, 0) / n) for c in categories)

        if pe == 1.0:
            return 1.0

        kappa = (po - pe) / (1 - pe)
        return round(kappa, 4)

    # =================== BULK OPERATIONS ===================

    async def bulk_decide(
        self,
        project_id: UUID,
        article_ids: list[UUID],
        phase: str,
        decision: str,
        reason: str | None = None,
    ) -> int:
        """Bulk-decide multiple articles. Returns count of decisions created."""
        count = 0
        for article_id in article_ids:
            await self.create_decision(
                project_id=project_id,
                article_id=article_id,
                phase=phase,
                decision=decision,
                reason=reason,
            )
            count += 1
        return count

    async def advance_to_fulltext(
        self,
        project_id: UUID,
        article_ids: list[UUID] | None = None,
    ) -> int:
        """
        Advance included articles from title/abstract to full-text phase.

        If article_ids is None, advances all included articles.
        Returns count of articles advanced.
        """
        if article_ids:
            # Only articles of this project can be advanced.
            articles = await self.article_repo.get_by_ids(article_ids, project_id)
        else:
            # Get all articles included in title/abstract phase
            result = await self.db.execute(
                select(Article).where(
                    and_(
                        Article.project_id == project_id,
                        Article.screening_phase == "title_abstract",
                    )
                )
            )
            articles = list(result.scalars().all())

        count = 0
        for article in articles:
            article.screening_phase = "full_text"
            count += 1

        await self.db.flush()
        return count
