"""
Assessment Models.

Modelos para instrumentos de avaliação de qualidade,
itens, respostas e avaliações por IA.
"""

from datetime import datetime
from enum import Enum as PyEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, BaseModel, PostgreSQLEnumType, UUIDMixin

if TYPE_CHECKING:
    from app.models.project import Project


class AssessmentStatus(str, PyEnum):
    """
    Status da avaliação de qualidade.

    Valores alinhados com o enum 'assessment_status' no PostgreSQL.
    """

    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    LOCKED = "locked"
    ARCHIVED = "archived"


class AssessmentInstrument(Base, UUIDMixin):
    """
    Instrumento de avaliação de qualidade (PROBAST, ROBIS, etc.).
    """

    __tablename__ = "assessment_instruments"

    tool_type: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[str] = mapped_column(String, nullable=False)
    mode: Mapped[str] = mapped_column(String, default="human", nullable=False)
    target_mode: Mapped[str] = mapped_column(
        String, default="per_article", nullable=False
    )  # per_article or per_model

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    aggregation_rules: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    schema_: Mapped[dict | None] = mapped_column("schema", JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    items: Mapped[list["AssessmentItem"]] = relationship(
        "AssessmentItem",
        back_populates="instrument",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<AssessmentInstrument {self.tool_type} {self.name}>"


class AssessmentItem(Base, UUIDMixin):
    """
    Item/pergunta individual de cada instrumento de avaliação.
    """

    __tablename__ = "assessment_items"

    instrument_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.assessment_instruments.id", ondelete="CASCADE"),
        nullable=False,
    )

    domain: Mapped[str] = mapped_column(String, nullable=False)
    item_code: Mapped[str] = mapped_column(String, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    allowed_levels: Mapped[dict] = mapped_column(JSONB, nullable=False)
    allowed_levels_override: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # LLM prompt for AI assessment
    llm_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    instrument: Mapped["AssessmentInstrument"] = relationship(
        "AssessmentInstrument",
        back_populates="items",
    )
    prompt: Mapped["AIAssessmentPrompt | None"] = relationship(
        "AIAssessmentPrompt",
        back_populates="assessment_item",
        uselist=False,
    )

    def __repr__(self) -> str:
        return f"<AssessmentItem {self.item_code}>"


# =================== REMOVED: LEGACY Assessment Model ===================
# A tabela "assessments" foi removida na migração 0032 (2026-01-28).
# Use a nova estrutura:
# - AssessmentInstance (análogo a ExtractionInstance)
# - AssessmentResponse (análogo a ExtractedValue)
# - AssessmentEvidence (análogo a ExtractionEvidence)
#
# Veja: AssessmentInstance, AssessmentResponse, AssessmentEvidence abaixo
# ========================================================================


class AIAssessmentConfig(BaseModel):
    """
    Configurações de IA para avaliação de qualidade por projeto.
    """

    __tablename__ = "ai_assessment_configs"

    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.projects.id", ondelete="CASCADE"),
        nullable=False,
    )

    instrument_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.assessment_instruments.id", ondelete="SET NULL"),
        nullable=True,
    )

    model_name: Mapped[str] = mapped_column(
        String,
        default="google/gemini-2.5-flash",
        nullable=False,
    )

    temperature: Mapped[float] = mapped_column(Numeric, default=0.3, nullable=False)
    max_tokens: Mapped[int] = mapped_column(Integer, default=2000, nullable=False)

    system_instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    def __repr__(self) -> str:
        return f"<AIAssessmentConfig project={self.project_id}>"


