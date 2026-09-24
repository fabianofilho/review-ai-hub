"""
Article author and sync models.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.article import Article


class ArticleAuthor(BaseModel):
    __tablename__ = "article_authors"

    normalized_name: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    orcid: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_hint: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    links: Mapped[list["ArticleAuthorLink"]] = relationship(
        "ArticleAuthorLink",
        back_populates="author",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_article_authors_normalized_name", "normalized_name"),
        {"schema": "public"},
    )


class ArticleAuthorLink(BaseModel):
    __tablename__ = "article_author_links"

    article_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.articles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    author_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.article_authors.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    author_order: Mapped[int] = mapped_column(Integer, nullable=False)
    creator_type: Mapped[str] = mapped_column(String, nullable=False, default="author")
    raw_creator_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    article: Mapped["Article"] = relationship("Article", back_populates="author_links")
    author: Mapped["ArticleAuthor"] = relationship("ArticleAuthor", back_populates="links")

    __table_args__ = (
        Index("idx_article_author_links_article_id", "article_id"),
        {"schema": "public"},
    )


class ArticleSyncRun(BaseModel):
    __tablename__ = "article_sync_runs"

    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    requested_by_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    source: Mapped[str] = mapped_column(String, nullable=False, default="zotero")
    source_collection_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_received: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    persisted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    removed_at_source: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reactivated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    events: Mapped[list["ArticleSyncEvent"]] = relationship(
        "ArticleSyncEvent",
        back_populates="sync_run",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_article_sync_runs_status", "status"),
        {"schema": "public"},
    )


class ArticleSyncEvent(BaseModel):
    __tablename__ = "article_sync_events"

    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    article_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.articles.id", ondelete="SET NULL"),
        nullable=True,
    )
    sync_run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.article_sync_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    zotero_item_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    authority_rule_applied: Mapped[str | None] = mapped_column(String, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    article: Mapped["Article | None"] = relationship("Article", back_populates="sync_events")
    sync_run: Mapped["ArticleSyncRun"] = relationship("ArticleSyncRun", back_populates="events")

    __table_args__ = (
        Index("idx_article_sync_events_status", "status"),
        {"schema": "public"},
    )
