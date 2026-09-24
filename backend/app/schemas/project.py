"""
Project Schemas.

Schemas Pydantic para projetos de revisão sistemática.
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# =================== PICOTS CONFIG ===================


class TimingConfig(BaseModel):
    """Configuração de timing para PICOTS."""

    prediction_moment: str = Field(default="", alias="predictionMoment")
    prediction_horizon: str = Field(default="", alias="predictionHorizon")

    model_config = ConfigDict(populate_by_name=True)


class PICOTSConfig(BaseModel):
    """Configuração PICOTS para revisões de modelos preditivos."""

    population: str = ""
    index_models: str = Field(default="", alias="indexModels")
    comparator_models: str = Field(default="", alias="comparatorModels")
    outcomes: str = ""
    timing: TimingConfig = Field(default_factory=TimingConfig)
    setting_and_intended_use: str = Field(default="", alias="settingAndIntendedUse")

    model_config = ConfigDict(populate_by_name=True)


# =================== PROJECT SETTINGS ===================


class ProjectSettings(BaseModel):
    """Configurações do projeto."""

    blind_mode: bool = Field(default=False, alias="blindMode")
    require_dual_review: bool = Field(default=True, alias="requireDualReview")
    auto_consensus: bool = Field(default=False, alias="autoConsensus")

    model_config = ConfigDict(populate_by_name=True)


# =================== PROJECT SCHEMAS ===================


class ProjectCreate(BaseModel):
    """Request para criar projeto."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None

    review_title: str | None = Field(default=None, alias="reviewTitle")
    condition_studied: str | None = Field(default=None, alias="conditionStudied")
    review_rationale: str | None = Field(default=None, alias="reviewRationale")
    review_context: str | None = Field(default=None, alias="reviewContext")
    search_strategy: str | None = Field(default=None, alias="searchStrategy")

    review_keywords: list[str] = Field(default=[], alias="reviewKeywords")
    eligibility_criteria: dict[str, Any] = Field(default={}, alias="eligibilityCriteria")
    study_design: dict[str, Any] = Field(default={}, alias="studyDesign")

    review_type: Literal[
        "interventional",
        "predictive_model",
        "diagnostic",
        "prognostic",
        "qualitative",
        "other",
    ] = Field(default="interventional", alias="reviewType")

    assessment_scope: Literal["article", "extraction_instance"] = Field(
        default="article",
        alias="assessmentScope",
    )

    picots_config_ai_review: PICOTSConfig | None = Field(
        default=None,
        alias="picotsConfigAiReview",
    )

    settings: ProjectSettings = Field(default_factory=ProjectSettings)

    model_config = ConfigDict(populate_by_name=True)


