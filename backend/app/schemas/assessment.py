"""
Assessment Schemas.

Clean, DRY schema architecture for quality assessment:
- AI Assessment: Automated quality assessment via OpenAI
- Human Assessment: Manual quality assessment (to be implemented)
- Instruments: Assessment tools (PROBAST, ROBIS, etc.)
- Suggestions: AI-generated suggestions pending review

Architecture:
- Base schemas for shared concerns (Evidence, Response)
- Specialized schemas for AI vs Human flows
- Request/Response pairs following API conventions
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field

# =================== BASE SCHEMAS (SHARED) ===================


class EvidencePassage(BaseModel):
    """Text passage cited as evidence for an assessment."""

    text: str = Field(..., description="Text extracted from document")
    page_number: int | None = Field(default=None, alias="pageNumber")

    model_config = ConfigDict(populate_by_name=True)


class AssessmentItemSchema(BaseModel):
    """Assessment item (question) from an instrument."""

    id: UUID
    domain: str
    item_code: str = Field(..., alias="itemCode")
    question: str
    description: str | None = None
    sort_order: int = Field(..., alias="sortOrder")
    required: bool = True
    allowed_levels: list[str] = Field(..., alias="allowedLevels")
    llm_prompt: str | None = Field(default=None, alias="llmPrompt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class AssessmentInstrumentSchema(BaseModel):
    """Assessment instrument (PROBAST, ROBIS, etc.)."""

    id: UUID
    tool_type: str = Field(..., alias="toolType")
    name: str
    version: str
    mode: Literal["human", "ai", "hybrid"] = "human"
    is_active: bool = Field(default=True, alias="isActive")
    items: list[AssessmentItemSchema] = []

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


# =================== AI ASSESSMENT SCHEMAS ===================


class AIAssessmentRequest(BaseModel):
    """Request for AI assessment of a single item."""

    project_id: UUID = Field(..., alias="projectId")
    article_id: UUID = Field(..., alias="articleId")
    assessment_item_id: UUID = Field(..., alias="assessmentItemId")
    instrument_id: UUID = Field(..., alias="instrumentId")

    # PDF source (one of these must be provided)
    pdf_storage_key: str | None = Field(default=None, alias="pdfStorageKey")
    pdf_base64: str | None = Field(default=None, alias="pdfBase64")
    pdf_filename: str | None = Field(default=None, alias="pdfFilename")
    pdf_file_id: str | None = Field(default=None, alias="pdfFileId")

    # Force File Search for large PDFs (> 32MB)
    force_file_search: bool = Field(default=False, alias="forceFileSearch")

    # BYOK: Bring Your Own Key
    openai_api_key: str | None = Field(default=None, alias="openaiApiKey")

    # Hierarchical assessment (PROBAST by model)
    extraction_instance_id: UUID | None = Field(default=None, alias="extractionInstanceId")

    # Model options
    model: str = Field(default="gpt-4o-mini")
    temperature: float = Field(default=0.1, ge=0, le=1)

    model_config = ConfigDict(populate_by_name=True)


class AIAssessmentResult(BaseModel):
    """Result of a single AI assessment."""

    id: UUID
    project_id: UUID = Field(..., alias="projectId")
    article_id: UUID = Field(..., alias="articleId")
    assessment_item_id: UUID = Field(..., alias="assessmentItemId")
    instrument_id: UUID = Field(..., alias="instrumentId")

    selected_level: str = Field(..., alias="selectedLevel")
    confidence_score: float | None = Field(default=None, alias="confidenceScore")
    justification: str
    evidence_passages: list[EvidencePassage] = Field(default=[], alias="evidencePassages")

    ai_model_used: str = Field(..., alias="aiModelUsed")
    processing_time_ms: int | None = Field(default=None, alias="processingTimeMs")
    prompt_tokens: int | None = Field(default=None, alias="promptTokens")
    completion_tokens: int | None = Field(default=None, alias="completionTokens")

    status: str
    created_at: datetime = Field(..., alias="createdAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class AIAssessmentResponse(BaseModel):
    """Response from AI assessment endpoint."""

    assessment: AIAssessmentResult
    trace_id: str = Field(..., alias="traceId")

    model_config = ConfigDict(populate_by_name=True)


# Legacy response format (used by some endpoints)
class AIAssessmentResponseData(BaseModel):
    """Legacy response format for AI assessment."""

    id: str
    selected_level: str = Field(..., alias="selectedLevel")
    confidence_score: float | None = Field(default=None, alias="confidenceScore")
    justification: str
    evidence_passages: list[dict[str, Any]] = Field(default=[], alias="evidencePassages")
    status: str
    metadata: dict[str, Any]

    model_config = ConfigDict(populate_by_name=True)


# =================== BATCH AI ASSESSMENT SCHEMAS ===================


class BatchAIAssessmentRequest(BaseModel):
    """Request for batch AI assessment."""

    project_id: UUID = Field(..., alias="projectId")
    article_id: UUID = Field(..., alias="articleId")
    instrument_id: UUID = Field(..., alias="instrumentId")

    # Specific items or all items
    item_ids: list[UUID] = Field(..., alias="itemIds")

    # PDF source
    pdf_storage_key: str | None = Field(default=None, alias="pdfStorageKey")

    # BYOK: Bring Your Own Key
    openai_api_key: str | None = Field(default=None, alias="openaiApiKey")

    # Hierarchical assessment (PROBAST by model)
    extraction_instance_id: UUID | None = Field(default=None, alias="extractionInstanceId")

    # Options
    model: str = Field(default="gpt-4o-mini")
    force_file_search: bool = Field(default=False, alias="forceFileSearch")

    model_config = ConfigDict(populate_by_name=True)


class BatchItemResult(BaseModel):
    """Result of a single item in batch assessment."""

    item_id: UUID = Field(..., alias="itemId")
    success: bool
    assessment_id: UUID | None = Field(default=None, alias="assessmentId")
    error: str | None = None

    model_config = ConfigDict(populate_by_name=True)


class BatchAIAssessmentResult(BaseModel):
    """Result of batch AI assessment."""

    trace_id: str = Field(..., alias="traceId")
    total_items: int = Field(..., alias="totalItems")
    successful: int
    failed: int
    results: list[BatchItemResult]
    processing_time_ms: int = Field(..., alias="processingTimeMs")

    model_config = ConfigDict(populate_by_name=True)


# Legacy batch response format
class BatchAIAssessmentResponseData(BaseModel):
    """Legacy response format for batch AI assessment."""

    results: list[dict[str, Any]]
    total_items: int = Field(..., alias="totalItems")
    successful_items: int = Field(..., alias="successfulItems")

    model_config = ConfigDict(populate_by_name=True)


# =================== AI SUGGESTION SCHEMAS ===================


class AISuggestionSchema(BaseModel):
    """AI-generated suggestion pending review."""

    id: UUID
    assessment_run_id: UUID = Field(..., alias="assessmentRunId")
    # Both nullable at DB level (XOR), but frontend always gets one via assessmentItemId
    assessment_item_id: UUID | None = Field(default=None, exclude=True)
    project_assessment_item_id: UUID | None = Field(default=None, exclude=True)
    suggested_value: dict[str, Any] = Field(..., alias="suggestedValue")
    confidence_score: float | None = Field(default=None, alias="confidenceScore")
    reasoning: str | None = None
    status: str  # 'pending', 'accepted', 'rejected'
    metadata_: dict[str, Any] = Field(default={}, alias="metadata")
    created_at: datetime = Field(..., alias="createdAt")

    @computed_field(alias="assessmentItemId")  # type: ignore[misc]
    @property
    def effective_assessment_item_id(self) -> UUID:
        """Return whichever item ID is set (global or project-scoped)."""
        return self.assessment_item_id or self.project_assessment_item_id  # type: ignore[return-value]

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class ListSuggestionsRequest(BaseModel):
    """Request to list AI suggestions."""

    project_id: UUID = Field(..., alias="projectId")
    article_id: UUID = Field(..., alias="articleId")
    instrument_id: UUID | None = Field(default=None, alias="instrumentId")
    extraction_instance_id: UUID | None = Field(default=None, alias="extractionInstanceId")
    status: Literal["pending", "accepted", "rejected"] | None = None

    model_config = ConfigDict(populate_by_name=True)


class ListSuggestionsResponse(BaseModel):
    """Response with list of AI suggestions."""

    suggestions: list[AISuggestionSchema]
    total: int

    model_config = ConfigDict(populate_by_name=True)


class ReviewAISuggestionRequest(BaseModel):
    """Request to review an AI suggestion."""

    action: Literal["accept", "reject", "modify"]
    modified_value: dict[str, Any] | None = Field(default=None, alias="modifiedValue")
    review_notes: str | None = Field(default=None, alias="reviewNotes")

    model_config = ConfigDict(populate_by_name=True)


class ReviewAISuggestionResponse(BaseModel):
    """Response after reviewing an AI suggestion."""

    suggestion_id: UUID = Field(..., alias="suggestionId")
    action: str
    assessment_created: bool = Field(..., alias="assessmentCreated")
    assessment_id: UUID | None = Field(default=None, alias="assessmentId")

    model_config = ConfigDict(populate_by_name=True)


# Deprecated - use ReviewAISuggestionRequest
class ReviewAIAssessmentRequest(BaseModel):
    """
    DEPRECATED: Use ReviewAISuggestionRequest instead.

    Request to review AI assessment (old format).
    """

    status: Literal["accepted", "rejected", "modified"]
    human_response: str | None = Field(default=None, alias="humanResponse")
    notes: str | None = None

    model_config = ConfigDict(populate_by_name=True)


# =================== HUMAN ASSESSMENT SCHEMAS (NEW - EXTRACTION PATTERN) ===================
# These schemas follow the extraction pattern: Instance → Response → Evidence
# Aligned with AssessmentInstance, AssessmentResponse, AssessmentEvidence models


class AssessmentResponseCreate(BaseModel):
    """Create a new assessment response (single item answer)."""

    assessment_item_id: UUID = Field(..., alias="assessmentItemId")
    selected_level: str = Field(..., alias="selectedLevel")
    notes: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)

    model_config = ConfigDict(populate_by_name=True)


class AssessmentResponseSchema(BaseModel):
    """Assessment response (single item answer)."""

    id: UUID
    project_id: UUID = Field(..., alias="projectId")
    article_id: UUID = Field(..., alias="articleId")
    assessment_instance_id: UUID = Field(..., alias="assessmentInstanceId")
    assessment_item_id: UUID = Field(..., alias="assessmentItemId")

    selected_level: str = Field(..., alias="selectedLevel")
    notes: str | None = None
    confidence: float | None = None

    source: Literal["human", "ai", "consensus"]
    confidence_score: float | None = Field(default=None, alias="confidenceScore")
    ai_suggestion_id: UUID | None = Field(default=None, alias="aiSuggestionId")

    reviewer_id: UUID = Field(..., alias="reviewerId")
    is_consensus: bool = Field(default=False, alias="isConsensus")

    created_at: datetime = Field(..., alias="createdAt")
    updated_at: datetime = Field(..., alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class AssessmentEvidenceCreate(BaseModel):
    """Create evidence for an assessment response or instance."""

    target_type: Literal["response", "instance"]
    target_id: UUID = Field(..., alias="targetId")

    article_file_id: UUID | None = Field(default=None, alias="articleFileId")
    page_number: int | None = Field(default=None, alias="pageNumber")
    position: dict[str, Any] | None = None
    text_content: str | None = Field(default=None, alias="textContent")

    model_config = ConfigDict(populate_by_name=True)


class AssessmentEvidenceSchema(BaseModel):
    """Evidence supporting an assessment response or instance."""

    id: UUID
    project_id: UUID = Field(..., alias="projectId")
    article_id: UUID = Field(..., alias="articleId")

    target_type: Literal["response", "instance"]
    target_id: UUID = Field(..., alias="targetId")

    article_file_id: UUID | None = Field(default=None, alias="articleFileId")
    page_number: int | None = Field(default=None, alias="pageNumber")
    position: dict[str, Any] | None = None
    text_content: str | None = Field(default=None, alias="textContent")

    created_by: UUID = Field(..., alias="createdBy")
    created_at: datetime = Field(..., alias="createdAt")
    updated_at: datetime = Field(..., alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class AssessmentInstanceCreate(BaseModel):
    """Create a new assessment instance (container for responses)."""

    project_id: UUID = Field(..., alias="projectId")
    article_id: UUID = Field(..., alias="articleId")
    instrument_id: UUID = Field(..., alias="instrumentId")

    label: str  # e.g., "PROBAST Assessment - John Doe"

    # Hierarchical assessment (PROBAST by model)
    extraction_instance_id: UUID | None = Field(default=None, alias="extractionInstanceId")
    parent_instance_id: UUID | None = Field(default=None, alias="parentInstanceId")

    # Blind mode
    is_blind: bool = Field(default=False, alias="isBlind")
    can_see_others: bool = Field(default=True, alias="canSeeOthers")

    # Flexible metadata (overall_risk, applicability_concerns, etc.)
    metadata: dict[str, Any] = {}

    model_config = ConfigDict(populate_by_name=True)


class AssessmentInstanceUpdate(BaseModel):
    """Update an existing assessment instance."""

    label: str | None = None
    status: Literal["in_progress", "submitted", "locked", "archived"] | None = None
    is_blind: bool | None = Field(default=None, alias="isBlind")
    can_see_others: bool | None = Field(default=None, alias="canSeeOthers")
    metadata: dict[str, Any] | None = None

    model_config = ConfigDict(populate_by_name=True)


class AssessmentInstanceSchema(BaseModel):
    """Assessment instance (container for responses)."""

    id: UUID
    project_id: UUID = Field(..., alias="projectId")
    article_id: UUID = Field(..., alias="articleId")
    instrument_id: UUID = Field(..., alias="instrumentId")

    extraction_instance_id: UUID | None = Field(default=None, alias="extractionInstanceId")
    parent_instance_id: UUID | None = Field(default=None, alias="parentInstanceId")

    label: str
    status: Literal["in_progress", "submitted", "locked", "archived"]

    reviewer_id: UUID = Field(..., alias="reviewerId")

    is_blind: bool = Field(..., alias="isBlind")
    can_see_others: bool = Field(..., alias="canSeeOthers")

    metadata: dict[str, Any]

    created_at: datetime = Field(..., alias="createdAt")
    updated_at: datetime = Field(..., alias="updatedAt")

    # Optional nested data
    responses: list[AssessmentResponseSchema] = []
    evidence: list[AssessmentEvidenceSchema] = []

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


# =================== AGGREGATE SCHEMAS ===================


class DomainSummary(BaseModel):
    """Summary of an assessment domain."""

    domain: str
    items_count: int = Field(..., alias="itemsCount")
    completed_count: int = Field(..., alias="completedCount")
    overall_level: str | None = Field(default=None, alias="overallLevel")

    model_config = ConfigDict(populate_by_name=True)


class ArticleAssessmentSummary(BaseModel):
    """Summary of all assessments for an article."""

    article_id: UUID = Field(..., alias="articleId")
    human_assessments: int = Field(..., alias="humanAssessments")
    ai_assessments: int = Field(..., alias="aiAssessments")
    domains: list[DomainSummary]
    overall_risk_of_bias: str | None = Field(default=None, alias="overallRiskOfBias")
    consensus_reached: bool = Field(default=False, alias="consensusReached")

    model_config = ConfigDict(populate_by_name=True)


# =================== PROJECT INSTRUMENT SCHEMAS ===================


class ProjectAssessmentItemBase(BaseModel):
    """Base fields for project assessment item."""

    domain: str
    item_code: str = Field(..., alias="itemCode")
    question: str
    description: str | None = None
    sort_order: int = Field(default=0, alias="sortOrder")
    required: bool = True
    allowed_levels: list[str] = Field(..., alias="allowedLevels")
    llm_prompt: str | None = Field(default=None, alias="llmPrompt")

    model_config = ConfigDict(populate_by_name=True)


class ProjectAssessmentItemCreate(ProjectAssessmentItemBase):
    """Create a project assessment item."""

    global_item_id: UUID | None = Field(default=None, alias="globalItemId")


class ProjectAssessmentItemUpdate(BaseModel):
    """Update a project assessment item."""

    domain: str | None = None
    item_code: str | None = Field(default=None, alias="itemCode")
    question: str | None = None
    description: str | None = None
    sort_order: int | None = Field(default=None, alias="sortOrder")
    required: bool | None = None
    allowed_levels: list[str] | None = Field(default=None, alias="allowedLevels")
    llm_prompt: str | None = Field(default=None, alias="llmPrompt")

    model_config = ConfigDict(populate_by_name=True)


class ProjectAssessmentItemSchema(ProjectAssessmentItemBase):
    """Project assessment item full schema."""

    id: UUID
    project_instrument_id: UUID = Field(..., alias="projectInstrumentId")
    global_item_id: UUID | None = Field(default=None, alias="globalItemId")
    created_at: datetime = Field(..., alias="createdAt")
    updated_at: datetime = Field(..., alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class ProjectAssessmentInstrumentBase(BaseModel):
    """Base fields for project assessment instrument."""

    name: str
    description: str | None = None
    tool_type: str = Field(..., alias="toolType")  # PROBAST, ROBIS, CUSTOM
    version: str = "1.0.0"
    mode: Literal["human", "ai", "hybrid"] = "human"
    target_mode: Literal["per_article", "per_model"] = Field(
        default="per_article",
        alias="targetMode",
        description="Assessment target: per_article (whole article) or per_model (each extracted model)",
    )
    is_active: bool = Field(default=True, alias="isActive")
    aggregation_rules: dict[str, Any] | None = Field(default=None, alias="aggregationRules")
    schema_config: dict[str, Any] | None = Field(
        default=None,
        alias="schema",
        validation_alias="schema_",
    )

    model_config = ConfigDict(populate_by_name=True)


class ProjectAssessmentInstrumentCreate(ProjectAssessmentInstrumentBase):
    """Create a project assessment instrument."""

    project_id: UUID = Field(..., alias="projectId")
    global_instrument_id: UUID | None = Field(default=None, alias="globalInstrumentId")
    items: list[ProjectAssessmentItemCreate] = []


class ProjectAssessmentInstrumentUpdate(BaseModel):
    """Update a project assessment instrument."""

    name: str | None = None
    description: str | None = None
    version: str | None = None
    mode: Literal["human", "ai", "hybrid"] | None = None
    target_mode: Literal["per_article", "per_model"] | None = Field(
        default=None, alias="targetMode"
    )
    is_active: bool | None = Field(default=None, alias="isActive")
    aggregation_rules: dict[str, Any] | None = Field(default=None, alias="aggregationRules")
    schema_config: dict[str, Any] | None = Field(default=None, alias="schema")

    model_config = ConfigDict(populate_by_name=True)


class ProjectAssessmentInstrumentSchema(ProjectAssessmentInstrumentBase):
    """Project assessment instrument full schema."""

    id: UUID
    project_id: UUID = Field(..., alias="projectId")
    global_instrument_id: UUID | None = Field(default=None, alias="globalInstrumentId")
    created_by: UUID = Field(..., alias="createdBy")
    created_at: datetime = Field(..., alias="createdAt")
    updated_at: datetime = Field(..., alias="updatedAt")
    items: list[ProjectAssessmentItemSchema] = []

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class CloneInstrumentRequest(BaseModel):
    """Request to clone a global instrument to a project."""

    project_id: UUID = Field(..., alias="projectId")
    global_instrument_id: UUID = Field(..., alias="globalInstrumentId")
    custom_name: str | None = Field(default=None, alias="customName")

    model_config = ConfigDict(populate_by_name=True)


class CloneInstrumentResponse(BaseModel):
    """Response after cloning an instrument."""

    project_instrument_id: UUID = Field(..., alias="projectInstrumentId")
    message: str

    model_config = ConfigDict(populate_by_name=True)


class GlobalInstrumentSummary(BaseModel):
    """Summary of a global instrument for selection."""

    id: UUID
    tool_type: str = Field(..., alias="toolType")
    name: str
    version: str
    mode: Literal["human", "ai", "hybrid"]
    target_mode: Literal["per_article", "per_model"] = Field(
        default="per_article",
        alias="targetMode",
        description="Default assessment target for this instrument",
    )
    items_count: int = Field(..., alias="itemsCount")
    domains: list[str]

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)