class AIAssessmentPrompt(BaseModel):
    """
    Prompts customizados para cada item de avaliação.
    """

    __tablename__ = "ai_assessment_prompts"

    assessment_item_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.assessment_items.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )

    system_prompt: Mapped[str] = mapped_column(
        Text,
        default="You are an expert research quality assessor. Analyze the provided research article and answer the specific question based on the evidence found in the text.",
        nullable=False,
    )

    user_prompt_template: Mapped[str] = mapped_column(
        Text,
        default="""Based on the article content, assess: {{question}}

Available response levels: {{levels}}

Provide your assessment with clear justification and cite specific passages from the text that support your conclusion.""",
        nullable=False,
    )

    # Relationships
    assessment_item: Mapped["AssessmentItem"] = relationship(
        "AssessmentItem",
        back_populates="prompt",
    )

    def __repr__(self) -> str:
        return f"<AIAssessmentPrompt item={self.assessment_item_id}>"


class AIAssessmentRun(BaseModel):
    """
    Rastreamento de execuções de avaliação por IA.

    Similar a extraction_runs, rastreia o ciclo de vida completo
    de uma execução de assessment por IA, incluindo parâmetros,
    resultados e métricas de performance.

    Índices:
    - project_id, article_id, instrument_id: FKs indexadas
    - extraction_instance_id: FK indexada (para PROBAST por modelo)
    - status, stage: Para queries de estado
    - parameters, results: GIN para busca em JSONB
    """

    __tablename__ = "ai_assessment_runs"

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

    instrument_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.assessment_instruments.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    project_instrument_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.project_assessment_instruments.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    extraction_instance_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.extraction_instances.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    stage: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="pending", nullable=False)

    parameters: Mapped[dict] = mapped_column(JSONB, default={}, nullable=False)
    results: Mapped[dict] = mapped_column(JSONB, default={}, nullable=False)
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
        index=True,
    )

    # Índices definidos via __table_args__
    __table_args__ = (
        # Índice composto para queries de status
        Index("idx_ai_assessment_runs_status", "status", "stage"),
        # Índices GIN para JSONB
        Index("idx_ai_assessment_runs_parameters_gin", "parameters", postgresql_using="gin"),
        Index("idx_ai_assessment_runs_results_gin", "results", postgresql_using="gin"),
        {"schema": "public"},
    )

    def __repr__(self) -> str:
        return f"<AIAssessmentRun {self.id} {self.stage} {self.status}>"


class AIAssessment(BaseModel):
    """
    Avaliação de qualidade gerada por IA.

    Índices:
    - project_id, article_id: FKs indexadas
    - evidence_passages: GIN para busca em JSONB
    """

    __tablename__ = "ai_assessments"

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

    assessment_item_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.assessment_items.id", ondelete="RESTRICT"),
        nullable=False,
    )

    instrument_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.assessment_instruments.id", ondelete="RESTRICT"),
        nullable=False,
    )

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.profiles.id", ondelete="RESTRICT"),
        nullable=False,
    )

    selected_level: Mapped[str] = mapped_column(String, nullable=False)
    confidence_score: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_passages: Mapped[dict] = mapped_column(JSONB, default=[], nullable=False)

    ai_model_used: Mapped[str] = mapped_column(String, nullable=False)
    processing_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[str] = mapped_column(
        String,
        default="pending_review",
        nullable=False,
    )

    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    human_response: Mapped[str | None] = mapped_column(String, nullable=True)

    article_file_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.article_files.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Índices definidos via __table_args__
    __table_args__ = (
        # Índice GIN para JSONB
        Index("idx_ai_assessments_evidence_gin", "evidence_passages", postgresql_using="gin"),
        {"schema": "public"},
    )

    def __repr__(self) -> str:
        return f"<AIAssessment article={self.article_id} item={self.assessment_item_id}>"


# =================== NEW MODELS (Assessment 2.0 - Extraction Pattern) ===================


class AssessmentSource(str, PyEnum):
    """
    Origem da resposta de assessment.

    Valores alinhados com o enum 'assessment_source' no PostgreSQL.
    """

    HUMAN = "human"
    AI = "ai"
    CONSENSUS = "consensus"


