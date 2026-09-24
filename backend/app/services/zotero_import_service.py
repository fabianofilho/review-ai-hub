"""Zotero import service."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any
from uuid import NAMESPACE_DNS, UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import LoggerMixin
from app.infrastructure.storage import StorageAdapter
from app.models.article import ArticleFile
from app.models.article_author import ArticleAuthorLink, ArticleSyncRun
from app.repositories.article_author_repository import (
    ArticleAuthorLinkRepository,
    ArticleAuthorRepository,
)
from app.repositories.article_repository import (
    ArticleFileRepository,
    ArticleRepository,
    ArticleSyncEventRepository,
    ArticleSyncRunRepository,
)
from app.services.article_source_normalization import normalize_zotero_item
from app.services.zotero_service import ZoteroService


@dataclass
class ZoteroImportItemResult:
    """Resultado de importacao de um item."""

    zotero_key: str
    title: str
    success: bool
    article_id: str | None = None
    error: str | None = None
    pdf_imported: bool = False


@dataclass
class ZoteroImportResult:
    """Resultado agregado da importacao."""

    total_items: int
    imported: int
    failed: int
    skipped: int
    updated: int = 0
    removed_at_source: int = 0
    reactivated: int = 0
    results: list[ZoteroImportItemResult] = field(default_factory=list)
    sync_run_id: str | None = None


class ZoteroImportService(LoggerMixin):
    """
    Service para importacao de itens do Zotero.

    Responsavel por:
    - Fetch de itens via ZoteroService
    - Criacao de artigos e arquivos
    - Upload de PDFs para storage
    """

    def __init__(
        self,
        db: AsyncSession,
        user_id: str,
        storage: StorageAdapter,
        trace_id: str,
    ):
        self.db = db
        self.user_id = user_id
        self.storage = storage
        self.trace_id = trace_id

        self._zotero = ZoteroService(db=db, user_id=user_id)
        self._articles = ArticleRepository(db)
        self._article_files = ArticleFileRepository(db)
        self._authors = ArticleAuthorRepository(db)
        self._author_links = ArticleAuthorLinkRepository(db)
        self._sync_runs = ArticleSyncRunRepository(db)
        self._sync_events = ArticleSyncEventRepository(db)

    async def create_sync_run(
        self,
        *,
        project_id: UUID,
        collection_key: str | None,
    ) -> ArticleSyncRun:
        return await self._sync_runs.create_run(
            project_id=project_id,
            requested_by_user_id=self._user_uuid(),
            source="zotero",
            source_collection_key=collection_key,
        )

    async def get_owned_sync_run(self, sync_run_id: UUID) -> ArticleSyncRun | None:
        return await self._sync_runs.get_owned_run(sync_run_id, self._user_uuid())

    async def import_collection(
        self,
        project_id: UUID,
        collection_key: str,
        max_items: int = 100,
        import_pdfs: bool = True,
        update_existing: bool = True,
        sync_run_id: UUID | None = None,
        predefined_items: list[dict[str, Any]] | None = None,
    ) -> ZoteroImportResult:
        """
        Importa itens de uma collection do Zotero.

        Args:
            project_id: ID do projeto.
            collection_key: Key da collection.
            max_items: Maximo de itens a importar.
            import_pdfs: Se deve importar PDFs.

        Returns:
            ZoteroImportResult com estatisticas.
        """
        self.logger.info(
            "zotero_import_start",
            trace_id=self.trace_id,
            project_id=str(project_id),
            collection_key=collection_key,
            max_items=max_items,
            import_pdfs=import_pdfs,
        )

        run = await self._ensure_run(
            project_id=project_id, collection_key=collection_key, sync_run_id=sync_run_id
        )
        run.status = "running"
        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(run)

        if predefined_items is None:
            items_result = await self._zotero.fetch_items(
                collection_key=collection_key,
                limit=max_items,
            )
            items = items_result.get("items", [])
        else:
            items = predefined_items

        initial_counts = {
            "total_received": len(items),
            "persisted": 0,
            "updated": 0,
            "skipped": 0,
            "failed": 0,
            "removed_at_source": 0,
            "reactivated": 0,
        }
        await self._sync_runs.update_counts(run, initial_counts, "running")
        await self.db.commit()
        await self.db.refresh(run)

        imported = 0
        failed = 0
        skipped = 0
        updated = 0
        removed_at_source = 0
        reactivated = 0
        results: list[ZoteroImportItemResult] = []
        seen_keys: set[str] = set()

        for item in items:
            try:
                result = await self._process_item(
                    item=item,
                    project_id=project_id,
                    collection_key=collection_key,
                    import_pdfs=import_pdfs,
                    update_existing=update_existing,
                    sync_run_id=run.id,
                )
                results.append(result)

                if result.success:
                    if result.error == "updated":
                        updated += 1
                    elif result.error == "reactivated":
                        reactivated += 1
                    else:
                        imported += 1
                elif result.error and "already exists" in result.error:
                    skipped += 1
                else:
                    failed += 1
                if result.zotero_key:
                    seen_keys.add(result.zotero_key)
            except Exception as exc:
                failed += 1
                results.append(
                    ZoteroImportItemResult(
                        zotero_key=item.get("key", "unknown"),
                        title=item.get("data", {}).get("title", "Unknown"),
                        success=False,
                        error=str(exc),
                    )
                )
                self.logger.error(
                    "zotero_item_import_failed",
                    trace_id=self.trace_id,
                    zotero_key=item.get("key"),
                    error=str(exc),
                )
                await self._sync_events.create_event(
                    project_id=project_id,
                    sync_run_id=run.id,
                    zotero_item_key=item.get("key"),
                    status="failed",
                    error_code="UNEXPECTED_ERROR",
                    error_message=str(exc),
                    event_payload={"item": item},
                )
            running_counts = {
                "total_received": len(items),
                "persisted": imported,
                "updated": updated,
                "skipped": skipped,
                "failed": failed,
                "removed_at_source": 0,
                "reactivated": reactivated,
            }
            await self._sync_runs.update_counts(run, running_counts, "running")
            await self.db.commit()
            await self.db.refresh(run)

        if predefined_items is None:
            removed_at_source = await self._mark_removed_items(
                project_id=project_id,
                collection_key=collection_key,
                seen_item_keys=seen_keys,
                sync_run_id=run.id,
            )

        self.logger.info(
            "zotero_import_complete",
            trace_id=self.trace_id,
            total_items=len(items),
            imported=imported,
            updated=updated,
            failed=failed,
            skipped=skipped,
            removed_at_source=removed_at_source,
            reactivated=reactivated,
        )

        counts = {
            "total_received": len(items),
            "persisted": imported,
            "updated": updated,
            "skipped": skipped,
            "failed": failed,
            "removed_at_source": removed_at_source,
            "reactivated": reactivated,
        }
        await self._sync_runs.update_counts(run, counts, "completed" if failed == 0 else "failed")
        await self.db.commit()
        await self.db.refresh(run)

        return ZoteroImportResult(
            total_items=len(items),
            imported=imported,
            failed=failed,
            skipped=skipped,
            updated=updated,
            removed_at_source=removed_at_source,
            reactivated=reactivated,
            results=results,
            sync_run_id=str(run.id),
        )

    async def retry_failed_items(
        self,
        *,
        project_id: UUID,
        source_run_id: UUID,
        target_run_id: UUID | None = None,
        limit: int = 100,
    ) -> tuple[ArticleSyncRun, ZoteroImportResult]:
        source_run = await self._sync_runs.get_owned_run(source_run_id, self._user_uuid())
        if not source_run:
            raise ValueError("Sync run not found")

        failed_events = await self._sync_events.list_failed_by_run(source_run_id, limit=limit)
        if not failed_events:
            raise ValueError("Original sync run has no failed items")

        if target_run_id:
            retry_run = await self._ensure_run(
                project_id=project_id,
                collection_key=source_run.source_collection_key or "",
                sync_run_id=target_run_id,
            )
        else:
            retry_run = await self.create_sync_run(
                project_id=project_id,
                collection_key=source_run.source_collection_key,
            )
        predefined_items = [
            (event.event_payload or {}).get("item")
            for event in failed_events
            if (event.event_payload or {}).get("item")
        ]
        result = await self.import_collection(
            project_id=project_id,
            collection_key=source_run.source_collection_key or "",
            max_items=len(predefined_items),
            import_pdfs=True,
            update_existing=True,
            sync_run_id=retry_run.id,
            predefined_items=predefined_items,
        )
        return retry_run, result

    async def _process_item(
        self,
        item: dict[str, Any],
        project_id: UUID,
        collection_key: str,
        import_pdfs: bool,
        update_existing: bool,
        sync_run_id: UUID,
    ) -> ZoteroImportItemResult:
        """Processa um item do Zotero."""
        zotero_key = item.get("key", "")
        data = item.get("data", {})
        title = data.get("title") or "Untitled"

        normalized = normalize_zotero_item(item=item, collection_key=collection_key)
        existing = await self._articles.get_by_canonical_identity(
            project_id=project_id,
            zotero_item_key=normalized.canonical_identity.get("zotero_item_key"),
            doi=normalized.canonical_identity.get("doi"),
            url_landing=normalized.canonical_identity.get("url_landing"),
        )
        if existing and not update_existing:
            await self._sync_events.create_event(
                project_id=project_id,
                sync_run_id=sync_run_id,
                zotero_item_key=zotero_key,
                article_id=existing.id,
                status="skipped",
                authority_rule_applied="source_parity_wins",
                event_payload={"item": item},
            )
            return ZoteroImportItemResult(
                zotero_key=zotero_key,
                title=title,
                success=False,
                article_id=str(existing.id),
                error="Article already exists",
            )

        payload = normalized.article_fields
        if existing:
            # Preserve local enrichment authority.
            payload["pdf_extracted_text"] = existing.pdf_extracted_text
            payload["semantic_abstract_text"] = existing.semantic_abstract_text
            payload["semantic_fulltext_text"] = existing.semantic_fulltext_text
            payload["sync_state"] = "active"
        saved_article, created = await self._articles.upsert_by_canonical_identity(
            project_id=project_id,
            payload=payload,
            canonical_identity=normalized.canonical_identity,
        )
        if existing and existing.sync_state == "removed_at_source":
            await self._articles.mark_reactivated(saved_article)

        pdf_imported = False
        if import_pdfs:
            pdf_imported = await self._import_pdf(
                article_id=saved_article.id,
                project_id=project_id,
                zotero_key=zotero_key,
            )

        await self._sync_author_links(saved_article.id, normalized.creator_rows)
        status = "success" if created else "updated"
        if existing and existing.sync_state == "removed_at_source":
            status = "reactivated"
        await self._sync_events.create_event(
            project_id=project_id,
            sync_run_id=sync_run_id,
            zotero_item_key=zotero_key,
            article_id=saved_article.id,
            status=status,
            authority_rule_applied="source_parity_wins+local_enrichment_wins",
            event_payload={"item": item},
        )

        return ZoteroImportItemResult(
            zotero_key=zotero_key,
            title=title,
            success=True,
            article_id=str(saved_article.id),
            pdf_imported=pdf_imported,
            error=status if status in {"updated", "reactivated"} else None,
        )

    async def _import_pdf(
        self,
        article_id: UUID,
        project_id: UUID,
        zotero_key: str,
    ) -> bool:
        """Importa o primeiro PDF disponivel para o item."""
        try:
            attachments_result = await self._zotero.fetch_attachments(zotero_key)
            attachments = attachments_result.get("attachments", [])

            pdf_attachments = [
                attachment
                for attachment in attachments
                if attachment.get("data", {}).get("contentType") == "application/pdf"
            ]
            if not pdf_attachments:
                return False

            attachment = pdf_attachments[0]
            attachment_key = attachment.get("key")
            if not attachment_key:
                return False

            download_result = await self._zotero.download_attachment(attachment_key)
            pdf_bytes = base64.b64decode(download_result["base64"])

            storage_key = f"{project_id}/{article_id}/{download_result['filename']}"
            await self.storage.upload(
                bucket="articles",
                path=storage_key,
                data=pdf_bytes,
                content_type=download_result.get("content_type", "application/pdf"),
            )

            article_file = ArticleFile(
                project_id=project_id,
                article_id=article_id,
                file_type=download_result.get("content_type", "application/pdf"),
                storage_key=storage_key,
                original_filename=download_result.get("filename"),
                bytes=len(pdf_bytes),
                file_role="MAIN",
            )

            await self._article_files.create(article_file)
            return True
        except Exception as exc:
            self.logger.warning(
                "zotero_pdf_import_failed",
                trace_id=self.trace_id,
                article_id=str(article_id),
                zotero_key=zotero_key,
                error=str(exc),
            )
            return False

    async def _sync_author_links(
        self, article_id: UUID, creator_rows: list[dict[str, Any]]
    ) -> None:
        links: list[ArticleAuthorLink] = []
        seen_link_keys: set[tuple[UUID, str]] = set()
        author_cache: dict[str, Any] = {}
        for row in creator_rows:
            display_name = row["display_name"]
            creator_type = row.get("creator_type") or "author"
            raw_creator = row.get("raw") if isinstance(row.get("raw"), dict) else {}
            cache_key = self._canonical_creator_key(display_name, creator_type, raw_creator)
            author = author_cache.get(cache_key)
            if author is None:
                author = await self._authors.get_or_create(
                    display_name,
                    source_hint={"creator_type": creator_type},
                )
                author_cache[cache_key] = author
            link_key = (author.id, creator_type)
            if link_key in seen_link_keys:
                continue
            seen_link_keys.add(link_key)
            links.append(
                ArticleAuthorLink(
                    article_id=article_id,
                    author_id=author.id,
                    author_order=len(links),
                    creator_type=creator_type,
                    raw_creator_payload=row.get("raw"),
                )
            )
        await self._author_links.replace_article_links(article_id, links)

    def _canonical_creator_key(
        self,
        display_name: str,
        creator_type: str,
        raw_creator: dict[str, Any],
    ) -> str:
        """
        Canonical key inspired by Zotero creator modes:
        - two-field personal names (firstName/lastName) => normalized family+given key
        - one-field names (institutions/unknown) => normalized literal key
        """
        first_name = str(raw_creator.get("firstName") or "").strip().lower()
        last_name = str(raw_creator.get("lastName") or "").strip().lower()
        field_mode = raw_creator.get("fieldMode")

        if first_name or last_name:
            return f"{creator_type}|person|{last_name}|{first_name}"

        normalized_display = " ".join(display_name.strip().lower().split())
        if field_mode == 1:
            return f"{creator_type}|onefield|{normalized_display}"

        if "," in normalized_display:
            left, right = [part.strip() for part in normalized_display.split(",", 1)]
            if left and right:
                return f"{creator_type}|person|{left}|{right}"

        tokens = normalized_display.split(" ")
        if len(tokens) == 2 and all(tokens):
            return f"{creator_type}|person|{tokens[1]}|{tokens[0]}"

        return f"{creator_type}|onefield|{normalized_display}"

    async def _mark_removed_items(
        self,
        *,
        project_id: UUID,
        collection_key: str,
        seen_item_keys: set[str],
        sync_run_id: UUID,
    ) -> int:
        removed_count = 0
        candidates = await self._articles.get_zotero_project_articles(project_id, collection_key)
        for article in candidates:
            if not article.zotero_item_key:
                continue
            if article.zotero_item_key in seen_item_keys:
                continue
            await self._articles.mark_removed_at_source(article)
            removed_count += 1
            await self._sync_events.create_event(
                project_id=project_id,
                sync_run_id=sync_run_id,
                zotero_item_key=article.zotero_item_key,
                article_id=article.id,
                status="removed_at_source",
                authority_rule_applied="source_parity_wins",
            )
        return removed_count

    async def _ensure_run(
        self,
        *,
        project_id: UUID,
        collection_key: str,
        sync_run_id: UUID | None,
    ) -> ArticleSyncRun:
        if sync_run_id:
            run = await self._sync_runs.get_by_id(sync_run_id)
            if run:
                return run
        return await self.create_sync_run(project_id=project_id, collection_key=collection_key)

    async def get_sync_status(self, sync_run_id: UUID) -> ArticleSyncRun | None:
        return await self.get_owned_sync_run(sync_run_id)

    async def get_sync_item_results(
        self,
        *,
        sync_run_id: UUID,
        status_filter: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list, int]:
        return await self._sync_events.list_run_events(
            sync_run_id=sync_run_id,
            status_filter=status_filter,
            offset=offset,
            limit=limit,
        )

    def _user_uuid(self) -> UUID:
        try:
            return UUID(self.user_id)
        except ValueError:
            return uuid5(NAMESPACE_DNS, self.user_id)
