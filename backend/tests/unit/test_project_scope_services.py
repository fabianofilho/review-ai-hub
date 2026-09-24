"""
Service-level project scoping tests (REV-01).

Membership of the project is checked in the endpoints; these tests cover the
second half of the fix: ids received together with a project_id (articles,
assessment items, storage keys) must belong to that project.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.storage import StorageAdapter
from app.repositories.article_repository import ArticleRepository
from app.services.ai_assessment_service import AIAssessmentService
from app.services.ai_screening_service import AIScreeningService
from app.services.model_extraction_service import ModelExtractionService
from app.services.screening_service import ScreeningService
from app.services.section_extraction_service import SectionExtractionService

USER_ID = str(uuid.uuid4())
PROJECT_ID = uuid.uuid4()
OTHER_PROJECT_ID = uuid.uuid4()
ARTICLE_ID = uuid.uuid4()


def _db_returning_ids(ids):
    """Mock session whose execute().scalars().all() returns the given ids."""
    db = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.scalars.return_value.all.return_value = list(ids)
    db.execute = AsyncMock(return_value=result)
    return db


def _storage():
    storage = MagicMock(spec=StorageAdapter)
    storage.download = AsyncMock(return_value=b"%PDF-1.4")
    return storage


class TestArticleRepositoryEnsureInProject:
    @pytest.mark.asyncio
    async def test_passes_when_all_articles_belong_to_project(self):
        repo = ArticleRepository(_db_returning_ids([ARTICLE_ID]))
        await repo.ensure_in_project([ARTICLE_ID], PROJECT_ID)

    @pytest.mark.asyncio
    async def test_raises_when_article_is_in_another_project(self):
        repo = ArticleRepository(_db_returning_ids([]))
        with pytest.raises(ValueError, match="not found in project"):
            await repo.ensure_in_project([ARTICLE_ID], PROJECT_ID)

    @pytest.mark.asyncio
    async def test_query_is_filtered_by_project(self):
        db = _db_returning_ids([ARTICLE_ID])
        await ArticleRepository(db).ensure_in_project([str(ARTICLE_ID)], str(PROJECT_ID))
        compiled = db.execute.await_args.args[0].compile()
        assert "articles.project_id" in str(compiled)
        assert PROJECT_ID in compiled.params.values()


class TestScreeningServiceScope:
    @pytest.mark.asyncio
    async def test_decision_for_foreign_article_is_rejected_before_writing(self):
        service = ScreeningService(db=AsyncMock(spec=AsyncSession), user_id=USER_ID)
        service.article_repo.ensure_in_project = AsyncMock(side_effect=ValueError("not found"))
        service.decision_repo.create = AsyncMock()
        service.decision_repo.update = AsyncMock()

        with pytest.raises(ValueError):
            await service.create_decision(
                project_id=PROJECT_ID,
                article_id=ARTICLE_ID,
                phase="title_abstract",
                decision="include",
            )

        service.article_repo.ensure_in_project.assert_awaited_once_with([ARTICLE_ID], PROJECT_ID)
        service.decision_repo.create.assert_not_called()
        service.decision_repo.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_advance_to_fulltext_only_loads_articles_of_the_project(self):
        own = SimpleNamespace(screening_phase="title_abstract")
        service = ScreeningService(db=AsyncMock(spec=AsyncSession), user_id=USER_ID)
        service.article_repo.get_by_ids = AsyncMock(return_value=[own])

        count = await service.advance_to_fulltext(PROJECT_ID, [ARTICLE_ID, uuid.uuid4()])

        assert count == 1
        assert own.screening_phase == "full_text"
        assert service.article_repo.get_by_ids.await_args.args[1] == PROJECT_ID


class TestAIScreeningServiceScope:
    @pytest.mark.asyncio
    async def test_article_of_another_project_is_not_screened(self):
        db = AsyncMock(spec=AsyncSession)
        db.get = AsyncMock(return_value=SimpleNamespace(id=ARTICLE_ID, project_id=OTHER_PROJECT_ID))
        with patch("app.services.ai_screening_service.OpenAIService"):
            service = AIScreeningService(db=db, user_id=USER_ID, storage=_storage())
        service.config_repo.get_by_project_and_phase = AsyncMock(
            return_value=SimpleNamespace(criteria=[])
        )
        service._screen_title_abstract = AsyncMock()

        with pytest.raises(ValueError, match="not found"):
            await service.screen_article(PROJECT_ID, ARTICLE_ID, "title_abstract")

        service._screen_title_abstract.assert_not_called()


@pytest.fixture
def assessment_service():
    service = AIAssessmentService(
        db=AsyncMock(spec=AsyncSession),
        user_id=USER_ID,
        storage=_storage(),
        trace_id="trace",
        openai_api_key="test-key",
    )
    service._runs = MagicMock()
    service._runs.create_run = AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))
    service._runs.start_run = AsyncMock()
    service._runs.fail_run = AsyncMock()
    service._project_assessment_items = MagicMock()
    service._project_assessment_items.get_by_id = AsyncMock(return_value=None)
    service._assessment_items = MagicMock()
    service._assessment_items.get_by_id = AsyncMock(
        return_value=SimpleNamespace(id=uuid.uuid4(), allowed_levels=["low", "high"])
    )
    service._project_instruments = MagicMock()
    service._articles = MagicMock()
    service._articles.get_by_id = AsyncMock(
        return_value=SimpleNamespace(id=ARTICLE_ID, project_id=PROJECT_ID)
    )
    service._article_files = MagicMock()
    service._projects = MagicMock()
    service._projects.get_summary = AsyncMock(return_value={})
    service._prepare_pdf_file = AsyncMock(side_effect=AssertionError("PDF must not be read"))
    return service


class TestAIAssessmentServiceScope:
    @pytest.mark.asyncio
    async def test_article_of_another_project_fails_the_run(self, assessment_service):
        assessment_service._articles.get_by_id = AsyncMock(
            return_value=SimpleNamespace(id=ARTICLE_ID, project_id=OTHER_PROJECT_ID)
        )

        with pytest.raises(ValueError, match="Article not found"):
            await assessment_service.assess(
                project_id=PROJECT_ID,
                article_id=ARTICLE_ID,
                assessment_item_id=uuid.uuid4(),
                instrument_id=uuid.uuid4(),
            )

        assessment_service._runs.fail_run.assert_awaited_once()
        assessment_service._prepare_pdf_file.assert_not_called()

    @pytest.mark.asyncio
    async def test_foreign_storage_key_is_rejected(self, assessment_service):
        assessment_service._article_files.get_by_article = AsyncMock(
            return_value=[
                SimpleNamespace(
                    storage_key=f"{PROJECT_ID}/{ARTICLE_ID}/paper.pdf", project_id=PROJECT_ID
                )
            ]
        )

        with pytest.raises(ValueError, match="pdf_storage_key"):
            await assessment_service.assess(
                project_id=PROJECT_ID,
                article_id=ARTICLE_ID,
                assessment_item_id=uuid.uuid4(),
                instrument_id=uuid.uuid4(),
                pdf_storage_key=f"{OTHER_PROJECT_ID}/{uuid.uuid4()}/secret.pdf",
            )

        assessment_service._prepare_pdf_file.assert_not_called()

    @pytest.mark.asyncio
    async def test_storage_key_of_the_article_is_accepted(self, assessment_service):
        key = f"{PROJECT_ID}/{ARTICLE_ID}/paper.pdf"
        assessment_service._article_files.get_by_article = AsyncMock(
            return_value=[SimpleNamespace(storage_key=key, project_id=PROJECT_ID)]
        )
        await assessment_service._ensure_article_file_key(key, ARTICLE_ID, PROJECT_ID)

    @pytest.mark.asyncio
    async def test_project_item_of_another_project_is_not_found(self, assessment_service):
        foreign_item = SimpleNamespace(id=uuid.uuid4(), project_instrument_id=uuid.uuid4())
        assessment_service._project_assessment_items.get_by_id = AsyncMock(
            return_value=foreign_item
        )
        assessment_service._project_instruments.get_by_id = AsyncMock(
            return_value=SimpleNamespace(project_id=OTHER_PROJECT_ID)
        )

        with pytest.raises(ValueError, match="Assessment item not found"):
            await assessment_service.assess(
                project_id=PROJECT_ID,
                article_id=ARTICLE_ID,
                assessment_item_id=foreign_item.id,
                instrument_id=uuid.uuid4(),
            )

        assessment_service._assessment_items.get_by_id.assert_not_called()
        assessment_service._prepare_pdf_file.assert_not_called()

    @pytest.mark.asyncio
    async def test_batch_rejects_article_of_another_project(self, assessment_service):
        assessment_service._articles.get_by_id = AsyncMock(
            return_value=SimpleNamespace(id=ARTICLE_ID, project_id=OTHER_PROJECT_ID)
        )
        assessment_service._article_files.get_latest_pdf = AsyncMock()

        with pytest.raises(ValueError, match="not found"):
            await assessment_service.assess_batch(
                project_id=PROJECT_ID,
                article_id=ARTICLE_ID,
                item_ids=[uuid.uuid4()],
                instrument_id=uuid.uuid4(),
            )

        assessment_service._article_files.get_latest_pdf.assert_not_called()
        assessment_service.storage.download.assert_not_called()


class TestExtractionServicesScope:
    @pytest.mark.asyncio
    async def test_model_extraction_checks_article_before_creating_run(self):
        with (
            patch("app.services.model_extraction_service.OpenAIService"),
            patch("app.services.model_extraction_service.PDFProcessor"),
        ):
            service = ModelExtractionService(
                db=AsyncMock(spec=AsyncSession),
                user_id=USER_ID,
                storage=_storage(),
                trace_id="trace",
            )
        service._articles = MagicMock()
        service._articles.ensure_in_project = AsyncMock(side_effect=ValueError("not found"))
        service._runs = MagicMock()
        service._runs.create_run = AsyncMock()

        with pytest.raises(ValueError):
            await service.extract(PROJECT_ID, ARTICLE_ID, uuid.uuid4())

        service._articles.ensure_in_project.assert_awaited_once_with([ARTICLE_ID], PROJECT_ID)
        service._runs.create_run.assert_not_called()
        service.storage.download.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method", ["extract_section", "extract_all_sections"])
    async def test_section_extraction_checks_article_before_creating_run(self, method):
        with (
            patch("app.services.section_extraction_service.OpenAIService"),
            patch("app.services.section_extraction_service.PDFProcessor"),
        ):
            service = SectionExtractionService(
                db=AsyncMock(spec=AsyncSession),
                user_id=USER_ID,
                storage=_storage(),
                trace_id="trace",
            )
        service._articles = MagicMock()
        service._articles.ensure_in_project = AsyncMock(side_effect=ValueError("not found"))
        service._runs = MagicMock()
        service._runs.create_run = AsyncMock()

        with pytest.raises(ValueError):
            await getattr(service, method)(PROJECT_ID, ARTICLE_ID, uuid.uuid4(), uuid.uuid4())

        service._articles.ensure_in_project.assert_awaited_once_with([ARTICLE_ID], PROJECT_ID)
        service._runs.create_run.assert_not_called()
        service.storage.download.assert_not_called()
