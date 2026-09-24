"""
Unit tests for ZoteroImportService paths not covered by test_zotero_import_service.py.

Every collaborator (repositories, ZoteroService, storage) is replaced by an autospec
mock, so the tests check what the service asks each collaborator to do and how it
aggregates the results, without touching the database or the network.
"""

import base64
from typing import Any
from unittest.mock import AsyncMock, MagicMock, create_autospec
from uuid import NAMESPACE_DNS, UUID, uuid4, uuid5

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.storage import StorageAdapter
from app.models.article import ArticleFile
from app.models.article_author import ArticleAuthorLink
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
from app.services.zotero_import_service import ZoteroImportItemResult, ZoteroImportService
from app.services.zotero_service import ZoteroService

USER_ID = UUID("11111111-2222-3333-4444-555555555555")


def _make_service(user_id: str = str(USER_ID)) -> ZoteroImportService:
    svc = ZoteroImportService(
        db=AsyncMock(spec=AsyncSession),
        user_id=user_id,
        storage=create_autospec(StorageAdapter, instance=True),
        trace_id="trace-flows",
    )
    svc._zotero = create_autospec(ZoteroService, instance=True)
    svc._articles = create_autospec(ArticleRepository, instance=True)
    svc._article_files = create_autospec(ArticleFileRepository, instance=True)
    svc._authors = create_autospec(ArticleAuthorRepository, instance=True)
    svc._author_links = create_autospec(ArticleAuthorLinkRepository, instance=True)
    svc._sync_runs = create_autospec(ArticleSyncRunRepository, instance=True)
    svc._sync_events = create_autospec(ArticleSyncEventRepository, instance=True)
    return svc


@pytest.fixture
def service() -> ZoteroImportService:
    return _make_service()


def _run() -> MagicMock:
    run = MagicMock()
    run.id = uuid4()
    run.status = "pending"
    return run


def _zotero_item(key: str, title: str | None = "A title", **extra: Any) -> dict[str, Any]:
    data: dict[str, Any] = {"DOI": "10.1000/XYZ", "url": "https://example.org/a/", **extra}
    if title is not None:
        data["title"] = title
    return {"key": key, "version": 7, "data": data}


# =================== RUN LIFECYCLE ===================


