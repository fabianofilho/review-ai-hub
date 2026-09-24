"""
Article Import Schemas.

Schemas for PDF metadata extraction and CSV (Scopus) import.
"""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# =================== PDF METADATA EXTRACTION ===================


class PDFMetadataExtractionRequest(BaseModel):
    """Request to extract metadata from an uploaded PDF via AI."""

    project_id: UUID = Field(..., alias="projectId")
    storage_key: str = Field(..., alias="storageKey")
    original_filename: str = Field(..., alias="originalFilename")
    file_bytes: int = Field(..., alias="fileBytes")

    model_config = ConfigDict(populate_by_name=True)


class ExtractedArticleMetadata(BaseModel):
    """Article metadata extracted from a PDF by AI."""

    title: str | None = None
    abstract: str | None = None
    authors: list[str] | None = None
    publication_year: int | None = Field(default=None, alias="publicationYear")
    publication_month: int | None = Field(default=None, alias="publicationMonth")
    journal_title: str | None = Field(default=None, alias="journalTitle")
    journal_issn: str | None = Field(default=None, alias="journalIssn")
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    doi: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    keywords: list[str] | None = None
    article_type: str | None = Field(default=None, alias="articleType")
    language: str | None = None
    url_landing: str | None = Field(default=None, alias="urlLanding")
    study_design: str | None = Field(default=None, alias="studyDesign")

    model_config = ConfigDict(populate_by_name=True)


class PDFMetadataExtractionResponse(BaseModel):
    """Response with extracted metadata from PDF."""

    metadata: ExtractedArticleMetadata
    input_tokens: int = Field(default=0, alias="inputTokens")
    output_tokens: int = Field(default=0, alias="outputTokens")
    duration_ms: float = Field(default=0, alias="durationMs")

    model_config = ConfigDict(populate_by_name=True)


# =================== CSV (SCOPUS) IMPORT ===================


class CSVImportRequest(BaseModel):
    """Request to import articles from a CSV file (Scopus format)."""

    project_id: UUID = Field(..., alias="projectId")
    articles: list[dict[str, Any]]

    model_config = ConfigDict(populate_by_name=True)


class CSVImportResult(BaseModel):
    """Result of a CSV import operation."""

    success_count: int = Field(..., alias="successCount")
    fail_count: int = Field(..., alias="failCount")
    duplicate_count: int = Field(..., alias="duplicateCount")
    errors: list[str] = []

    model_config = ConfigDict(populate_by_name=True)


# =================== PDF ARTICLE CREATION ===================


class PDFCreateArticleRequest(BaseModel):
    """Request to create an article from AI-extracted PDF metadata."""

    project_id: UUID = Field(..., alias="projectId")
    storage_key: str = Field(..., alias="storageKey")
    original_filename: str = Field(..., alias="originalFilename")
    file_bytes: int = Field(default=0, alias="fileBytes")

    # Article metadata (reviewed by user)
    title: str
    abstract: str | None = None
    authors: list[str] | None = None
    publication_year: int | None = Field(default=None, alias="publicationYear")
    publication_month: int | None = Field(default=None, alias="publicationMonth")
    journal_title: str | None = Field(default=None, alias="journalTitle")
    journal_issn: str | None = Field(default=None, alias="journalIssn")
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    doi: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    keywords: list[str] | None = None
    article_type: str | None = Field(default=None, alias="articleType")
    language: str | None = None
    url_landing: str | None = Field(default=None, alias="urlLanding")
    study_design: str | None = Field(default=None, alias="studyDesign")

    model_config = ConfigDict(populate_by_name=True)
