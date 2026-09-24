"""
Screening Models.

Models for the article screening workflow: configuration, decisions,
conflicts, and AI screening runs.
"""

from datetime import datetime
from enum import Enum as PyEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, BaseModel, PostgreSQLEnumType, UUIDMixin

if TYPE_CHECKING:
    from app.models.extraction import AISuggestion

# =============================================================================
# PYTHON ENUMS (mirrors PostgreSQL ENUM types)
# =============================================================================


class ScreeningPhase(str, PyEnum):
    """Phase of the screening process."""

    TITLE_ABSTRACT = "title_abstract"
    FULL_TEXT = "full_text"


class ScreeningDecisionValue(str, PyEnum):
    """Reviewer's screening decision."""

    INCLUDE = "include"
    EXCLUDE = "exclude"
    MAYBE = "maybe"


class ScreeningConflictStatusValue(str, PyEnum):
    """Status of a screening conflict."""

    NONE = "none"
    CONFLICT = "conflict"
    RESOLVED = "resolved"


# =============================================================================
# MODELS
# =============================================================================


class ScreeningConfig(BaseModel):
    """
    Project-level screening configuration per phase.

    Stores inclusion/exclusion criteria and settings for
    dual-review, blind mode, and AI-assisted screening.
    """

    __tablename__ = "screening_configs"

    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    phase: Mapped[str] = mapped_column(
        PostgreSQLEnumType("screening_phase"),
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    require_dual_review: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    blind_mode: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    # Array of {id, type: "inclusion"|"exclusion", label, description}
    criteria: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        default=[],
        nullable=False,
    )

    ai_model_name: Mapped[str | None] = mapped_column(
        String(100),
        default="gpt-4o-mini",
        nullable=True,
    )

    ai_system_instruction: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.profiles.id", ondelete="RESTRICT"),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("project_id", "phase", name="uq_screening_configs_project_phase"),
        Index("idx_screening_configs_criteria_gin", "criteria", postgresql_using="gin"),
        {"schema": "public"},
    )

    def __repr__(self) -> str:
        return f"<ScreeningConfig project={self.project_id} phase={self.phase}>"


class ScreeningDecision(BaseModel):
    """
    Individual reviewer's screening decision for an article.

    One record per (project, article, reviewer, phase).
    """

    __tablename__ = "screening_decisions"

    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    article_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.articles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    reviewer_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    phase: Mapped[str] = mapped_column(
        PostgreSQLEnumType("screening_phase"),
        nullable=False,
    )

    decision: Mapped[str] = mapped_column(
        PostgreSQLEnumType("screening_decision"),
        nullable=False,
    )

    reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # Per-criterion boolean responses: {criterion_id: true/false}
    criteria_responses: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default={},
        nullable=False,
    )

    is_ai_assisted: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    ai_suggestion_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.ai_suggestions.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "article_id",
            "reviewer_id",
            "phase",
            name="uq_screening_decisions_article_reviewer_phase",
        ),
        Index(
            "idx_screening_decisions_criteria_gin",
            "criteria_responses",
            postgresql_using="gin",
        ),
        {"schema": "public"},
    )

    def __repr__(self) -> str:
        return f"<ScreeningDecision article={self.article_id} decision={self.decision}>"


class ScreeningConflict(BaseModel):
    """
    Tracks conflicts between dual reviewers for the same article.

    Created automatically when two reviewers disagree.
    """

    __tablename__ = "screening_conflicts"

    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    article_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.articles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    phase: Mapped[str] = mapped_column(
        PostgreSQLEnumType("screening_phase"),
        nullable=False,
    )

    decision_1_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.screening_decisions.id", ondelete="CASCADE"),
        nullable=False,
    )

    decision_2_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.screening_decisions.id", ondelete="CASCADE"),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        PostgreSQLEnumType("screening_conflict_status"),
        default="conflict",
        nullable=False,
    )

    resolved_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.profiles.id", ondelete="SET NULL"),
        nullable=True,
    )

    resolved_decision: Mapped[str | None] = mapped_column(
        PostgreSQLEnumType("screening_decision"),
        nullable=True,
    )

    resolved_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "article_id",
            "phase",
            name="uq_screening_conflicts_article_phase",
        ),
        {"schema": "public"},
    )

    def __repr__(self) -> str:
        return f"<ScreeningConflict article={self.article_id} status={self.status}>"


class ScreeningRun(Base, UUIDMixin):
    """
    AI screening run tracking.

    Follows the same pattern as ExtractionRun for batch AI operations.
    """

    __tablename__ = "screening_runs"

    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    phase: Mapped[str] = mapped_column(
        PostgreSQLEnumType("screening_phase"),
        nullable=False,
    )

    stage: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        PostgreSQLEnumType("extraction_run_status"),  # Reuse existing enum
        default="pending",
        nullable=False,
    )

    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, default={}, nullable=False)
    results: Mapped[dict[str, Any]] = mapped_column(JSONB, default={}, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.profiles.id", ondelete="RESTRICT"),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    suggestions: Mapped[list["AISuggestion"]] = relationship(
        "AISuggestion",
        foreign_keys="AISuggestion.screening_run_id",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_screening_runs_status", "status"),
        Index("idx_screening_runs_parameters_gin", "parameters", postgresql_using="gin"),
        Index("idx_screening_runs_results_gin", "results", postgresql_using="gin"),
        {"schema": "public"},
    )

    def __repr__(self) -> str:
        return f"<ScreeningRun {self.id} status={self.status}>"