class TestRunLifecycle:
    async def test_create_sync_run_uses_user_uuid_and_zotero_source(
        self, service: ZoteroImportService
    ) -> None:
        project_id = uuid4()
        run = _run()
        service._sync_runs.create_run.return_value = run

        created = await service.create_sync_run(project_id=project_id, collection_key="COLL")

        assert created is run
        service._sync_runs.create_run.assert_awaited_once_with(
            project_id=project_id,
            requested_by_user_id=USER_ID,
            source="zotero",
            source_collection_key="COLL",
        )

    async def test_non_uuid_user_id_is_mapped_to_a_stable_uuid5(self) -> None:
        svc = _make_service(user_id="auth0|someone")
        svc._sync_runs.create_run.return_value = _run()

        await svc.create_sync_run(project_id=uuid4(), collection_key=None)

        kwargs = svc._sync_runs.create_run.await_args.kwargs
        assert kwargs["requested_by_user_id"] == uuid5(NAMESPACE_DNS, "auth0|someone")
        assert kwargs["source_collection_key"] is None

    async def test_get_sync_status_returns_run_owned_by_user(
        self, service: ZoteroImportService
    ) -> None:
        run_id = uuid4()
        run = _run()
        service._sync_runs.get_owned_run.return_value = run

        assert await service.get_sync_status(run_id) is run
        service._sync_runs.get_owned_run.assert_awaited_once_with(run_id, USER_ID)

    async def test_get_owned_sync_run_returns_none_for_foreign_run(
        self, service: ZoteroImportService
    ) -> None:
        service._sync_runs.get_owned_run.return_value = None

        assert await service.get_owned_sync_run(uuid4()) is None

    async def test_get_sync_item_results_delegates_filters_and_paging(
        self, service: ZoteroImportService
    ) -> None:
        run_id = uuid4()
        events = [MagicMock(), MagicMock()]
        service._sync_events.list_run_events.return_value = (events, 12)

        result = await service.get_sync_item_results(
            sync_run_id=run_id, status_filter="failed", offset=10, limit=2
        )

        assert result == (events, 12)
        service._sync_events.list_run_events.assert_awaited_once_with(
            sync_run_id=run_id, status_filter="failed", offset=10, limit=2
        )

    async def test_ensure_run_reuses_existing_run(self, service: ZoteroImportService) -> None:
        run = _run()
        service._sync_runs.get_by_id.return_value = run

        result = await service._ensure_run(
            project_id=uuid4(), collection_key="COLL", sync_run_id=run.id
        )

        assert result is run
        service._sync_runs.get_by_id.assert_awaited_once_with(run.id)
        service._sync_runs.create_run.assert_not_awaited()

    async def test_ensure_run_creates_run_when_id_is_unknown(
        self, service: ZoteroImportService
    ) -> None:
        project_id = uuid4()
        new_run = _run()
        service._sync_runs.get_by_id.return_value = None
        service._sync_runs.create_run.return_value = new_run

        result = await service._ensure_run(
            project_id=project_id, collection_key="COLL", sync_run_id=uuid4()
        )

        assert result is new_run
        service._sync_runs.create_run.assert_awaited_once_with(
            project_id=project_id,
            requested_by_user_id=USER_ID,
            source="zotero",
            source_collection_key="COLL",
        )

    async def test_ensure_run_without_id_creates_run(self, service: ZoteroImportService) -> None:
        new_run = _run()
        service._sync_runs.create_run.return_value = new_run

        result = await service._ensure_run(
            project_id=uuid4(), collection_key="COLL", sync_run_id=None
        )

        assert result is new_run
        service._sync_runs.get_by_id.assert_not_awaited()


# =================== IMPORT COLLECTION ===================


