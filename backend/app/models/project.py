"""
Project Models.

Models for systematic review projects and members.
"""

from datetime import datetime
from enum import Enum as PyEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel, PostgreSQLEnumType

if TYPE_CHECKING:
    from app.models.article import Article
    from app.models.assessment import ProjectAssessmentInstrument
    from app.models.user import Profile


class ReviewType(str, PyEnum):
    """
    Type of systematic review.

    Values aligned with PostgreSQL 'review_type' enum.
    """

    INTERVENTIONAL = "interventional"
    PREDICTIVE_MODEL = "predictive_model"
    DIAGNOSTIC = "diagnostic"
    PROGNOSTIC = "prognostic"
    QUALITATIVE = "qualitative"
    OTHER = "other"


class ProjectMemberRole(str, PyEnum):
    """
    Papel do membro no projeto.

    Values aligned with PostgreSQL 'project_member_role' enum.
    """

    MANAGER = "manager"
    REVIEWER = "reviewer"
    VIEWER = "viewer"
    CONSENSUS = "consensus"


class Project(BaseModel):
    """
    Systematic review project.
    Contains settings, members and associated articles.
    """

    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.profiles.id", ondelete="RESTRICT"),
        nullable=False,
    )

    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default={"blind_mode": False},
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Review fields
    review_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    condition_studied: Mapped[str | None] = mapped_column(String, nullable=True)
    review_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_keywords: Mapped[list[str]] = mapped_column(JSONB, default=[], nullable=False)
    eligibility_criteria: Mapped[dict[str, Any]] = mapped_column(JSONB, default={}, nullable=False)
    study_design: Mapped[dict[str, Any]] = mapped_column(JSONB, default={}, nullable=False)
    review_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    search_strategy: Mapped[str | None] = mapped_column(Text, nullable=True)

    risk_of_bias_instrument_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
    )

    # PICOTS configuration for predictive model reviews
    picots_config_ai_review: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        default={
            "population": "",
            "index_models": "",
            "comparator_models": "",
            "outcomes": "",
            "timing": {"prediction_moment": "", "prediction_horizon": ""},
            "setting_and_intended_use": "",
        },
    )

    review_type: Mapped[str] = mapped_column(
        PostgreSQLEnumType("review_type"),
        default="interventional",
        nullable=True,
    )

    assessment_scope: Mapped[str] = mapped_column(
        String,
        default="article",
        nullable=True,
    )

    assessment_entity_type_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.extraction_entity_types.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    created_by: Mapped["Profile"] = relationship(
        "Profile",
        back_populates="projects_created",
        foreign_keys=[created_by_id],
    )
    members: Mapped[list["ProjectMember"]] = relationship(
        "ProjectMember",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    articles: Mapped[list["Article"]] = relationship(
        "Article",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    assessment_instruments: Mapped[list["ProjectAssessmentInstrument"]] = relationship(
        "ProjectAssessmentInstrument",
        back_populates="project",
        cascade="all, delete-orphan",
    )

    # Índices definidos via __table_args__
    __table_args__ = (
        # GIN indexes for JSONB fields (efficient search with @>, ?, etc.)
        Index("idx_projects_settings_gin", "settings", postgresql_using="gin"),
        Index("idx_projects_review_keywords_gin", "review_keywords", postgresql_using="gin"),
        Index(
            "idx_projects_eligibility_criteria_gin", "eligibility_criteria", postgresql_using="gin"
        ),
        Index("idx_projects_study_design_gin", "study_design", postgresql_using="gin"),
        {"schema": "public"},
    )

    def __repr__(self) -> str:
        return f"<Project {self.name}>"


class ProjectMember(BaseModel):
    """
    Project member with role and permissions.

    Índices:
    - project_id, user_id: FKs indexadas
    - (project_id, user_id): unique constraint
    """

    __tablename__ = "project_members"

    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    role: Mapped[str] = mapped_column(
        PostgreSQLEnumType("project_member_role"),
        default="reviewer",
        nullable=False,
    )

    permissions: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default={"can_export": False},
        nullable=False,
    )

    # Campos de convite
    invitation_email: Mapped[str | None] = mapped_column(Text, nullable=True)
    invitation_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    invitation_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    invitation_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_by_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.profiles.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    project: Mapped["Project"] = relationship(
        "Project",
        back_populates="members",
    )
    user: Mapped["Profile"] = relationship(
        "Profile",
        back_populates="project_memberships",
        foreign_keys=[user_id],
    )

    # Índices definidos via __table_args__
    __table_args__ = (
        # Unique constraint to avoid duplicates
        UniqueConstraint("project_id", "user_id", name="uq_project_user"),
        {"schema": "public"},
    )

    def __repr__(self) -> str:
        return f"<ProjectMember project={self.project_id} user={self.user_id}>"