class AssessmentInstance(BaseModel):
    """
    Instância de avaliação (PROBAST por artigo ou por modelo).

    Análogo a ExtractionInstance. Permite hierarquia e vinculação
    a extraction_instances para suporte a PROBAST por modelo.

    Índices:
    - project_id, article_id, instrument_id: FKs indexadas
    - extraction_instance_id: FK indexada (para PROBAST por modelo)
    - parent_instance_id: FK indexada (hierarquia)
    - reviewer_id, status: Para queries de estado
    """

    __tablename__ = "assessment_instances"

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

    # XOR: must have exactly one instrument reference (global OR project)
    instrument_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.assessment_instruments.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    project_instrument_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.project_assessment_instruments.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    extraction_instance_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.extraction_instances.id", ondelete="SET NULL"),
        nullable=True,
    )

    parent_instance_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.assessment_instances.id", ondelete="CASCADE"),
        nullable=True,
    )

    label: Mapped[str] = mapped_column(String, nullable=False)

    status: Mapped[str] = mapped_column(
        PostgreSQLEnumType("assessment_status"),
        default="in_progress",
        nullable=False,
    )

    reviewer_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # Modo cego
    is_blind: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    can_see_others: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Metadados flexíveis (overall_risk, applicability_concerns, etc.)
    # Renamed from 'metadata' to 'meta' to avoid SQLAlchemy reserved attribute
    meta: Mapped[dict] = mapped_column("metadata", JSONB, default={}, nullable=False)

    # Relationships
    responses: Mapped[list["AssessmentResponse"]] = relationship(
        "AssessmentResponse",
        back_populates="assessment_instance",
        cascade="all, delete-orphan",
    )

    evidence: Mapped[list["AssessmentEvidence"]] = relationship(
        "AssessmentEvidence",
        foreign_keys="[AssessmentEvidence.target_id]",
        primaryjoin="and_(AssessmentInstance.id == foreign(AssessmentEvidence.target_id), AssessmentEvidence.target_type == 'instance')",
        cascade="all, delete-orphan",
        viewonly=True,
    )

    def __repr__(self) -> str:
        return f"<AssessmentInstance {self.label} article={self.article_id}>"


class AssessmentResponse(BaseModel):
    """
    Resposta individual a um item de avaliação.

    Análogo a ExtractedValue. Granularidade total: 1 linha = 1 resposta.

    Índices:
    - project_id, article_id: FKs indexadas (denormalização para performance)
    - assessment_instance_id, assessment_item_id: FKs indexadas
    - reviewer_id, source, selected_level: Para queries de filtro
    - uq_assessment_instance_item: UNIQUE (instance + item)
    """

    __tablename__ = "assessment_responses"

    # Denormalização intencional (performance + RLS)
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

    assessment_instance_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.assessment_instances.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    assessment_item_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.assessment_items.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # Resposta
    selected_level: Mapped[str] = mapped_column(String, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)

    # Origem e rastreabilidade
    source: Mapped[str] = mapped_column(
        PostgreSQLEnumType("assessment_source"),
        default="human",
        nullable=False,
    )

    confidence_score: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)

    ai_suggestion_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.ai_assessments.id", ondelete="SET NULL"),
        nullable=True,
    )

    reviewer_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    is_consensus: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    assessment_instance: Mapped["AssessmentInstance"] = relationship(
        "AssessmentInstance",
        back_populates="responses",
    )

    evidence: Mapped[list["AssessmentEvidence"]] = relationship(
        "AssessmentEvidence",
        foreign_keys="[AssessmentEvidence.target_id]",
        primaryjoin="and_(AssessmentResponse.id == foreign(AssessmentEvidence.target_id), AssessmentEvidence.target_type == 'response')",
        cascade="all, delete-orphan",
        viewonly=True,
    )

    def __repr__(self) -> str:
        return f"<AssessmentResponse {self.selected_level} item={self.assessment_item_id}>"


