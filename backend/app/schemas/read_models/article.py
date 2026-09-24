"""
Article Read Models.

DTOs otimizados para listagem e detalhes de artigos.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ArticleFileReadModel(BaseModel):
    """Arquivo de artigo para leitura."""

    id: UUID
    file_type: str
    storage_key: str
    size_bytes: int | None = None

    model_config = ConfigDict(from_attributes=True)


class ArticleListReadModel(BaseModel):
    """
    Artigo para listagem.

    Inclui dados desnormalizados para evitar N+1 queries.
    """

    id: UUID
    title: str
    authors: str | None = None
    publication_year: int | None = None

    # Dados do projeto (JOIN)
    project_id: UUID
    project_name: str | None = None

    # Contagens (aggregations)
    files_count: int = 0
    assessments_count: int = 0
    extractions_count: int = 0

    # Status computado
    has_pdf: bool = False
    assessment_status: str | None = None  # pending, in_progress, completed

    # Timestamps
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ArticleDetailReadModel(BaseModel):
    """
    Artigo com detalhes completos.

    Inclui arquivos, assessments e extrações.
    """

    id: UUID
    title: str
    authors: str | None = None
    publication_year: int | None = None
    abstract: str | None = None
    doi: str | None = None
    journal: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None

    # Dados do projeto
    project_id: UUID
    project_name: str | None = None
    review_title: str | None = None

    # Arquivos (eager loaded)
    files: list[ArticleFileReadModel] = []

    # Resumo de assessments
    assessments_total: int = 0
    assessments_completed: int = 0
    assessments_pending: int = 0
    ai_assessments_count: int = 0

    # Resumo de extrações
    extractions_total: int = 0
    extractions_completed: int = 0
    models_extracted: int = 0

    # Status computados
    has_pdf: bool = False
    assessment_progress: float = 0.0  # 0-100%
    extraction_progress: float = 0.0  # 0-100%
    overall_status: str = "pending"  # pending, in_progress, completed

    # Metadados
    zotero_key: str | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def compute_progress(cls, completed: int, total: int) -> float:
        """Calcula progresso percentual."""
        if total == 0:
            return 0.0
        return round((completed / total) * 100, 1)

    @classmethod
    def compute_overall_status(
        cls,
        assessment_progress: float,
        extraction_progress: float,
    ) -> str:
        """Computa status geral do artigo."""
        if assessment_progress == 0 and extraction_progress == 0:
            return "pending"
        if assessment_progress >= 100 and extraction_progress >= 100:
            return "completed"
        return "in_progress"
