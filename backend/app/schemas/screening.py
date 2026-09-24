"""
Screening Schemas.

Pydantic schemas for the screening workflow.
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# =================== CRITERIA ===================


class ScreeningCriterion(BaseModel):
    """Single inclusion/exclusion criterion."""

    id: str
    type: Literal["inclusion", "exclusion"]
    label: str
    description: str | None = None

    model_config = ConfigDict(populate_by_name=True)


# =================== CONFIG ===================


class ScreeningConfigCreate(BaseModel):
    """Request to create or update screening config."""

    project_id: UUID = Field(..., alias="projectId")
    phase: Literal["title_abstract", "full_text"]
    require_dual_review: bool = Field(default=False, alias="requireDualReview")
    blind_mode: bool = Field(default=False, alias="blindMode")
    criteria: list[ScreeningCriterion] = []
    ai_model_name: str | None = Field(default="gpt-4o-mini", alias="aiModelName")
    ai_system_instruction: str | None = Field(default=None, alias="aiSystemInstruction")

    model_config = ConfigDict(populate_by_name=True)


class ScreeningConfigResponse(BaseModel):
    """Response for screening config."""

    id: UUID
    project_id: UUID = Field(..., alias="projectId")
    phase: str
    is_active: bool = Field(..., alias="isActive")
    require_dual_review: bool = Field(..., alias="requireDualReview")
    blind_mode: bool = Field(..., alias="blindMode")
    criteria: list[ScreeningCriterion]
    ai_model_name: str | None = Field(default=None, alias="aiModelName")
    ai_system_instruction: str | None = Field(default=None, alias="aiSystemInstruction")
    created_at: datetime = Field(..., alias="createdAt")
    updated_at: datetime = Field(..., alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


# =================== DECISIONS ===================


class ScreeningDecisionCreate(BaseModel):
    """Request to submit a screening decision."""

    project_id: UUID = Field(..., alias="projectId")
    article_id: UUID = Field(..., alias="articleId")
    phase: Literal["title_abstract", "full_text"]
    decision: Literal["include", "exclude", "maybe"]
    reason: str | None = None
    criteria_responses: dict[str, bool] = Field(default={}, alias="criteriaResponses")

    model_config = ConfigDict(populate_by_name=True)


class ScreeningDecisionResponse(BaseModel):
    """Response for a screening decision."""

    id: UUID
    project_id: UUID = Field(..., alias="projectId")
    article_id: UUID = Field(..., alias="articleId")
    reviewer_id: UUID = Field(..., alias="reviewerId")
    phase: str
    decision: str
    reason: str | None = None
    criteria_responses: dict[str, bool] = Field(default={}, alias="criteriaResponses")
    is_ai_assisted: bool = Field(default=False, alias="isAiAssisted")
    created_at: datetime = Field(..., alias="createdAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


# =================== CONFLICTS ===================


class ScreeningConflictResponse(BaseModel):
    """Response for a screening conflict."""

    id: UUID
    project_id: UUID = Field(..., alias="projectId")
    article_id: UUID = Field(..., alias="articleId")
    phase: str
    status: str
    resolved_by: UUID | None = Field(default=None, alias="resolvedBy")
    resolved_decision: str | None = Field(default=None, alias="resolvedDecision")
    resolved_reason: str | None = Field(default=None, alias="resolvedReason")
    resolved_at: datetime | None = Field(default=None, alias="resolvedAt")
    created_at: datetime = Field(..., alias="createdAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class ResolveConflictRequest(BaseModel):
    """Request to resolve a conflict."""

    decision: Literal["include", "exclude", "maybe"]
    reason: str | None = None

    model_config = ConfigDict(populate_by_name=True)


# =================== PROGRESS / DASHBOARD ===================


class ScreeningProgressStats(BaseModel):
    """Progress statistics for a screening phase."""

    total_articles: int = Field(..., alias="totalArticles")
    screened: int
    pending: int
    included: int
    excluded: int
    maybe: int
    conflicts: int

    model_config = ConfigDict(populate_by_name=True)


class PRISMAFlowData(BaseModel):
    """PRISMA 2020 flow diagram counts."""

    total_imported: int = Field(..., alias="totalImported")
    duplicates_removed: int = Field(default=0, alias="duplicatesRemoved")
    title_abstract_screened: int = Field(default=0, alias="titleAbstractScreened")
    title_abstract_excluded: int = Field(default=0, alias="titleAbstractExcluded")
    full_text_assessed: int = Field(default=0, alias="fullTextAssessed")
    full_text_excluded: int = Field(default=0, alias="fullTextExcluded")
    included: int = 0

    model_config = ConfigDict(populate_by_name=True)


class ScreeningDashboardData(BaseModel):
    """Aggregated dashboard data."""

    title_abstract_progress: ScreeningProgressStats | None = Field(
        default=None, alias="titleAbstractProgress"
    )
    full_text_progress: ScreeningProgressStats | None = Field(
        default=None, alias="fullTextProgress"
    )
    prisma: PRISMAFlowData
    cohens_kappa: float | None = Field(default=None, alias="cohensKappa")

    model_config = ConfigDict(populate_by_name=True)


# =================== AI SCREENING ===================


class AIScreeningRequest(BaseModel):
    """Request to AI-screen a single article."""

    project_id: UUID = Field(..., alias="projectId")
    article_id: UUID = Field(..., alias="articleId")
    phase: Literal["title_abstract", "full_text"]
    model: str | None = None

    model_config = ConfigDict(populate_by_name=True)


class BatchAIScreeningRequest(BaseModel):
    """Request to AI-screen multiple articles."""

    project_id: UUID = Field(..., alias="projectId")
    article_ids: list[UUID] = Field(..., alias="articleIds")
    phase: Literal["title_abstract", "full_text"]
    model: str | None = None

    model_config = ConfigDict(populate_by_name=True)


class AIScreeningSuggestion(BaseModel):
    """AI screening suggestion."""

    id: UUID
    article_id: UUID = Field(..., alias="articleId")
    decision: str
    relevance_score: float | None = Field(default=None, alias="relevanceScore")
    reasoning: str | None = None
    criteria_evaluations: list[dict[str, Any]] = Field(default=[], alias="criteriaEvaluations")
    status: str
    created_at: datetime = Field(..., alias="createdAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


# =================== BULK OPERATIONS ===================


class BulkDecideRequest(BaseModel):
    """Request to bulk-decide articles."""

    project_id: UUID = Field(..., alias="projectId")
    article_ids: list[UUID] = Field(..., alias="articleIds")
    phase: Literal["title_abstract", "full_text"]
    decision: Literal["include", "exclude", "maybe"]
    reason: str | None = None

    model_config = ConfigDict(populate_by_name=True)


class AdvanceToFullTextRequest(BaseModel):
    """Request to advance included articles to full-text phase."""

    project_id: UUID = Field(..., alias="projectId")
    article_ids: list[UUID] | None = Field(default=None, alias="articleIds")

    model_config = ConfigDict(populate_by_name=True)
