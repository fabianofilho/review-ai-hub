"""
SQLAlchemy Models.

Exporta todos os modelos para facilitar importação e
garantir que o Alembic detecte todas as tabelas.

IMPORTANTE: A ordem de importação importa!
- Modelos base primeiro (Base, BaseModel)
- Modelos sem dependências (User, Project)
- Modelos que dependem de outros (Article, Extraction, etc.)
"""

# Base models primeiro
# Modelos que dependem dos anteriores
from app.models.article import Article, ArticleFile, FileRole
from app.models.article_author import (
    ArticleAuthor,
    ArticleAuthorLink,
    ArticleSyncEvent,
    ArticleSyncRun,
)
from app.models.assessment import (
    AIAssessment,
    AIAssessmentConfig,
    AIAssessmentPrompt,
    AIAssessmentRun,
    AssessmentEvidence,
    AssessmentInstance,
    AssessmentInstrument,
    AssessmentItem,
    AssessmentResponse,
    AssessmentSource,
    AssessmentStatus,
    ProjectAssessmentInstrument,
    ProjectAssessmentItem,
)
from app.models.base import Base, BaseModel, TimestampMixin, UUIDMixin
from app.models.extraction import (
    AISuggestion,
    ExtractedValue,
    ExtractionCardinality,
    ExtractionEntityType,
    ExtractionEvidence,
    ExtractionField,
    ExtractionFieldType,
    ExtractionFramework,
    ExtractionInstance,
    ExtractionRun,
    ExtractionRunStage,
    ExtractionRunStatus,
    ExtractionSource,
    ExtractionTemplateGlobal,
    ProjectExtractionTemplate,
    SuggestionStatus,
)
from app.models.integration import ZoteroIntegration
from app.models.project import Project, ProjectMember, ProjectMemberRole, ReviewType
from app.models.screening import (
    ScreeningConfig,
    ScreeningConflict,
    ScreeningConflictStatusValue,
    ScreeningDecision,
    ScreeningDecisionValue,
    ScreeningPhase,
    ScreeningRun,
)

# Modelos sem dependências (ou com dependências mínimas)
from app.models.user import Profile
from app.models.user_api_key import SUPPORTED_PROVIDERS, UserAPIKey


# Força o registro de todas as tabelas no metadata
# Isso garante que todas as foreign keys sejam resolvidas corretamente
def _prepare_metadata() -> None:
    """
    Prepara o metadata do SQLAlchemy registrando todas as tabelas.

    Isso garante que todas as foreign keys sejam resolvidas corretamente,
    mesmo quando há dependências circulares entre modelos.

    A estratégia é forçar o processamento de cada modelo na ordem correta
    acessando seus atributos de tabela, garantindo que todas as foreign keys
    sejam resolvidas antes de processar modelos dependentes.
    """
    # Forçar o processamento de cada modelo na ordem de dependência
    # Isso garante que as tabelas sejam registradas antes de serem referenciadas

    # 1. Profile primeiro (sem dependências)
    Profile.__table__  # noqa: B018

    # 2. Project (depende de Profile)
    Project.__table__  # noqa: B018
    ProjectMember.__table__  # noqa: B018

    # 3. Article (depende de Project)
    Article.__table__  # noqa: B018
    ArticleFile.__table__  # noqa: B018
    ArticleAuthor.__table__  # noqa: B018
    ArticleAuthorLink.__table__  # noqa: B018
    ArticleSyncRun.__table__  # noqa: B018
    ArticleSyncEvent.__table__  # noqa: B018

    # 4. Extraction models (dependem de Article, Project, etc.)
    # Apenas acessar o metadata já força o processamento de todos
    _ = Base.metadata.tables


# Executar preparação do metadata após todas as importações
_prepare_metadata()

__all__ = [
    # Base
    "Base",
    "BaseModel",
    "TimestampMixin",
    "UUIDMixin",
    # User
    "Profile",
    # Project
    "Project",
    "ProjectMember",
    "ProjectMemberRole",
    "ReviewType",
    # Article
    "Article",
    "ArticleFile",
    "FileRole",
    "ArticleAuthor",
    "ArticleAuthorLink",
    "ArticleSyncRun",
    "ArticleSyncEvent",
    # Extraction
    "ExtractionTemplateGlobal",
    "ProjectExtractionTemplate",
    "ExtractionEntityType",
    "ExtractionField",
    "ExtractionInstance",
    "ExtractedValue",
    "ExtractionEvidence",
    "ExtractionRun",
    "AISuggestion",
    "ExtractionFramework",
    "ExtractionFieldType",
    "ExtractionCardinality",
    "ExtractionSource",
    "ExtractionRunStage",
    "ExtractionRunStatus",
    "SuggestionStatus",
    # Assessment (new structure)
    "AssessmentInstrument",
    "AssessmentItem",
    "AssessmentInstance",
    "AssessmentResponse",
    "AssessmentEvidence",
    "AssessmentSource",
    "AssessmentStatus",
    "AIAssessmentConfig",
    "AIAssessmentPrompt",
    "AIAssessmentRun",
    "AIAssessment",
    "ProjectAssessmentInstrument",
    "ProjectAssessmentItem",
    # Integration
    "ZoteroIntegration",
    # Screening
    "ScreeningConfig",
    "ScreeningDecision",
    "ScreeningConflict",
    "ScreeningRun",
    "ScreeningPhase",
    "ScreeningDecisionValue",
    "ScreeningConflictStatusValue",
    # User API Keys
    "UserAPIKey",
    "SUPPORTED_PROVIDERS",
]
