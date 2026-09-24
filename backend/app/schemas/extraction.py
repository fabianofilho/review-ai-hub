"""
Extraction Schemas.

Schemas Pydantic para extração de dados de artigos científicos.
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

# =================== COMMON SCHEMAS ===================


class ExtractionOptions(BaseModel):
    """Opções de extração."""

    model: str = Field(default="gpt-4o-mini", description="Modelo OpenAI a usar")
    temperature: float = Field(default=0.1, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=100, le=16000)

    model_config = ConfigDict(populate_by_name=True)


class EvidencePassage(BaseModel):
    """Passagem de texto citada como evidência."""

    text: str = Field(..., description="Texto extraído do documento")
    page_number: int | None = Field(default=None, description="Número da página")
    confidence: float | None = Field(default=None, ge=0, le=1)

    model_config = ConfigDict(populate_by_name=True)


class FieldSuggestion(BaseModel):
    """Sugestão de valor para um campo."""

    field_id: UUID = Field(..., alias="fieldId")
    field_name: str = Field(..., alias="fieldName")
    suggested_value: Any = Field(..., alias="suggestedValue")
    confidence_score: float | None = Field(default=None, alias="confidenceScore", ge=0, le=1)
    reasoning: str | None = None
    evidence: list[EvidencePassage] = []

    model_config = ConfigDict(populate_by_name=True)


# =================== SECTION EXTRACTION SCHEMAS ===================


class SectionExtractionRequest(BaseModel):
    """Request para extração de seção."""

    project_id: UUID = Field(..., alias="projectId")
    article_id: UUID = Field(..., alias="articleId")
    template_id: UUID = Field(..., alias="templateId")

    # Para extração de seção única
    entity_type_id: UUID | None = Field(default=None, alias="entityTypeId")

    # Para extração em batch de todas as seções
    parent_instance_id: UUID | None = Field(default=None, alias="parentInstanceId")
    extract_all_sections: bool = Field(default=False, alias="extractAllSections")

    # Filtrar seções específicas (para chunking)
    section_ids: list[UUID] | None = Field(default=None, alias="sectionIds")

    # Texto do PDF já processado (evita reprocessar)
    pdf_text: str | None = Field(default=None, alias="pdfText")

    # Opções de extração
    options: ExtractionOptions | None = None
    model: str | None = Field(
        default="gpt-4o-mini",
        description="Modelo OpenAI a usar",
    )

    model_config = ConfigDict(populate_by_name=True)

    @model_validator(mode="after")
    def validate_extraction_mode(self) -> "SectionExtractionRequest":
        """Valida que os campos corretos estão presentes para cada modo."""
        if self.extract_all_sections:
            if not self.parent_instance_id:
                raise ValueError("parentInstanceId is required when extractAllSections is true")
        else:
            if not self.entity_type_id:
                raise ValueError("entityTypeId is required when extractAllSections is false")
        return self


class SingleSectionResult(BaseModel):
    """Resultado de extração de seção única."""

    extraction_run_id: str = Field(..., alias="extractionRunId")
    suggestions_created: int = Field(..., alias="suggestionsCreated")
    entity_type_id: str = Field(..., alias="entityTypeId")
    tokens_prompt: int = Field(..., alias="tokensPrompt")
    tokens_completion: int = Field(..., alias="tokensCompletion")
    tokens_total: int = Field(..., alias="tokensTotal")
    duration_ms: float = Field(..., alias="durationMs")

    model_config = ConfigDict(populate_by_name=True)


class BatchSectionResult(BaseModel):
    """Resultado de extração em batch."""

    extraction_run_id: str = Field(..., alias="extractionRunId")
    total_sections: int = Field(..., alias="totalSections")
    successful_sections: int = Field(..., alias="successfulSections")
    failed_sections: int = Field(..., alias="failedSections")
    total_suggestions_created: int = Field(..., alias="totalSuggestionsCreated")
    total_tokens_used: int = Field(..., alias="totalTokensUsed")
    duration_ms: float = Field(..., alias="durationMs")
    sections: list[dict[str, Any]] = Field(default=[], alias="sections")

    model_config = ConfigDict(populate_by_name=True)


# =================== MODEL EXTRACTION SCHEMAS ===================


class ModelExtractionRequest(BaseModel):
    """Request para extração de modelos de predição."""

    project_id: UUID = Field(..., alias="projectId")
    article_id: UUID = Field(..., alias="articleId")
    template_id: UUID = Field(..., alias="templateId")

    # Opções de extração
    model: str | None = Field(
        default="gpt-4o-mini",
        description="Modelo OpenAI a usar",
    )
    options: ExtractionOptions | None = None

    model_config = ConfigDict(populate_by_name=True)


class IdentifiedModel(BaseModel):
    """Modelo de predição identificado no artigo."""

    model_name: str = Field(..., alias="modelName")
    model_type: str | None = Field(default=None, alias="modelType")
    target_outcome: str | None = Field(default=None, alias="targetOutcome")
    description: str | None = None

    # Metadados adicionais extraídos
    sample_size: int | None = Field(default=None, alias="sampleSize")
    performance_metrics: dict[str, Any] = Field(default={}, alias="performanceMetrics")
    validation_strategy: str | None = Field(default=None, alias="validationStrategy")

    model_config = ConfigDict(populate_by_name=True)


class ModelExtractionResult(BaseModel):
    """Resultado da extração de modelos."""

    extraction_run_id: str = Field(..., alias="extractionRunId")
    models_created: list[dict[str, Any]] = Field(..., alias="modelsCreated")
    total_models: int = Field(..., alias="totalModels")
    child_instances_created: int = Field(..., alias="childInstancesCreated")
    metadata: dict[str, Any]

    model_config = ConfigDict(populate_by_name=True)


# =================== ENTITY TYPE SCHEMAS ===================


class ExtractionFieldSchema(BaseModel):
    """Schema de campo de extração."""

    id: UUID
    name: str
    label: str
    description: str | None = None
    field_type: str = Field(..., alias="fieldType")
    is_required: bool = Field(default=False, alias="isRequired")
    allowed_values: list[str] | None = Field(default=None, alias="allowedValues")
    unit: str | None = None
    allowed_units: list[str] | None = Field(default=None, alias="allowedUnits")
    llm_description: str | None = Field(default=None, alias="llmDescription")
    sort_order: int = Field(default=0, alias="sortOrder")

    model_config = ConfigDict(populate_by_name=True)


class ExtractionEntityTypeSchema(BaseModel):
    """Schema de tipo de entidade."""

    id: UUID
    name: str
    label: str
    description: str | None = None
    cardinality: Literal["one", "many"]
    is_required: bool = Field(default=False, alias="isRequired")
    sort_order: int = Field(default=0, alias="sortOrder")
    parent_entity_type_id: UUID | None = Field(default=None, alias="parentEntityTypeId")
    fields: list[ExtractionFieldSchema] = []

    model_config = ConfigDict(populate_by_name=True)


class ExtractionTemplateSchema(BaseModel):
    """Schema de template de extração."""

    id: UUID
    name: str
    description: str | None = None
    framework: Literal["CHARMS", "PICOS", "CUSTOM"]
    version: str
    entity_types: list[ExtractionEntityTypeSchema] = Field(default=[], alias="entityTypes")

    model_config = ConfigDict(populate_by_name=True)


# =================== INSTANCE SCHEMAS ===================


class CreateInstanceRequest(BaseModel):
    """Request para criar instância de extração."""

    project_id: UUID = Field(..., alias="projectId")
    article_id: UUID = Field(..., alias="articleId")
    template_id: UUID = Field(..., alias="templateId")
    entity_type_id: UUID = Field(..., alias="entityTypeId")
    parent_instance_id: UUID | None = Field(default=None, alias="parentInstanceId")
    label: str
    metadata: dict[str, Any] = {}

    model_config = ConfigDict(populate_by_name=True)


class InstanceResponse(BaseModel):
    """Response de instância de extração."""

    id: UUID
    project_id: UUID = Field(..., alias="projectId")
    article_id: UUID | None = Field(default=None, alias="articleId")
    template_id: UUID = Field(..., alias="templateId")
    entity_type_id: UUID = Field(..., alias="entityTypeId")
    parent_instance_id: UUID | None = Field(default=None, alias="parentInstanceId")
    label: str
    status: str
    sort_order: int = Field(..., alias="sortOrder")
    created_at: datetime = Field(..., alias="createdAt")
    updated_at: datetime = Field(..., alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


# =================== VALUE SCHEMAS ===================


class SaveValueRequest(BaseModel):
    """Request para salvar valor extraído."""

    instance_id: UUID = Field(..., alias="instanceId")
    field_id: UUID = Field(..., alias="fieldId")
    value: Any
    source: Literal["human", "ai", "rule"] = "human"
    unit: str | None = None
    evidence: list[EvidencePassage] = []
    ai_suggestion_id: UUID | None = Field(default=None, alias="aiSuggestionId")

    model_config = ConfigDict(populate_by_name=True)


class ValueResponse(BaseModel):
    """Response de valor extraído."""

    id: UUID
    instance_id: UUID = Field(..., alias="instanceId")
    field_id: UUID = Field(..., alias="fieldId")
    value: Any
    source: str
    confidence_score: float | None = Field(default=None, alias="confidenceScore")
    unit: str | None = None
    is_consensus: bool = Field(default=False, alias="isConsensus")
    created_at: datetime = Field(..., alias="createdAt")
    updated_at: datetime = Field(..., alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


# =================== SUGGESTION SCHEMAS ===================


class SuggestionResponse(BaseModel):
    """Response de sugestão de IA para extraction."""

    id: UUID
    extraction_run_id: UUID = Field(..., alias="extractionRunId")
    instance_id: UUID | None = Field(default=None, alias="instanceId")
    field_id: UUID = Field(..., alias="fieldId")
    suggested_value: Any = Field(..., alias="suggestedValue")
    confidence_score: float | None = Field(default=None, alias="confidenceScore")
    reasoning: str | None = None
    status: Literal["pending", "accepted", "rejected"]
    created_at: datetime = Field(..., alias="createdAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class ReviewSuggestionRequest(BaseModel):
    """Request para revisar sugestão."""

    status: Literal["accepted", "rejected"]
    modified_value: Any | None = Field(default=None, alias="modifiedValue")

    model_config = ConfigDict(populate_by_name=True)