class AssessmentEvidence(BaseModel):
    """
    Evidências que suportam respostas de avaliação ou instances.

    Análogo a ExtractionEvidence. Armazena citações do PDF que
    justificam respostas ou avaliações completas.

    Índices:
    - project_id, article_id: FKs indexadas
    - target_type, target_id: Índice composto para queries polimórficas
    """

    __tablename__ = "assessment_evidence"

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

    # Alvo polimórfico (response ou instance)
    target_type: Mapped[str] = mapped_column(String, nullable=False)
    target_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)

    # Evidência do PDF
    article_file_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.article_files.id", ondelete="SET NULL"),
        nullable=True,
    )

    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    position: Mapped[dict | None] = mapped_column(JSONB, default={}, nullable=True)
    text_content: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.profiles.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # Índice composto definido via __table_args__
    __table_args__ = (
        Index("idx_assessment_evidence_target", "target_type", "target_id"),
        {"schema": "public"},
    )

    def __repr__(self) -> str:
        return f"<AssessmentEvidence {self.target_type} target={self.target_id}>"


# =================== PROJECT-LEVEL INSTRUMENTS (2.1) ===================


class ProjectAssessmentInstrument(BaseModel):
    """
    Project-specific assessment instrument.

    Allows per-project customization of global instruments (PROBAST, ROBIS, etc.)
    or creation of custom instruments. Follows the same pattern as
    project_extraction_templates.

    Indices:
    - project_id: FK indexed
    - global_instrument_id: FK indexed
    - created_by: FK indexed
    """

    __tablename__ = "project_assessment_instruments"

    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Reference to global instrument (if cloned)
    global_instrument_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.assessment_instruments.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Instrument metadata
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_type: Mapped[str] = mapped_column(String, nullable=False)  # PROBAST, ROBIS, CUSTOM
    version: Mapped[str] = mapped_column(String, default="1.0.0", nullable=False)
    mode: Mapped[str] = mapped_column(String, default="human", nullable=False)  # human, ai, hybrid
    target_mode: Mapped[str] = mapped_column(
        String, default="per_article", nullable=False
    )  # per_article or per_model

    # Configuration
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    aggregation_rules: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    schema_: Mapped[dict | None] = mapped_column("schema", JSONB, nullable=True)

    # Audit
    created_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.profiles.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # Relationships
    items: Mapped[list["ProjectAssessmentItem"]] = relationship(
        "ProjectAssessmentItem",
        back_populates="project_instrument",
        cascade="all, delete-orphan",
    )

    project: Mapped["Project"] = relationship(
        "Project",
        back_populates="assessment_instruments",
    )

    global_instrument: Mapped["AssessmentInstrument | None"] = relationship(
        "AssessmentInstrument",
    )

    def __repr__(self) -> str:
        return f"<ProjectAssessmentInstrument {self.name} project={self.project_id}>"


class ProjectAssessmentItem(BaseModel):
    """
    Project-specific assessment item.

    Items within a project instrument. Can be cloned from global items
    or created as custom items. Includes description and LLM prompt
    for AI assessment.

    Indices:
    - project_instrument_id: FK indexed
    - global_item_id: FK indexed
    """

    __tablename__ = "project_assessment_items"

    project_instrument_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.project_assessment_instruments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Reference to global item (if cloned)
    global_item_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.assessment_items.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Item definition
    domain: Mapped[str] = mapped_column(String, nullable=False)
    item_code: Mapped[str] = mapped_column(String, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Ordering and requirements
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Response levels
    allowed_levels: Mapped[dict] = mapped_column(JSONB, nullable=False)
    allowed_levels_override: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # AI configuration
    llm_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    project_instrument: Mapped["ProjectAssessmentInstrument"] = relationship(
        "ProjectAssessmentInstrument",
        back_populates="items",
    )

    global_item: Mapped["AssessmentItem | None"] = relationship(
        "AssessmentItem",
    )

    def __repr__(self) -> str:
        return f"<ProjectAssessmentItem {self.item_code} instrument={self.project_instrument_id}>"