class TestImportCollection:
    async def test_counts_every_outcome_and_marks_run_failed(
        self, service: ZoteroImportService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project_id = uuid4()
        run = _run()
        monkeypatch.setattr(service, "_ensure_run", AsyncMock(return_value=run))
        mark_removed = AsyncMock(return_value=0)
        monkeypatch.setattr(service, "_mark_removed_items", mark_removed)

        items = [
            {"key": "NEW", "data": {"title": "New"}},
            {"key": "UPD", "data": {"title": "Updated"}},
            {"key": "REA", "data": {"title": "Reactivated"}},
            {"key": "DUP", "data": {"title": "Duplicate"}},
            {"key": "BAD", "data": {"title": "Bad"}},
            {"key": "EXC", "data": {"title": "Explodes"}},
        ]
        outcomes: dict[str, ZoteroImportItemResult | Exception] = {
            "NEW": ZoteroImportItemResult(zotero_key="NEW", title="New", success=True),
            "UPD": ZoteroImportItemResult(
                zotero_key="UPD", title="Updated", success=True, error="updated"
            ),
            "REA": ZoteroImportItemResult(
                zotero_key="REA", title="Reactivated", success=True, error="reactivated"
            ),
            "DUP": ZoteroImportItemResult(
                zotero_key="DUP", title="Duplicate", success=False, error="Article already exists"
            ),
            "BAD": ZoteroImportItemResult(
                zotero_key="BAD", title="Bad", success=False, error="validation error"
            ),
            "EXC": RuntimeError("database exploded"),
        }

        async def fake_process_item(**kwargs: Any) -> ZoteroImportItemResult:
            outcome = outcomes[kwargs["item"]["key"]]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        process_item = AsyncMock(side_effect=fake_process_item)
        monkeypatch.setattr(service, "_process_item", process_item)

        result = await service.import_collection(
            project_id=project_id,
            collection_key="COLL",
            import_pdfs=False,
            update_existing=True,
            predefined_items=items,
        )

        assert result.total_items == 6
        assert result.imported == 1
        assert result.updated == 1
        assert result.reactivated == 1
        assert result.skipped == 1
        assert result.failed == 2
        assert result.removed_at_source == 0
        assert result.sync_run_id == str(run.id)
        assert [r.zotero_key for r in result.results] == ["NEW", "UPD", "REA", "DUP", "BAD", "EXC"]
        assert result.results[-1].success is False
        assert result.results[-1].error == "database exploded"
        assert result.results[-1].title == "Explodes"

        # Predefined items never hit the Zotero API and never mark removals.
        service._zotero.fetch_items.assert_not_awaited()
        mark_removed.assert_not_awaited()

        first_call = process_item.await_args_list[0].kwargs
        assert first_call["project_id"] == project_id
        assert first_call["collection_key"] == "COLL"
        assert first_call["import_pdfs"] is False
        assert first_call["update_existing"] is True
        assert first_call["sync_run_id"] == run.id

        service._sync_events.create_event.assert_awaited_once_with(
            project_id=project_id,
            sync_run_id=run.id,
            zotero_item_key="EXC",
            status="failed",
            error_code="UNEXPECTED_ERROR",
            error_message="database exploded",
            event_payload={"item": items[-1]},
        )

        final_counts, final_status = service._sync_runs.update_counts.await_args_list[-1].args[1:]
        assert final_status == "failed"
        assert final_counts == {
            "total_received": 6,
            "persisted": 1,
            "updated": 1,
            "skipped": 1,
            "failed": 2,
            "removed_at_source": 0,
            "reactivated": 1,
        }
        # One initial update, one per item and one final update.
        assert service._sync_runs.update_counts.await_count == len(items) + 2
        assert run.status == "running"

    async def test_unexpected_error_on_item_without_key_uses_placeholders(
        self, service: ZoteroImportService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        run = _run()
        monkeypatch.setattr(service, "_ensure_run", AsyncMock(return_value=run))
        monkeypatch.setattr(service, "_process_item", AsyncMock(side_effect=KeyError("key")))

        result = await service.import_collection(
            project_id=uuid4(), collection_key="COLL", predefined_items=[{}]
        )

        assert result.failed == 1
        item_result = result.results[0]
        assert item_result.zotero_key == "unknown"
        assert item_result.title == "Unknown"
        assert service._sync_events.create_event.await_args.kwargs["zotero_item_key"] is None

    async def test_fetches_items_and_marks_missing_ones_removed(
        self, service: ZoteroImportService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project_id = uuid4()
        run = _run()
        monkeypatch.setattr(service, "_ensure_run", AsyncMock(return_value=run))
        service._zotero.fetch_items.return_value = {
            "items": [{"key": "A", "data": {}}, {"key": "B", "data": {}}]
        }
        monkeypatch.setattr(
            service,
            "_process_item",
            AsyncMock(
                side_effect=[
                    ZoteroImportItemResult(zotero_key="A", title="A", success=True),
                    ZoteroImportItemResult(zotero_key="", title="B", success=True),
                ]
            ),
        )
        mark_removed = AsyncMock(return_value=3)
        monkeypatch.setattr(service, "_mark_removed_items", mark_removed)

        result = await service.import_collection(
            project_id=project_id, collection_key="COLL", max_items=25
        )

        service._zotero.fetch_items.assert_awaited_once_with(collection_key="COLL", limit=25)
        # Results without a key are not considered "seen" at the source.
        mark_removed.assert_awaited_once_with(
            project_id=project_id,
            collection_key="COLL",
            seen_item_keys={"A"},
            sync_run_id=run.id,
        )
        assert result.imported == 2
        assert result.removed_at_source == 3
        final_counts, final_status = service._sync_runs.update_counts.await_args_list[-1].args[1:]
        assert final_status == "completed"
        assert final_counts["removed_at_source"] == 3
        assert final_counts["persisted"] == 2

    async def test_empty_fetch_result_completes_without_items(
        self, service: ZoteroImportService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        run = _run()
        monkeypatch.setattr(service, "_ensure_run", AsyncMock(return_value=run))
        monkeypatch.setattr(service, "_mark_removed_items", AsyncMock(return_value=0))
        process_item = AsyncMock()
        monkeypatch.setattr(service, "_process_item", process_item)
        service._zotero.fetch_items.return_value = {}

        result = await service.import_collection(project_id=uuid4(), collection_key="COLL")

        assert result.total_items == 0
        assert result.results == []
        process_item.assert_not_awaited()
        assert service._sync_runs.update_counts.await_args_list[-1].args[2] == "completed"


# =================== RETRY FAILED ITEMS ===================


class TestRetryFailedItems:
    async def test_unknown_source_run_raises(self, service: ZoteroImportService) -> None:
        service._sync_runs.get_owned_run.return_value = None

        with pytest.raises(ValueError, match="Sync run not found"):
            await service.retry_failed_items(project_id=uuid4(), source_run_id=uuid4())

        service._sync_events.list_failed_by_run.assert_not_awaited()

    async def test_retries_items_from_failed_events_in_new_run(
        self, service: ZoteroImportService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project_id = uuid4()
        source_run_id = uuid4()
        source_run = MagicMock(source_collection_key="COLL")
        service._sync_runs.get_owned_run.return_value = source_run
        item_a = {"key": "A", "data": {"title": "A"}}
        item_b = {"key": "B", "data": {"title": "B"}}
        service._sync_events.list_failed_by_run.return_value = [
            MagicMock(event_payload={"item": item_a}),
            MagicMock(event_payload=None),
            MagicMock(event_payload={"other": 1}),
            MagicMock(event_payload={"item": item_b}),
        ]
        retry_run = _run()
        service._sync_runs.create_run.return_value = retry_run
        import_result = MagicMock()
        import_collection = AsyncMock(return_value=import_result)
        monkeypatch.setattr(service, "import_collection", import_collection)

        run, result = await service.retry_failed_items(
            project_id=project_id, source_run_id=source_run_id, limit=5
        )

        assert run is retry_run
        assert result is import_result
        service._sync_runs.get_owned_run.assert_awaited_once_with(source_run_id, USER_ID)
        service._sync_events.list_failed_by_run.assert_awaited_once_with(source_run_id, limit=5)
        service._sync_runs.create_run.assert_awaited_once_with(
            project_id=project_id,
            requested_by_user_id=USER_ID,
            source="zotero",
            source_collection_key="COLL",
        )
        import_collection.assert_awaited_once_with(
            project_id=project_id,
            collection_key="COLL",
            max_items=2,
            import_pdfs=True,
            update_existing=True,
            sync_run_id=retry_run.id,
            predefined_items=[item_a, item_b],
        )

    async def test_retry_into_existing_target_run(
        self, service: ZoteroImportService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project_id = uuid4()
        target_run_id = uuid4()
        service._sync_runs.get_owned_run.return_value = MagicMock(source_collection_key=None)
        item = {"key": "A", "data": {}}
        service._sync_events.list_failed_by_run.return_value = [
            MagicMock(event_payload={"item": item})
        ]
        target_run = _run()
        ensure_run = AsyncMock(return_value=target_run)
        monkeypatch.setattr(service, "_ensure_run", ensure_run)
        import_collection = AsyncMock(return_value=MagicMock())
        monkeypatch.setattr(service, "import_collection", import_collection)

        run, _ = await service.retry_failed_items(
            project_id=project_id, source_run_id=uuid4(), target_run_id=target_run_id
        )

        assert run is target_run
        ensure_run.assert_awaited_once_with(
            project_id=project_id, collection_key="", sync_run_id=target_run_id
        )
        service._sync_runs.create_run.assert_not_awaited()
        kwargs = import_collection.await_args.kwargs
        assert kwargs["collection_key"] == ""
        assert kwargs["sync_run_id"] == target_run.id
        assert kwargs["predefined_items"] == [item]


# =================== PROCESS ITEM ===================


class TestProcessItem:
    async def test_existing_article_is_skipped_when_updates_are_disabled(
        self, service: ZoteroImportService
    ) -> None:
        project_id = uuid4()
        run_id = uuid4()
        existing = MagicMock(id=uuid4(), sync_state="active")
        service._articles.get_by_canonical_identity.return_value = existing
        item = _zotero_item("K1", title="Known")

        result = await service._process_item(
            item=item,
            project_id=project_id,
            collection_key="COLL",
            import_pdfs=True,
            update_existing=False,
            sync_run_id=run_id,
        )

        assert result == ZoteroImportItemResult(
            zotero_key="K1",
            title="Known",
            success=False,
            article_id=str(existing.id),
            error="Article already exists",
        )
        service._articles.get_by_canonical_identity.assert_awaited_once_with(
            project_id=project_id,
            zotero_item_key="K1",
            doi="10.1000/xyz",
            url_landing="https://example.org/a",
        )
        service._articles.upsert_by_canonical_identity.assert_not_awaited()
        service._zotero.fetch_attachments.assert_not_awaited()
        service._sync_events.create_event.assert_awaited_once_with(
            project_id=project_id,
            sync_run_id=run_id,
            zotero_item_key="K1",
            article_id=existing.id,
            status="skipped",
            authority_rule_applied="source_parity_wins",
            event_payload={"item": item},
        )

    async def test_new_article_is_created_with_authors_and_success_event(
        self, service: ZoteroImportService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project_id = uuid4()
        run_id = uuid4()
        saved = MagicMock(id=uuid4())
        service._articles.get_by_canonical_identity.return_value = None
        service._articles.upsert_by_canonical_identity.return_value = (saved, True)
        sync_links = AsyncMock()
        monkeypatch.setattr(service, "_sync_author_links", sync_links)
        import_pdf = AsyncMock()
        monkeypatch.setattr(service, "_import_pdf", import_pdf)
        item = _zotero_item(
            "K2",
            title=None,
            creators=[{"creatorType": "author", "firstName": "Ada", "lastName": "Lovelace"}],
        )

        result = await service._process_item(
            item=item,
            project_id=project_id,
            collection_key="COLL",
            import_pdfs=False,
            update_existing=True,
            sync_run_id=run_id,
        )

        assert result.success is True
        assert result.title == "Untitled"
        assert result.article_id == str(saved.id)
        assert result.error is None
        assert result.pdf_imported is False
        import_pdf.assert_not_awaited()

        upsert_kwargs = service._articles.upsert_by_canonical_identity.await_args.kwargs
        assert upsert_kwargs["project_id"] == project_id
        assert upsert_kwargs["canonical_identity"] == {
            "zotero_item_key": "K2",
            "doi": "10.1000/xyz",
            "url_landing": "https://example.org/a",
        }
        payload = upsert_kwargs["payload"]
        assert payload["zotero_item_key"] == "K2"
        assert payload["zotero_collection_key"] == "COLL"
        assert payload["ingestion_source"] == "zotero"
        assert payload["authors"] == ["Lovelace, Ada"]
        # A brand new article has no local enrichment to preserve.
        assert "pdf_extracted_text" not in payload

        sync_links.assert_awaited_once()
        link_article_id, creator_rows = sync_links.await_args.args
        assert link_article_id == saved.id
        assert [row["display_name"] for row in creator_rows] == ["Lovelace, Ada"]

        service._articles.mark_reactivated.assert_not_awaited()
        event_kwargs = service._sync_events.create_event.await_args.kwargs
        assert event_kwargs["status"] == "success"
        assert event_kwargs["article_id"] == saved.id
        assert event_kwargs["authority_rule_applied"] == (
            "source_parity_wins+local_enrichment_wins"
        )

    async def test_existing_article_keeps_local_enrichment_and_imports_pdf(
        self, service: ZoteroImportService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project_id = uuid4()
        existing = MagicMock(
            id=uuid4(),
            sync_state="active",
            pdf_extracted_text="full text",
            semantic_abstract_text="abstract embedding text",
            semantic_fulltext_text="fulltext embedding text",
        )
        service._articles.get_by_canonical_identity.return_value = existing
        service._articles.upsert_by_canonical_identity.return_value = (existing, False)
        monkeypatch.setattr(service, "_sync_author_links", AsyncMock())
        import_pdf = AsyncMock(return_value=True)
        monkeypatch.setattr(service, "_import_pdf", import_pdf)

        result = await service._process_item(
            item=_zotero_item("K3", title="Refreshed"),
            project_id=project_id,
            collection_key="COLL",
            import_pdfs=True,
            update_existing=True,
            sync_run_id=uuid4(),
        )

        assert result.success is True
        assert result.error == "updated"
        assert result.pdf_imported is True
        import_pdf.assert_awaited_once_with(
            article_id=existing.id, project_id=project_id, zotero_key="K3"
        )
        payload = service._articles.upsert_by_canonical_identity.await_args.kwargs["payload"]
        assert payload["title"] == "Refreshed"
        assert payload["pdf_extracted_text"] == "full text"
        assert payload["semantic_abstract_text"] == "abstract embedding text"
        assert payload["semantic_fulltext_text"] == "fulltext embedding text"
        assert payload["sync_state"] == "active"
        service._articles.mark_reactivated.assert_not_awaited()
        assert service._sync_events.create_event.await_args.kwargs["status"] == "updated"


# =================== PDF IMPORT ===================


class TestImportPdf:
    async def test_returns_false_without_pdf_attachments(
        self, service: ZoteroImportService
    ) -> None:
        service._zotero.fetch_attachments.return_value = {
            "attachments": [
                {"key": "HTML", "data": {"contentType": "text/html"}},
                {"key": "NODATA"},
            ]
        }

        assert await service._import_pdf(uuid4(), uuid4(), "K1") is False
        service._zotero.fetch_attachments.assert_awaited_once_with("K1")
        service._zotero.download_attachment.assert_not_awaited()
        service.storage.upload.assert_not_awaited()

    async def test_returns_false_when_pdf_attachment_has_no_key(
        self, service: ZoteroImportService
    ) -> None:
        service._zotero.fetch_attachments.return_value = {
            "attachments": [{"data": {"contentType": "application/pdf"}}]
        }

        assert await service._import_pdf(uuid4(), uuid4(), "K1") is False
        service._zotero.download_attachment.assert_not_awaited()

    async def test_uploads_first_pdf_and_records_article_file(
        self, service: ZoteroImportService
    ) -> None:
        project_id = uuid4()
        article_id = uuid4()
        pdf_bytes = b"%PDF-1.4 fake pdf body"
        service._zotero.fetch_attachments.return_value = {
            "attachments": [
                {"key": "SNAP", "data": {"contentType": "text/html"}},
                {"key": "PDF1", "data": {"contentType": "application/pdf"}},
                {"key": "PDF2", "data": {"contentType": "application/pdf"}},
            ]
        }
        service._zotero.download_attachment.return_value = {
            "base64": base64.b64encode(pdf_bytes).decode(),
            "filename": "paper.pdf",
            "content_type": "application/x-pdf",
        }

        assert await service._import_pdf(article_id, project_id, "K1") is True

        service._zotero.download_attachment.assert_awaited_once_with("PDF1")
        expected_key = f"{project_id}/{article_id}/paper.pdf"
        service.storage.upload.assert_awaited_once_with(
            bucket="articles",
            path=expected_key,
            data=pdf_bytes,
            content_type="application/x-pdf",
        )
        service._article_files.create.assert_awaited_once()
        article_file = service._article_files.create.await_args.args[0]
        assert isinstance(article_file, ArticleFile)
        assert article_file.project_id == project_id
        assert article_file.article_id == article_id
        assert article_file.file_type == "application/x-pdf"
        assert article_file.storage_key == expected_key
        assert article_file.original_filename == "paper.pdf"
        assert article_file.bytes == len(pdf_bytes)
        assert article_file.file_role == "MAIN"

    async def test_content_type_defaults_to_pdf(self, service: ZoteroImportService) -> None:
        service._zotero.fetch_attachments.return_value = {
            "attachments": [{"key": "PDF1", "data": {"contentType": "application/pdf"}}]
        }
        service._zotero.download_attachment.return_value = {
            "base64": base64.b64encode(b"pdf").decode(),
            "filename": "doc.pdf",
        }

        assert await service._import_pdf(uuid4(), uuid4(), "K1") is True

        assert service.storage.upload.await_args.kwargs["content_type"] == "application/pdf"
        article_file = service._article_files.create.await_args.args[0]
        assert article_file.file_type == "application/pdf"

    async def test_download_failure_is_swallowed(self, service: ZoteroImportService) -> None:
        service._zotero.fetch_attachments.return_value = {
            "attachments": [{"key": "PDF1", "data": {"contentType": "application/pdf"}}]
        }
        service._zotero.download_attachment.side_effect = RuntimeError("zotero down")

        assert await service._import_pdf(uuid4(), uuid4(), "K1") is False
        service.storage.upload.assert_not_awaited()
        service._article_files.create.assert_not_awaited()

    async def test_storage_failure_does_not_record_file(self, service: ZoteroImportService) -> None:
        service._zotero.fetch_attachments.return_value = {
            "attachments": [{"key": "PDF1", "data": {"contentType": "application/pdf"}}]
        }
        service._zotero.download_attachment.return_value = {
            "base64": base64.b64encode(b"pdf").decode(),
            "filename": "doc.pdf",
        }
        service.storage.upload.side_effect = OSError("bucket unavailable")

        assert await service._import_pdf(uuid4(), uuid4(), "K1") is False
        service._article_files.create.assert_not_awaited()


# =================== AUTHOR LINKS ===================


class TestSyncAuthorLinks:
    async def test_deduplicates_creators_and_orders_links(
        self, service: ZoteroImportService
    ) -> None:
        article_id = uuid4()
        authors: dict[str, MagicMock] = {}

        async def get_or_create(display_name: str, **kwargs: Any) -> MagicMock:
            return authors.setdefault(display_name, MagicMock(id=uuid4()))

        service._authors.get_or_create.side_effect = get_or_create
        ada_raw = {"creatorType": "author", "firstName": "Ada", "lastName": "Lovelace"}
        rows = [
            {"creator_type": "author", "display_name": "Lovelace, Ada", "raw": ada_raw},
            # Same person again: served from the per-call cache.
            {"creator_type": "author", "display_name": "Lovelace, Ada", "raw": dict(ada_raw)},
            # Same name as a one-field creator: different cache key, same author row.
            {
                "creator_type": "author",
                "display_name": "Lovelace, Ada",
                "raw": {"name": "Lovelace, Ada", "fieldMode": 1},
            },
            # Same person with another role gets its own link.
            {"creator_type": "editor", "display_name": "Lovelace, Ada", "raw": ada_raw},
            # Missing creator type and non-dict raw payload.
            {"display_name": "World Health Organization", "raw": "WHO"},
        ]

        await service._sync_author_links(article_id, rows)

        assert service._authors.get_or_create.await_count == 4
        service._authors.get_or_create.assert_any_await(
            "World Health Organization", source_hint={"creator_type": "author"}
        )
        service._authors.get_or_create.assert_any_await(
            "Lovelace, Ada", source_hint={"creator_type": "editor"}
        )

        service._author_links.replace_article_links.assert_awaited_once()
        called_article_id, links = service._author_links.replace_article_links.await_args.args
        assert called_article_id == article_id
        assert all(isinstance(link, ArticleAuthorLink) for link in links)
        assert [(link.author_id, link.creator_type, link.author_order) for link in links] == [
            (authors["Lovelace, Ada"].id, "author", 0),
            (authors["Lovelace, Ada"].id, "editor", 1),
            (authors["World Health Organization"].id, "author", 2),
        ]
        assert all(link.article_id == article_id for link in links)
        assert links[0].raw_creator_payload == ada_raw
        assert links[2].raw_creator_payload == "WHO"

    async def test_no_creators_clears_links(self, service: ZoteroImportService) -> None:
        article_id = uuid4()

        await service._sync_author_links(article_id, [])

        service._authors.get_or_create.assert_not_awaited()
        service._author_links.replace_article_links.assert_awaited_once_with(article_id, [])


class TestCanonicalCreatorKey:
    @pytest.mark.parametrize(
        ("display_name", "creator_type", "raw", "expected"),
        [
            (
                "ignored",
                "author",
                {"firstName": " Ada ", "lastName": "LOVELACE"},
                "author|person|lovelace|ada",
            ),
            ("Doe", "editor", {"lastName": "Doe"}, "editor|person|doe|"),
            (
                "World  Health Organization",
                "author",
                {"name": "World Health Organization", "fieldMode": 1},
                "author|onefield|world health organization",
            ),
            ("Smith, John", "author", {"fieldMode": 1}, "author|onefield|smith, john"),
            ("  Smith ,  John ", "author", {}, "author|person|smith|john"),
            (",John", "author", {}, "author|onefield|,john"),
            ("John   Smith", "author", {}, "author|person|smith|john"),
            (
                "Cochrane Collaboration Group",
                "author",
                {},
                "author|onefield|cochrane collaboration group",
            ),
            ("Plato", "author", {}, "author|onefield|plato"),
        ],
    )
    def test_canonical_keys(
        self,
        service: ZoteroImportService,
        display_name: str,
        creator_type: str,
        raw: dict[str, Any],
        expected: str,
    ) -> None:
        assert service._canonical_creator_key(display_name, creator_type, raw) == expected


# =================== REMOVED AT SOURCE ===================


class TestMarkRemovedItems:
    async def test_marks_only_unseen_keyed_articles(self, service: ZoteroImportService) -> None:
        project_id = uuid4()
        run_id = uuid4()
        without_key = MagicMock(id=uuid4(), zotero_item_key=None)
        seen = MagicMock(id=uuid4(), zotero_item_key="SEEN")
        gone_one = MagicMock(id=uuid4(), zotero_item_key="GONE1")
        gone_two = MagicMock(id=uuid4(), zotero_item_key="GONE2")
        service._articles.get_zotero_project_articles.return_value = [
            without_key,
            seen,
            gone_one,
            gone_two,
        ]

        removed = await service._mark_removed_items(
            project_id=project_id,
            collection_key="COLL",
            seen_item_keys={"SEEN"},
            sync_run_id=run_id,
        )

        assert removed == 2
        service._articles.get_zotero_project_articles.assert_awaited_once_with(project_id, "COLL")
        marked = [call.args[0] for call in service._articles.mark_removed_at_source.await_args_list]
        assert marked == [gone_one, gone_two]
        events = [call.kwargs for call in service._sync_events.create_event.await_args_list]
        assert events == [
            {
                "project_id": project_id,
                "sync_run_id": run_id,
                "zotero_item_key": article.zotero_item_key,
                "article_id": article.id,
                "status": "removed_at_source",
                "authority_rule_applied": "source_parity_wins",
            }
            for article in (gone_one, gone_two)
        ]

    async def test_returns_zero_when_everything_was_seen(
        self, service: ZoteroImportService
    ) -> None:
        service._articles.get_zotero_project_articles.return_value = [
            MagicMock(id=uuid4(), zotero_item_key="A")
        ]

        removed = await service._mark_removed_items(
            project_id=uuid4(), collection_key="COLL", seen_item_keys={"A"}, sync_run_id=uuid4()
        )

        assert removed == 0
        service._articles.mark_removed_at_source.assert_not_awaited()
        service._sync_events.create_event.assert_not_awaited()
