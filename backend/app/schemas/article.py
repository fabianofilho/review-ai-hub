"""
Article Schemas.

Schemas Pydantic para artigos científicos e arquivos.
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# =================== ARTICLE SCHEMAS ===================


class ArticleCreate(BaseModel):
    """Request para criar artigo."""

    project_id: UUID = Field(..., alias="projectId")
    title: str = Field(..., min_length=1)
    abstract: str | None = None
    language: str | None = None

    # Data de publicação
    publication_year: int | None = Field(default=None, alias="publicationYear", ge=1600, le=2500)
    publication_month: int | None = Field(default=None, alias="publicationMonth", ge=1, le=12)
    publication_day: int | None = Field(default=None, alias="publicationDay", ge=1, le=31)

    # Periódico
    journal_title: str | None = Field(default=None, alias="journalTitle")
    journal_issn: str | None = Field(default=None, alias="journalIssn")
    journal_eissn: str | None = Field(default=None, alias="journalEissn")
    journal_publisher: str | None = Field(default=None, alias="journalPublisher")
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None

    # Tipo e status
    article_type: str | None = Field(default=None, alias="articleType")
    publication_status: str | None = Field(default=None, alias="publicationStatus")
    open_access: bool | None = Field(default=None, alias="openAccess")
    license: str | None = None

    # Identificadores
    doi: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    arxiv_id: str | None = Field(default=None, alias="arxivId")
    pii: str | None = None

    # Arrays
    keywords: list[str] | None = None
    authors: list[str] | None = None
    mesh_terms: list[str] | None = Field(default=None, alias="meshTerms")

    # URLs
    url_landing: str | None = Field(default=None, alias="urlLanding")
    url_pdf: str | None = Field(default=None, alias="urlPdf")

    # Metadados adicionais
    study_design: str | None = Field(default=None, alias="studyDesign")
    registration: dict[str, Any] = {}
    funding: list[dict[str, Any]] = []
    conflicts_of_interest: str | None = Field(default=None, alias="conflictsOfInterest")
    data_availability: str | None = Field(default=None, alias="dataAvailability")

    # Fonte de ingestão
    ingestion_source: str | None = Field(default=None, alias="ingestionSource")
    source_payload: dict[str, Any] = Field(default={}, alias="sourcePayload")

    # Campos Zotero
    zotero_item_key: str | None = Field(default=None, alias="zoteroItemKey")
    zotero_collection_key: str | None = Field(default=None, alias="zoteroCollectionKey")
    zotero_version: int | None = Field(default=None, alias="zoteroVersion")

    model_config = ConfigDict(populate_by_name=True)


class ArticleUpdate(BaseModel):
    """Request para atualizar artigo."""

    title: str | None = Field(default=None, min_length=1)
    abstract: str | None = None
    language: str | None = None

    publication_year: int | None = Field(default=None, alias="publicationYear", ge=1600, le=2500)
    publication_month: int | None = Field(default=None, alias="publicationMonth", ge=1, le=12)
    publication_day: int | None = Field(default=None, alias="publicationDay", ge=1, le=31)

    journal_title: str | None = Field(default=None, alias="journalTitle")
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None

    doi: str | None = None
    pmid: str | None = None
    pmcid: str | None = None

    keywords: list[str] | None = None
    authors: list[str] | None = None

    study_design: str | None = Field(default=None, alias="studyDesign")

    model_config = ConfigDict(populate_by_name=True)


class ArticleResponse(BaseModel):
    """Response de artigo."""

    id: UUID
    project_id: UUID = Field(..., alias="projectId")
    title: str
    abstract: str | None = None
    language: str | None = None

    publication_year: int | None = Field(default=None, alias="publicationYear")
    publication_month: int | None = Field(default=None, alias="publicationMonth")
    publication_day: int | None = Field(default=None, alias="publicationDay")

    journal_title: str | None = Field(default=None, alias="journalTitle")
    journal_issn: str | None = Field(default=None, alias="journalIssn")
    journal_publisher: str | None = Field(default=None, alias="journalPublisher")
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None

    article_type: str | None = Field(default=None, alias="articleType")
    publication_status: str | None = Field(default=None, alias="publicationStatus")
    open_access: bool | None = Field(default=None, alias="openAccess")

    doi: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    arxiv_id: str | None = Field(default=None, alias="arxivId")

    keywords: list[str] | None = None
    authors: list[str] | None = None
    mesh_terms: list[str] | None = Field(default=None, alias="meshTerms")

    url_landing: str | None = Field(default=None, alias="urlLanding")
    url_pdf: str | None = Field(default=None, alias="urlPdf")

    study_design: str | None = Field(default=None, alias="studyDesign")
    registration: dict[str, Any] = {}
    funding: list[dict[str, Any]] = []

    ingestion_source: str | None = Field(default=None, alias="ingestionSource")

    zotero_item_key: str | None = Field(default=None, alias="zoteroItemKey")
    zotero_collection_key: str | None = Field(default=None, alias="zoteroCollectionKey")

    created_at: datetime = Field(..., alias="createdAt")
    updated_at: datetime = Field(..., alias="updatedAt")

    # Relacionamentos carregados
    files_count: int | None = Field(default=None, alias="filesCount")
    has_pdf: bool | None = Field(default=None, alias="hasPdf")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


# =================== ARTICLE FILE SCHEMAS ===================


class ArticleFileCreate(BaseModel):
    """Request para criar arquivo de artigo."""

    article_id: UUID = Field(..., alias="articleId")
    file_type: str = Field(..., alias="fileType")
    storage_key: str = Field(..., alias="storageKey")
    original_filename: str | None = Field(default=None, alias="originalFilename")
    bytes: int | None = None
    md5: str | None = None
    file_role: Literal[
        "MAIN", "SUPPLEMENT", "PROTOCOL", "DATASET", "APPENDIX", "FIGURE", "OTHER"
    ] = Field(default="MAIN", alias="fileRole")

    model_config = ConfigDict(populate_by_name=True)


class ArticleFileResponse(BaseModel):
    """Response de arquivo de artigo."""

    id: UUID
    project_id: UUID = Field(..., alias="projectId")
    article_id: UUID = Field(..., alias="articleId")
    file_type: str = Field(..., alias="fileType")
    storage_key: str = Field(..., alias="storageKey")
    original_filename: str | None = Field(default=None, alias="originalFilename")
    bytes: int | None = None
    file_role: str = Field(..., alias="fileRole")

    extraction_status: str = Field(default="pending", alias="extractionStatus")
    extraction_error: str | None = Field(default=None, alias="extractionError")
    extracted_at: datetime | None = Field(default=None, alias="extractedAt")

    has_text: bool = Field(default=False, alias="hasText")

    created_at: datetime = Field(..., alias="createdAt")
    updated_at: datetime = Field(..., alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


# =================== UPLOAD SCHEMAS ===================


class UploadUrlRequest(BaseModel):
    """Request para obter URL de upload."""

    article_id: UUID = Field(..., alias="articleId")
    filename: str
    content_type: str = Field(..., alias="contentType")
    file_role: Literal[
        "MAIN", "SUPPLEMENT", "PROTOCOL", "DATASET", "APPENDIX", "FIGURE", "OTHER"
    ] = Field(default="MAIN", alias="fileRole")

    model_config = ConfigDict(populate_by_name=True)


class UploadUrlResponse(BaseModel):
    """Response com URL de upload."""

    upload_url: str = Field(..., alias="uploadUrl")
    storage_key: str = Field(..., alias="storageKey")
    expires_at: datetime = Field(..., alias="expiresAt")

    model_config = ConfigDict(populate_by_name=True)


class ConfirmUploadRequest(BaseModel):
    """Request para confirmar upload."""

    article_id: UUID = Field(..., alias="articleId")
    storage_key: str = Field(..., alias="storageKey")
    original_filename: str = Field(..., alias="originalFilename")
    content_type: str = Field(..., alias="contentType")
    bytes: int
    file_role: Literal[
        "MAIN", "SUPPLEMENT", "PROTOCOL", "DATASET", "APPENDIX", "FIGURE", "OTHER"
    ] = Field(default="MAIN", alias="fileRole")

    model_config = ConfigDict(populate_by_name=True)


# =================== TEXT EXTRACTION SCHEMAS ===================


class ExtractTextRequest(BaseModel):
    """Request para extrair texto de PDF."""

    file_id: UUID = Field(..., alias="fileId")
    force: bool = False  # Forçar re-extração

    model_config = ConfigDict(populate_by_name=True)


class ExtractTextResponse(BaseModel):
    """Response de extração de texto."""

    file_id: UUID = Field(..., alias="fileId")
    status: Literal["pending", "completed", "failed"]
    pages: int | None = None
    characters: int | None = None
    error: str | None = None

    model_config = ConfigDict(populate_by_name=True)


# =================== LIST SCHEMAS ===================


class ArticleListItem(BaseModel):
    """Item de lista de artigos (resumido)."""

    id: UUID
    title: str
    authors: list[str] | None = None
    publication_year: int | None = Field(default=None, alias="publicationYear")
    journal_title: str | None = Field(default=None, alias="journalTitle")
    doi: str | None = None

    has_pdf: bool = Field(default=False, alias="hasPdf")
    extraction_status: str | None = Field(default=None, alias="extractionStatus")
    assessment_status: str | None = Field(default=None, alias="assessmentStatus")

    created_at: datetime = Field(..., alias="createdAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class ArticleListResponse(BaseModel):
    """Response de listagem de artigos."""

    items: list[ArticleListItem]
    total: int
    page: int = 1
    page_size: int = Field(..., alias="pageSize")
    has_more: bool = Field(..., alias="hasMore")

    model_config = ConfigDict(populate_by_name=True)


# =================== SEARCH SCHEMAS ===================


class ArticleSearchRequest(BaseModel):
    """Request para busca de artigos."""

    query: str | None = None
    project_id: UUID | None = Field(default=None, alias="projectId")

    # Filtros
    publication_year_min: int | None = Field(default=None, alias="publicationYearMin")
    publication_year_max: int | None = Field(default=None, alias="publicationYearMax")
    has_pdf: bool | None = Field(default=None, alias="hasPdf")
    ingestion_source: str | None = Field(default=None, alias="ingestionSource")

    # Paginação
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100, alias="pageSize")

    # Ordenação
    sort_by: Literal["created_at", "title", "publication_year"] = Field(
        default="created_at",
        alias="sortBy",
    )
    sort_order: Literal["asc", "desc"] = Field(default="desc", alias="sortOrder")

    model_config = ConfigDict(populate_by_name=True)
