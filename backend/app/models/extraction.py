"""
Extraction Models.

Modelos para templates de extração, entidades, campos,
instâncias, valores e sugestões de IA.
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
    pass


class ExtractionFramework(str, PyEnum):
    """Framework de extração de dados."""

    CHARMS = "CHARMS"
    PICOS = "PICOS"
    CUSTOM = "CUSTOM"


class ExtractionFieldType(str, PyEnum):
    """Tipo de campo de extração."""

    TEXT = "text"
    NUMBER = "number"
    DATE = "date"
    SELECT = "select"
    MULTISELECT = "multiselect"
    BOOLEAN = "boolean"


class ExtractionCardinality(str, PyEnum):
    """Cardinalidade da entidade."""

    ONE = "one"
    MANY = "many"


class ExtractionSource(str, PyEnum):
    """Fonte do valor extraído."""

    HUMAN = "human"
    AI = "ai"
    RULE = "rule"


class ExtractionRunStage(str, PyEnum):
    """Estágio da execução de extração."""

    DATA_SUGGEST = "data_suggest"
    PARSING = "parsing"
    VALIDATION = "validation"
    CONSENSUS = "consensus"


class ExtractionRunStatus(str, PyEnum):
    """Status da execução de extração."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class SuggestionStatus(str, PyEnum):
    """Status da sugestão de IA."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ExtractionInstanceStatus(str, PyEnum):
    """
    Status de uma instância de extração.

    Alinhado com o enum 'extraction_instance_status' no PostgreSQL.
    """

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    REVIEWED = "reviewed"
    ARCHIVED = "archived"


class ExtractionTemplateGlobal(BaseModel):
    """
    Template global de extração (CHARMS, PICOS, etc.).

    Templates globais são compartilhados entre projetos.
    """

    __tablename__ = "extraction_templates_global"

    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    framework: Mapped[str] = mapped_column(
        PostgreSQLEnumType("extraction_framework"),
        nullable=False,
    )
    version: Mapped[str] = mapped_column(String, default="1.0.0", nullable=False)

    is_global: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    schema_: Mapped[dict] = mapped_column("schema", JSONB, default={}, nullable=False)

    # Relationships
    entity_types: Mapped[list["ExtractionEntityType"]] = relationship(
        "ExtractionEntityType",
        back_populates="global_template",
        foreign_keys="ExtractionEntityType.template_id",
    )

    # Índices definidos via __table_args__
    __table_args__ = (
        Index("idx_extraction_templates_global_schema_gin", "schema", postgresql_using="gin"),
        {"schema": "public"},
    )

    def __repr__(self) -> str:
        return f"<ExtractionTemplateGlobal {self.name}>"


class ProjectExtractionTemplate(BaseModel):
    """
    Template de extração clonado e customizado por projeto.

    Índices:
    - project_id: FK indexada
    - schema: GIN para busca em JSONB
    """

    __tablename__ = "project_extraction_templates"

    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    global_template_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.extraction_templates_global.id", ondelete="SET NULL"),
        nullable=True,
    )

    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    framework: Mapped[str] = mapped_column(
        PostgreSQLEnumType("extraction_framework"),
        nullable=False,
    )
    version: Mapped[str] = mapped_column(String, default="1.0.0", nullable=False)

    schema_: Mapped[dict] = mapped_column("schema", JSONB, default={}, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.profiles.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # Relationships
    entity_types: Mapped[list["ExtractionEntityType"]] = relationship(
        "ExtractionEntityType",
        back_populates="project_template",
        foreign_keys="ExtractionEntityType.project_template_id",
    )
    instances: Mapped[list["ExtractionInstance"]] = relationship(
        "ExtractionInstance",
        back_populates="template",
    )

    # Índices definidos via __table_args__
    __table_args__ = (
        Index("idx_project_extraction_templates_schema_gin", "schema", postgresql_using="gin"),
        {"schema": "public"},
    )

    def __repr__(self) -> str:
        return f"<ProjectExtractionTemplate {self.name}>"


class ExtractionEntityType(BaseModel):
    """
    Tipo de entidade definida nos templates (dataset, model, etc.).
    """

    __tablename__ = "extraction_entity_types"

    # FK mutuamente exclusiva - ou template global ou template de projeto
    template_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.extraction_templates_global.id", ondelete="CASCADE"),
        nullable=True,
    )

    project_template_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.project_extraction_templates.id", ondelete="CASCADE"),
        nullable=True,
    )

    name: Mapped[str] = mapped_column(String, nullable=False)
    label: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    parent_entity_type_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.extraction_entity_types.id", ondelete="CASCADE"),
        nullable=True,
    )

    cardinality: Mapped[str] = mapped_column(
        PostgreSQLEnumType("extraction_cardinality"),
        default="one",
        nullable=False,
    )

    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    global_template: Mapped["ExtractionTemplateGlobal | None"] = relationship(
        "ExtractionTemplateGlobal",
        back_populates="entity_types",
        foreign_keys=[template_id],
    )
    project_template: Mapped["ProjectExtractionTemplate | None"] = relationship(
        "ProjectExtractionTemplate",
        back_populates="entity_types",
        foreign_keys=[project_template_id],
    )
    fields: Mapped[list["ExtractionField"]] = relationship(
        "ExtractionField",
        back_populates="entity_type",
        cascade="all, delete-orphan",
    )
    parent: Mapped["ExtractionEntityType | None"] = relationship(
        "ExtractionEntityType",
        remote_side="ExtractionEntityType.id",
        foreign_keys=[parent_entity_type_id],
    )

    def __repr__(self) -> str:
        return f"<ExtractionEntityType {self.name}>"


class ExtractionField(BaseModel):
    """
    Campo específico de cada tipo de entidade.
    """

    __tablename__ = "extraction_fields"

    entity_type_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.extraction_entity_types.id", ondelete="CASCADE"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String, nullable=False)
    label: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    field_type: Mapped[str] = mapped_column(
        PostgreSQLEnumType("extraction_field_type"),
        nullable=False,
    )

    is_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    validation_schema: Mapped[dict] = mapped_column(JSONB, default={}, nullable=True)
    allowed_values: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    unit: Mapped[str | None] = mapped_column(String, nullable=True)
    allowed_units: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Descrição para LLM
    llm_description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # "Other" option support for select/multiselect fields
    allow_other: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    other_label: Mapped[str | None] = mapped_column(String, nullable=True)
    other_placeholder: Mapped[str | None] = mapped_column(String, nullable=True)

    # Relationships
    entity_type: Mapped["ExtractionEntityType"] = relationship(
        "ExtractionEntityType",
        back_populates="fields",
    )

    def __repr__(self) -> str:
        return f"<ExtractionField {self.name}>"


class ExtractionInstance(BaseModel):
    """
    Instância específica de entidade para cada artigo.

    Índices:
    - project_id, article_id, template_id: FKs indexadas
    - (article_id, entity_type_id, sort_order): busca ordenada
    - metadata: GIN para busca em JSONB
    """

    __tablename__ = "extraction_instances"

    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    article_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.articles.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    template_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.project_extraction_templates.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    entity_type_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.extraction_entity_types.id", ondelete="RESTRICT"),
        nullable=False,
    )

    parent_instance_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.extraction_instances.id", ondelete="CASCADE"),
        nullable=True,
    )

    label: Mapped[str] = mapped_column(String, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default={}, nullable=False)

    created_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.profiles.id", ondelete="RESTRICT"),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        PostgreSQLEnumType("extraction_instance_status"),
        default=ExtractionInstanceStatus.PENDING.value,
        nullable=False,
    )
    is_template: Mapped[bool] = mapped_column(Boolean, default=False, nullable=True)

    # Relationships
    template: Mapped["ProjectExtractionTemplate"] = relationship(
        "ProjectExtractionTemplate",
        back_populates="instances",
    )
    values: Mapped[list["ExtractedValue"]] = relationship(
        "ExtractedValue",
        back_populates="instance",
        cascade="all, delete-orphan",
    )

    # Índices definidos via __table_args__
    __table_args__ = (
        # Índice composto para busca ordenada por artigo
        Index(
            "idx_extraction_instances_article_entity_sort",
            "article_id",
            "entity_type_id",
            "sort_order",
        ),
        # Índice GIN para metadata
        Index("idx_extraction_instances_metadata_gin", "metadata", postgresql_using="gin"),
        {"schema": "public"},
    )

    def __repr__(self) -> str:
        return f"<ExtractionInstance {self.label}>"


class ExtractedValue(BaseModel):
    """
    Valor extraído para cada campo de cada instância.

    Índices:
    - project_id, article_id, instance_id, field_id: FKs indexadas
    - (instance_id, field_id): busca mais comum
    - value, evidence: GIN para busca em JSONB
    """

    __tablename__ = "extracted_values"

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

    instance_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.extraction_instances.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    field_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.extraction_fields.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    value: Mapped[dict] = mapped_column(JSONB, default={}, nullable=False)
    source: Mapped[str] = mapped_column(
        PostgreSQLEnumType("extraction_source"),
        nullable=False,
    )

    confidence_score: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    evidence: Mapped[dict] = mapped_column(JSONB, default=[], nullable=False)

    reviewer_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.profiles.id", ondelete="SET NULL"),
        nullable=True,
    )

    is_consensus: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    ai_suggestion_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.ai_suggestions.id", ondelete="SET NULL"),
        nullable=True,
    )

    unit: Mapped[str | None] = mapped_column(String, nullable=True)

    # Relationships
    instance: Mapped["ExtractionInstance"] = relationship(
        "ExtractionInstance",
        back_populates="values",
    )

    # Índices definidos via __table_args__
    __table_args__ = (
        # Índice composto mais usado (busca por instance + field)
        Index("idx_extracted_values_instance_field", "instance_id", "field_id"),
        # Índices GIN para JSONB
        Index("idx_extracted_values_value_gin", "value", postgresql_using="gin"),
        Index("idx_extracted_values_evidence_gin", "evidence", postgresql_using="gin"),
        {"schema": "public"},
    )

    def __repr__(self) -> str:
        return f"<ExtractedValue field={self.field_id}>"


class ExtractionEvidence(BaseModel):
    """
    Evidências que suportam valores extraídos ou instâncias.

    Índices:
    - project_id, article_id: FKs indexadas
    - position: GIN para busca em JSONB
    """

    __tablename__ = "extraction_evidence"

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

    target_type: Mapped[str] = mapped_column(String, nullable=False)
    target_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)

    article_file_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.article_files.id", ondelete="SET NULL"),
        nullable=True,
    )

    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    position: Mapped[dict] = mapped_column(JSONB, default={}, nullable=True)
    text_content: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.profiles.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # Índices definidos via __table_args__
    __table_args__ = (
        # Índice GIN para position JSONB
        Index("idx_extraction_evidence_position_gin", "position", postgresql_using="gin"),
        {"schema": "public"},
    )

    def __repr__(self) -> str:
        return f"<ExtractionEvidence {self.target_type}:{self.target_id}>"


class ExtractionRun(Base, UUIDMixin):
    """
    Execução de IA para sugerir valores de extração.

    Índices:
    - project_id, article_id, template_id: FKs indexadas
    - (status, stage): busca por status de execução
    - parameters, results: GIN para busca em JSONB
    """

    __tablename__ = "extraction_runs"

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

    template_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.project_extraction_templates.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    stage: Mapped[str] = mapped_column(
        PostgreSQLEnumType("extraction_run_stage"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        PostgreSQLEnumType("extraction_run_status"),
        default="pending",
        nullable=False,
    )

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
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    suggestions: Mapped[list["AISuggestion"]] = relationship(
        "AISuggestion",
        back_populates="extraction_run",
        cascade="all, delete-orphan",
    )

    # Índices definidos via __table_args__
    __table_args__ = (
        # Índice composto para busca por status e estágio
        Index("idx_extraction_runs_status_stage", "status", "stage"),
        # Índices GIN para JSONB
        Index("idx_extraction_runs_parameters_gin", "parameters", postgresql_using="gin"),
        Index("idx_extraction_runs_results_gin", "results", postgresql_using="gin"),
        {"schema": "public"},
    )

    def __repr__(self) -> str:
        return f"<ExtractionRun {self.id} stage={self.stage}>"


class AISuggestion(Base, UUIDMixin):
    """
    Sugestão específica gerada pela IA.

    Suporta dois tipos de sugestões (mutualmente exclusivos):
    1. Extraction suggestions: extraction_run_id + instance_id + field_id
    2. Assessment suggestions: assessment_run_id + assessment_item_id

    Constraint: Exatamente UM tipo de run_id deve ser preenchido (XOR):
    - (extraction_run_id NOT NULL AND assessment_run_id IS NULL) OR
    - (extraction_run_id IS NULL AND assessment_run_id NOT NULL)

    Índices:
    - extraction_run_id, assessment_run_id: FKs indexadas
    - instance_id, field_id, assessment_item_id: FKs indexadas
    - suggested_value, metadata: GIN para busca em JSONB
    """

    __tablename__ = "ai_suggestions"

    # === Run FKs (mutually exclusive) ===
    extraction_run_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.extraction_runs.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    assessment_run_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.ai_assessment_runs.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    screening_run_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.screening_runs.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # === Extraction suggestion fields (mutually exclusive with assessment fields) ===
    instance_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.extraction_instances.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    field_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.extraction_fields.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    # === Assessment suggestion fields (mutually exclusive with extraction fields) ===
    # Global instrument items
    assessment_item_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.assessment_items.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    # Project-scoped instrument items (XOR with assessment_item_id)
    project_assessment_item_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.project_assessment_items.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    suggested_value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    confidence_score: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(
        PostgreSQLEnumType("suggestion_status"),
        default="pending",
        nullable=False,
    )

    reviewed_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default={}, nullable=False)

    # Relationships
    extraction_run: Mapped["ExtractionRun | None"] = relationship(
        "ExtractionRun",
        foreign_keys=[extraction_run_id],
        back_populates="suggestions",
    )

    # Note: assessment_run relationship pode ser adicionado quando necessário
    # assessment_run: Mapped["AIAssessmentRun | None"] = relationship(
    #     "AIAssessmentRun",
    #     foreign_keys=[assessment_run_id],
    # )

    # Índices definidos via __table_args__
    __table_args__ = (
        # Índices GIN para JSONB
        Index("idx_ai_suggestions_suggested_value_gin", "suggested_value", postgresql_using="gin"),
        Index("idx_ai_suggestions_metadata_gin", "metadata", postgresql_using="gin"),
        {"schema": "public"},
    )

    def __repr__(self) -> str:
        return f"<AISuggestion field={self.field_id} status={self.status}>"