class ProjectUpdate(BaseModel):
    """Request para atualizar projeto."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    is_active: bool | None = Field(default=None, alias="isActive")

    review_title: str | None = Field(default=None, alias="reviewTitle")
    condition_studied: str | None = Field(default=None, alias="conditionStudied")
    review_rationale: str | None = Field(default=None, alias="reviewRationale")
    review_context: str | None = Field(default=None, alias="reviewContext")
    search_strategy: str | None = Field(default=None, alias="searchStrategy")

    review_keywords: list[str] | None = Field(default=None, alias="reviewKeywords")
    eligibility_criteria: dict[str, Any] | None = Field(
        default=None,
        alias="eligibilityCriteria",
    )
    study_design: dict[str, Any] | None = Field(default=None, alias="studyDesign")

    review_type: (
        Literal[
            "interventional",
            "predictive_model",
            "diagnostic",
            "prognostic",
            "qualitative",
            "other",
        ]
        | None
    ) = Field(default=None, alias="reviewType")

    assessment_scope: Literal["article", "extraction_instance"] | None = Field(
        default=None,
        alias="assessmentScope",
    )

    assessment_entity_type_id: UUID | None = Field(
        default=None,
        alias="assessmentEntityTypeId",
    )

    risk_of_bias_instrument_id: UUID | None = Field(
        default=None,
        alias="riskOfBiasInstrumentId",
    )

    picots_config_ai_review: PICOTSConfig | None = Field(
        default=None,
        alias="picotsConfigAiReview",
    )

    settings: ProjectSettings | None = None

    model_config = ConfigDict(populate_by_name=True)


class ProjectResponse(BaseModel):
    """Response de projeto."""

    id: UUID
    name: str
    description: str | None = None
    created_by_id: UUID = Field(..., alias="createdById")
    is_active: bool = Field(..., alias="isActive")

    review_title: str | None = Field(default=None, alias="reviewTitle")
    condition_studied: str | None = Field(default=None, alias="conditionStudied")
    review_rationale: str | None = Field(default=None, alias="reviewRationale")
    review_context: str | None = Field(default=None, alias="reviewContext")
    search_strategy: str | None = Field(default=None, alias="searchStrategy")

    review_keywords: list[str] = Field(default=[], alias="reviewKeywords")
    eligibility_criteria: dict[str, Any] = Field(default={}, alias="eligibilityCriteria")
    study_design: dict[str, Any] = Field(default={}, alias="studyDesign")

    review_type: str = Field(default="interventional", alias="reviewType")
    assessment_scope: str = Field(default="article", alias="assessmentScope")

    assessment_entity_type_id: UUID | None = Field(
        default=None,
        alias="assessmentEntityTypeId",
    )
    risk_of_bias_instrument_id: UUID | None = Field(
        default=None,
        alias="riskOfBiasInstrumentId",
    )

    picots_config_ai_review: PICOTSConfig | None = Field(
        default=None,
        alias="picotsConfigAiReview",
    )

    settings: dict[str, Any]

    created_at: datetime = Field(..., alias="createdAt")
    updated_at: datetime = Field(..., alias="updatedAt")

    # Contadores
    articles_count: int | None = Field(default=None, alias="articlesCount")
    members_count: int | None = Field(default=None, alias="membersCount")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


# =================== MEMBER SCHEMAS ===================


class AddMemberRequest(BaseModel):
    """Request para adicionar membro ao projeto."""

    email: EmailStr
    role: Literal["manager", "reviewer", "viewer", "consensus"] = "reviewer"
    permissions: dict[str, bool] = Field(default={"can_export": False})
    send_invitation: bool = Field(default=True, alias="sendInvitation")

    model_config = ConfigDict(populate_by_name=True)


class UpdateMemberRequest(BaseModel):
    """Request para atualizar membro do projeto."""

    role: Literal["manager", "reviewer", "viewer", "consensus"] | None = None
    permissions: dict[str, bool] | None = None

    model_config = ConfigDict(populate_by_name=True)


class MemberResponse(BaseModel):
    """Response de membro do projeto."""

    id: UUID
    project_id: UUID = Field(..., alias="projectId")
    user_id: UUID = Field(..., alias="userId")
    role: str
    permissions: dict[str, bool]

    # Dados do usuário
    user_email: str | None = Field(default=None, alias="userEmail")
    user_name: str | None = Field(default=None, alias="userName")
    user_avatar: str | None = Field(default=None, alias="userAvatar")

    # Convite
    invitation_email: str | None = Field(default=None, alias="invitationEmail")
    invitation_sent_at: datetime | None = Field(default=None, alias="invitationSentAt")
    invitation_accepted_at: datetime | None = Field(
        default=None,
        alias="invitationAcceptedAt",
    )

    created_at: datetime = Field(..., alias="createdAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


# =================== LIST SCHEMAS ===================


class ProjectListItem(BaseModel):
    """Item de lista de projetos (resumido)."""

    id: UUID
    name: str
    description: str | None = None
    is_active: bool = Field(..., alias="isActive")
    review_type: str = Field(default="interventional", alias="reviewType")

    articles_count: int = Field(default=0, alias="articlesCount")
    members_count: int = Field(default=0, alias="membersCount")

    my_role: str | None = Field(default=None, alias="myRole")

    created_at: datetime = Field(..., alias="createdAt")
    updated_at: datetime = Field(..., alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class ProjectListResponse(BaseModel):
    """Response de listagem de projetos."""

    items: list[ProjectListItem]
    total: int
    page: int = 1
    page_size: int = Field(..., alias="pageSize")
    has_more: bool = Field(..., alias="hasMore")

    model_config = ConfigDict(populate_by_name=True)
