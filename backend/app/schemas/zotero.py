"""
Zotero Schemas.

Schemas Pydantic para integração com Zotero API.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# =================== REQUEST SCHEMAS ===================


class SaveCredentialsRequest(BaseModel):
    """Request para salvar credenciais do Zotero."""

    zotero_user_id: str = Field(..., alias="zoteroUserId", min_length=1)
    api_key: str = Field(..., alias="apiKey", min_length=1)
    library_type: Literal["user", "group"] = Field(..., alias="libraryType")

    model_config = ConfigDict(populate_by_name=True)


class FetchItemsRequest(BaseModel):
    """Request para buscar items de uma collection."""

    collection_key: str = Field(..., alias="collectionKey", min_length=1)
    limit: int = Field(default=100, ge=1, le=100)
    start: int = Field(default=0, ge=0)

    model_config = ConfigDict(populate_by_name=True)


class FetchAttachmentsRequest(BaseModel):
    """Request para buscar attachments de um item."""

    item_key: str = Field(..., alias="itemKey", min_length=1)

    model_config = ConfigDict(populate_by_name=True)


class DownloadAttachmentRequest(BaseModel):
    """Request para download de attachment."""

    attachment_key: str = Field(..., alias="attachmentKey", min_length=1)

    model_config = ConfigDict(populate_by_name=True)


class ImportToProjectRequest(BaseModel):
    """Request para importar items do Zotero para projeto."""

    project_id: str = Field(..., alias="projectId")
    collection_key: str = Field(..., alias="collectionKey")
    item_keys: list[str] = Field(default=[], alias="itemKeys")
    import_pdfs: bool = Field(default=True, alias="importPdfs")

    model_config = ConfigDict(populate_by_name=True)


class SyncCollectionRequest(BaseModel):
    project_id: str = Field(..., alias="projectId")
    collection_key: str = Field(..., alias="collectionKey", min_length=1)
    max_items: int = Field(default=1000, alias="maxItems", ge=1, le=10000)
    include_attachments: bool = Field(default=True, alias="includeAttachments")
    update_existing: bool = Field(default=True, alias="updateExisting")

    model_config = ConfigDict(populate_by_name=True)


class SyncStatusRequest(BaseModel):
    sync_run_id: str = Field(..., alias="syncRunId")

    model_config = ConfigDict(populate_by_name=True)


class SyncRetryFailedRequest(BaseModel):
    sync_run_id: str = Field(..., alias="syncRunId")
    limit: int = Field(default=100, ge=1, le=1000)

    model_config = ConfigDict(populate_by_name=True)


class SyncItemResultRequest(BaseModel):
    sync_run_id: str = Field(..., alias="syncRunId")
    status_filter: str | None = Field(default=None, alias="statusFilter")
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=200)

    model_config = ConfigDict(populate_by_name=True)


# =================== RESPONSE SCHEMAS ===================


class ZoteroCreator(BaseModel):
    """Autor ou criador no Zotero."""

    creator_type: str = Field(alias="creatorType")
    first_name: str | None = Field(default=None, alias="firstName")
    last_name: str | None = Field(default=None, alias="lastName")
    name: str | None = None  # Para corporate authors

    model_config = ConfigDict(populate_by_name=True)


class ZoteroItemData(BaseModel):
    """Dados de um item no Zotero."""

    key: str
    version: int
    item_type: str = Field(alias="itemType")
    title: str | None = None
    creators: list[ZoteroCreator] = []
    abstract_note: str | None = Field(default=None, alias="abstractNote")
    date: str | None = None

    # Campos de publicação
    publication_title: str | None = Field(default=None, alias="publicationTitle")
    journal_abbreviation: str | None = Field(default=None, alias="journalAbbreviation")
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None

    # Identificadores
    doi: str | None = Field(default=None, alias="DOI")
    issn: str | None = Field(default=None, alias="ISSN")
    url: str | None = None

    # Tags e notas
    tags: list[dict[str, str]] = []

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class ZoteroItem(BaseModel):
    """Item completo do Zotero."""

    key: str
    version: int
    library: dict[str, Any]
    links: dict[str, Any] = {}
    meta: dict[str, Any] = {}
    data: ZoteroItemData

    model_config = ConfigDict(extra="allow")


class ZoteroCollection(BaseModel):
    """Collection do Zotero."""

    key: str
    version: int
    name: str
    parent_collection: str | None = Field(default=None, alias="parentCollection")
    num_items: int | None = Field(default=None, alias="numItems")
    num_collections: int | None = Field(default=None, alias="numCollections")

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class ZoteroAttachment(BaseModel):
    """Attachment do Zotero."""

    key: str
    version: int
    link_mode: str = Field(alias="linkMode")
    content_type: str | None = Field(default=None, alias="contentType")
    filename: str | None = None
    title: str | None = None

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class SaveCredentialsResponse(BaseModel):
    """Response de salvar credenciais."""

    integration_id: str


class TestConnectionResponse(BaseModel):
    """Response de teste de conexão."""

    success: bool
    user_name: str | None = None
    user_id: str | None = None
    access: dict[str, Any] = {}
    error: str | None = None


class ListCollectionsResponse(BaseModel):
    """Response de listar collections."""

    collections: list[dict[str, Any]]


class FetchItemsResponse(BaseModel):
    """Response de buscar items."""

    items: list[dict[str, Any]]
    total_results: int | None = None
    has_more: bool = False


class FetchAttachmentsResponse(BaseModel):
    """Response de buscar attachments."""

    attachments: list[dict[str, Any]]


class DownloadAttachmentResponse(BaseModel):
    """Response de download de attachment."""

    base64: str
    filename: str
    content_type: str
    size: int


class ImportResult(BaseModel):
    """Resultado da importação de um item."""

    zotero_key: str
    article_id: str | None = None
    success: bool
    error: str | None = None
    pdf_imported: bool = False


class ImportToProjectResponse(BaseModel):
    """Response da importação para projeto."""

    total_items: int
    imported: int
    failed: int
    results: list[ImportResult]


class SyncCollectionResponse(BaseModel):
    sync_run_id: str = Field(alias="syncRunId")
    status: str
    message: str

    model_config = ConfigDict(populate_by_name=True)


class SyncCountsResponse(BaseModel):
    total_received: int = Field(alias="totalReceived")
    persisted: int
    updated: int
    skipped: int
    failed: int
    removed_at_source: int = Field(alias="removedAtSource")
    reactivated: int

    model_config = ConfigDict(populate_by_name=True)


class SyncStatusResponse(BaseModel):
    sync_run_id: str = Field(alias="syncRunId")
    status: str
    counts: SyncCountsResponse
    started_at: datetime = Field(alias="startedAt")
    completed_at: datetime | None = Field(default=None, alias="completedAt")
    trace_id: str = Field(alias="traceId")

    model_config = ConfigDict(populate_by_name=True)


class SyncRetryFailedResponse(BaseModel):
    sync_run_id: str = Field(alias="syncRunId")
    retry_of_sync_run_id: str = Field(alias="retryOfSyncRunId")
    queued_items: int = Field(alias="queuedItems")

    model_config = ConfigDict(populate_by_name=True)


class SyncItemResultEntry(BaseModel):
    zotero_item_key: str | None = Field(default=None, alias="zoteroItemKey")
    article_id: str | None = Field(default=None, alias="articleId")
    status: str
    error_code: str | None = Field(default=None, alias="errorCode")
    error_message: str | None = Field(default=None, alias="errorMessage")
    authority_rule_applied: str | None = Field(default=None, alias="authorityRuleApplied")
    processed_at: datetime = Field(alias="processedAt")

    model_config = ConfigDict(populate_by_name=True)


class SyncItemResultsResponse(BaseModel):
    items: list[SyncItemResultEntry]
    total: int
    offset: int
    limit: int
