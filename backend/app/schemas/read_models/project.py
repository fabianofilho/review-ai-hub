"""
Project Read Models.

DTOs otimizados para listagem e detalhes de projetos.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ProjectMemberReadModel(BaseModel):
    """Membro de projeto para leitura."""

    user_id: UUID
    role: str
    user_name: str | None = None
    user_email: str | None = None
    joined_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ProjectListReadModel(BaseModel):
    """
    Projeto para listagem.

    Inclui estatísticas agregadas.
    """

    id: UUID
    name: str
    review_title: str | None = None
    description: str | None = None
    status: str = "active"  # active, archived, completed

    # Organização
    org_id: UUID
    org_name: str | None = None

    # Contagens (aggregations)
    articles_count: int = 0
    members_count: int = 0
    instruments_count: int = 0
    templates_count: int = 0

    # Progresso
    articles_completed: int = 0
    completion_percentage: float = 0.0

    # Timestamps
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def compute_completion(cls, completed: int, total: int) -> float:
        """Calcula percentual de conclusão."""
        if total == 0:
            return 0.0
        return round((completed / total) * 100, 1)


class ProjectDetailReadModel(BaseModel):
    """
    Projeto com detalhes completos.

    Inclui membros, configurações e estatísticas detalhadas.
    """

    id: UUID
    name: str
    review_title: str | None = None
    description: str | None = None
    condition_studied: str | None = None
    eligibility_criteria: str | None = None
    study_design: str | None = None
    status: str = "active"

    # Organização
    org_id: UUID
    org_name: str | None = None

    # Criador
    created_by_id: UUID | None = None
    created_by_name: str | None = None

    # Membros (eager loaded)
    members: list[ProjectMemberReadModel] = []

    # Estatísticas de artigos
    articles_total: int = 0
    articles_pending: int = 0
    articles_in_progress: int = 0
    articles_completed: int = 0

    # Estatísticas de assessments
    assessments_total: int = 0
    assessments_completed: int = 0
    ai_assessments_total: int = 0
    ai_assessments_pending_review: int = 0

    # Estatísticas de extrações
    extractions_total: int = 0
    extractions_completed: int = 0
    models_extracted: int = 0

    # Progresso geral
    assessment_progress: float = 0.0
    extraction_progress: float = 0.0
    overall_progress: float = 0.0

    # Configurações
    default_instrument_id: UUID | None = None
    default_template_id: UUID | None = None

    # Timestamps
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def compute_overall_progress(
        cls,
        assessment_progress: float,
        extraction_progress: float,
    ) -> float:
        """Calcula progresso geral como média ponderada."""
        return round((assessment_progress + extraction_progress) / 2, 1)
