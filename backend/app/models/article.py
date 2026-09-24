"""
Article Models.

Modelos para artigos científicos e seus arquivos.
"""

from datetime import datetime
from enum import Enum as PyEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel, PostgreSQLEnumType

if TYPE_CHECKING:
    from app.models.article_author import ArticleAuthorLink, ArticleSyncEvent
    from app.models.project import Project


class FileRole(str, PyEnum):
    """
    Papel/tipo do arquivo do artigo.

    Valores alinhados com o enum 'file_role' no PostgreSQL.
    """

    MAIN = "MAIN"
    SUPPLEMENT = "SUPPLEMENT"
    PROTOCOL = "PROTOCOL"
    DATASET = "DATASET"
    APPENDIX = "APPENDIX"
    FIGURE = "FIGURE"
    OTHER = "OTHER"


class Article(BaseModel):
    """
    Artigo científico incluído em um projeto de revisão.

    Contém metadados bibliográficos completos.

    Índices:
    - project_id: FK para projeto (index=True)
    - (publication_year, journal_title): busca por ano/periódico
    - title: trigram para busca por similaridade
    - keywords, mesh_terms: GIN para busca em arrays
    - source_payload: GIN para busca em JSONB
    - (project_id, zotero_item_key): unique parcial
    """

    __tablename__ = "articles"

    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Campos básicos
    title: Mapped[str] = mapped_column(Text, nullable=False)
    abstract: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str | None] = mapped_column(String, nullable=True)

    # Data de publicação
    publication_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    publication_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    publication_day: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Informações do periódico
    journal_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    journal_issn: Mapped[str | None] = mapped_column(String, nullable=True)
    journal_eissn: Mapped[str | None] = mapped_column(String, nullable=True)
    journal_publisher: Mapped[str | None] = mapped_column(Text, nullable=True)
    volume: Mapped[str | None] = mapped_column(String, nullable=True)
    issue: Mapped[str | None] = mapped_column(String, nullable=True)
    pages: Mapped[str | None] = mapped_column(String, nullable=True)

    # Tipo e status
    article_type: Mapped[str | None] = mapped_column(String, nullable=True)
    publication_status: Mapped[str | None] = mapped_column(String, nullable=True)
    open_access: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    license: Mapped[str | None] = mapped_column(String, nullable=True)

    # Identificadores
    doi: Mapped[str | None] = mapped_column(Text, nullable=True)
    pmid: Mapped[str | None] = mapped_column(Text, nullable=True)
    pmcid: Mapped[str | None] = mapped_column(Text, nullable=True)
    arxiv_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    pii: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Arrays de texto
    keywords: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    authors: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    mesh_terms: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)

    # URLs
    url_landing: Mapped[str | None] = mapped_column(Text, nullable=True)
    url_pdf: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Metadados adicionais
    study_design: Mapped[str | None] = mapped_column(String, nullable=True)
    registration: Mapped[dict] = mapped_column(JSONB, default={}, nullable=True)
    funding: Mapped[dict] = mapped_column(JSONB, default=[], nullable=True)
    conflicts_of_interest: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_availability: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Controle de versão e ingestão
    hash_fingerprint: Mapped[str | None] = mapped_column(Text, nullable=True)
    ingestion_source: Mapped[str | None] = mapped_column(String, nullable=True)
    source_payload: Mapped[dict] = mapped_column(JSONB, default={}, nullable=True)
    row_version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)

    # Campos Zotero
    zotero_item_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    zotero_collection_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    zotero_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sync_state: Mapped[str] = mapped_column(String, nullable=False, default="active")
    removed_at_source_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sync_conflict_log: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    pdf_extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    semantic_abstract_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    semantic_fulltext_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_lineage: Mapped[str | None] = mapped_column(String, nullable=True)

    # Screening phase (denormalized for fast queries and PRISMA counts)
    # Values: null (not screened), "title_abstract", "full_text", "included", "excluded"
    screening_phase: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Relationships
    project: Mapped["Project"] = relationship(
        "Project",
        back_populates="articles",
    )
    files: Mapped[list["ArticleFile"]] = relationship(
        "ArticleFile",
        back_populates="article",
        cascade="all, delete-orphan",
    )
    author_links: Mapped[list["ArticleAuthorLink"]] = relationship(
        "ArticleAuthorLink",
        back_populates="article",
        cascade="all, delete-orphan",
    )
    sync_events: Mapped[list["ArticleSyncEvent"]] = relationship(
        "ArticleSyncEvent",
        back_populates="article",
    )

    # Índices definidos via __table_args__ (Infrastructure as Code)
    __table_args__ = (
        # Índice composto para busca por ano/periódico
        Index("idx_articles_biblio", "publication_year", "journal_title"),
        # Índice trigram para busca por similaridade no título
        # Requer extensão pg_trgm habilitada
        Index(
            "idx_articles_trgm_title",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
        # Índices GIN para arrays (busca eficiente com @> e &&)
        Index("idx_articles_keywords", "keywords", postgresql_using="gin"),
        Index("idx_articles_mesh", "mesh_terms", postgresql_using="gin"),
        # Índice GIN para JSONB
        Index("idx_articles_source_payload_gin", "source_payload", postgresql_using="gin"),
        # NOTA: o unique partial index uq_articles_project_zotero_item é gerenciado
        # via SQL na migration inicial (CREATE UNIQUE INDEX ... WHERE zotero_item_key IS NOT NULL).
        # Não definir UniqueConstraint aqui para evitar conflito com autogenerate.
        {"schema": "public"},
    )

    def __repr__(self) -> str:
        return f"<Article {self.title[:50]}...>"


class ArticleFile(BaseModel):
    """
    Arquivo PDF ou outro documento associado a um artigo.

    Índices:
    - project_id, article_id: FKs indexadas
    - (article_id, file_role): busca por tipo de arquivo
    """

    __tablename__ = "article_files"

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

    file_type: Mapped[str] = mapped_column(String, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    original_filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    md5: Mapped[str | None] = mapped_column(Text, nullable=True)

    file_role: Mapped[str] = mapped_column(
        PostgreSQLEnumType("file_role"),
        default="MAIN",
        nullable=True,
    )

    # Texto extraído
    text_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    text_html: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Status de extração
    extraction_status: Mapped[str] = mapped_column(
        String,
        default="pending",
        nullable=True,
    )
    extraction_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    article: Mapped["Article"] = relationship(
        "Article",
        back_populates="files",
    )

    # Índices definidos via __table_args__
    __table_args__ = (
        # Índice composto para busca por artigo e tipo de arquivo
        Index("idx_article_files_article_role", "article_id", "file_role"),
        {"schema": "public"},
    )

    def __repr__(self) -> str:
        return f"<ArticleFile {self.storage_key}>"
