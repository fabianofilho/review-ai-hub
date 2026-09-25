"""
Tests for the project membership checks on project-scoped routes (REV-01).

Every route that receives a project_id (or a resource that belongs to a
project) must answer 403 to an authenticated user who is not a member of that
project, without calling the service layer or querying project data.
"""

import uuid
from collections.abc import AsyncGenerator
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import ensure_project_member, get_db, get_supabase
from app.core.error_handler import AuthorizationError
from app.core.security import TokenPayload, get_current_user
from app.main import app
from app.schemas.screening import ScreeningProgressStats
from app.utils.rate_limiter import limiter

USER_ID = str(uuid.uuid4())
PROJECT_ID = str(uuid.uuid4())
ARTICLE_ID = str(uuid.uuid4())
CONFLICT_ID = str(uuid.uuid4())
SUGGESTION_ID = str(uuid.uuid4())
RUN_ID = str(uuid.uuid4())
INSTRUMENT_ID = str(uuid.uuid4())
ITEM_ID = str(uuid.uuid4())
OTHER_ID = str(uuid.uuid4())

API = "/api/v1"

# Services that must never be reached by a non-member.
GUARDED_SERVICES = [
    "app.api.v1.endpoints.screening.ScreeningService",
    "app.api.v1.endpoints.screening.AIScreeningService",
    "app.api.v1.endpoints.screening.APIKeyService",
    "app.api.v1.endpoints.ai_assessment.AIAssessmentService",
    "app.api.v1.endpoints.ai_assessment.APIKeyService",
    "app.api.v1.endpoints.article_import.ArticleImportService",
    "app.api.v1.endpoints.article_import.PDFMetadataExtractionService",
    "app.api.v1.endpoints.article_import.APIKeyService",
    "app.api.v1.endpoints.model_extraction.ModelExtractionService",
    "app.api.v1.endpoints.model_extraction.APIKeyService",
    "app.api.v1.endpoints.section_extraction.SectionExtractionService",
    "app.api.v1.endpoints.section_extraction.APIKeyService",
    "app.api.v1.endpoints.project_assessment_instruments.ProjectAssessmentInstrumentService",
]

# (method, url, request kwargs) for every project-scoped route.
PROJECT_SCOPED_ROUTES = [
    # screening.py (13 routes)
    (
        "POST",
        f"{API}/screening/config",
        {"json": {"projectId": PROJECT_ID, "phase": "title_abstract"}},
    ),
    ("GET", f"{API}/screening/config/{PROJECT_ID}/title_abstract", {}),
    (
        "POST",
        f"{API}/screening/decide",
        {
            "json": {
                "projectId": PROJECT_ID,
                "articleId": ARTICLE_ID,
                "phase": "title_abstract",
                "decision": "include",
            }
        },
    ),
    ("GET", f"{API}/screening/decisions/{PROJECT_ID}/title_abstract", {}),
    ("GET", f"{API}/screening/progress/{PROJECT_ID}/title_abstract", {}),
    ("GET", f"{API}/screening/conflicts/{PROJECT_ID}/title_abstract", {}),
    ("POST", f"{API}/screening/conflicts/{CONFLICT_ID}/resolve", {"json": {"decision": "include"}}),
    (
        "POST",
        f"{API}/screening/ai",
        {"json": {"projectId": PROJECT_ID, "articleId": ARTICLE_ID, "phase": "title_abstract"}},
    ),
    (
        "POST",
        f"{API}/screening/ai/batch",
        {"json": {"projectId": PROJECT_ID, "articleIds": [ARTICLE_ID], "phase": "title_abstract"}},
    ),
    ("GET", f"{API}/screening/prisma/{PROJECT_ID}", {}),
    ("GET", f"{API}/screening/dashboard/{PROJECT_ID}/title_abstract", {}),
    (
        "POST",
        f"{API}/screening/bulk-decide",
        {
            "json": {
                "projectId": PROJECT_ID,
                "articleIds": [ARTICLE_ID],
                "phase": "title_abstract",
                "decision": "exclude",
            }
        },
    ),
    ("POST", f"{API}/screening/advance-to-fulltext", {"json": {"projectId": PROJECT_ID}}),
    # ai_assessment.py (4 routes)
    (
        "POST",
        f"{API}/ai-assessment/ai",
        {
            "json": {
                "projectId": PROJECT_ID,
                "articleId": ARTICLE_ID,
                "assessmentItemId": ITEM_ID,
                "instrumentId": INSTRUMENT_ID,
            }
        },
    ),
    (
        "POST",
        f"{API}/ai-assessment/ai/batch",
        {
            "json": {
                "projectId": PROJECT_ID,
                "articleId": ARTICLE_ID,
                "instrumentId": INSTRUMENT_ID,
                "itemIds": [ITEM_ID],
            }
        },
    ),
    (
        "GET",
        f"{API}/ai-assessment/ai/suggestions",
        {"params": {"project_id": PROJECT_ID, "article_id": ARTICLE_ID}},
    ),
    (
        "POST",
        f"{API}/ai-assessment/ai/suggestions/{SUGGESTION_ID}/review",
        {"json": {"action": "reject"}},
    ),
    # article_import.py (3 routes)
    (
        "POST",
        f"{API}/article-import/pdf-extract-metadata",
        {
            "data": {
                "project_id": PROJECT_ID,
                "storage_key": f"temp/{USER_ID}/{OTHER_ID}/1.pdf",
                "original_filename": "paper.pdf",
            }
        },
    ),
    (
        "POST",
        f"{API}/article-import/pdf-create-article",
        {
            "json": {
                "projectId": PROJECT_ID,
                "storageKey": f"temp/{USER_ID}/{OTHER_ID}/1.pdf",
                "originalFilename": "paper.pdf",
                "title": "A title",
            }
        },
    ),
    (
        "POST",
        f"{API}/article-import/csv-import",
        {
            "data": {"project_id": PROJECT_ID},
            "files": {"file": ("scopus.csv", b"Title\nA title\n", "text/csv")},
        },
    ),
    # model_extraction.py and section_extraction.py (1 route each)
    (
        "POST",
        f"{API}/extraction/models",
        {"json": {"projectId": PROJECT_ID, "articleId": ARTICLE_ID, "templateId": OTHER_ID}},
    ),
    (
        "POST",
        f"{API}/extraction/sections",
        {
            "json": {
                "projectId": PROJECT_ID,
                "articleId": ARTICLE_ID,
                "templateId": OTHER_ID,
                "entityTypeId": OTHER_ID,
            }
        },
    ),
    # project_assessment_instruments.py (9 project-scoped routes; /global lists shared instruments)
    ("GET", f"{API}/assessment-instruments/project/{PROJECT_ID}", {}),
    ("GET", f"{API}/assessment-instruments/{INSTRUMENT_ID}", {}),
    (
        "POST",
        f"{API}/assessment-instruments/clone",
        {"json": {"projectId": PROJECT_ID, "globalInstrumentId": OTHER_ID}},
    ),
    (
        "POST",
        f"{API}/assessment-instruments",
        {"json": {"projectId": PROJECT_ID, "name": "Custom", "toolType": "CUSTOM"}},
    ),
    ("PATCH", f"{API}/assessment-instruments/{INSTRUMENT_ID}", {"json": {"name": "Renamed"}}),
    ("DELETE", f"{API}/assessment-instruments/{INSTRUMENT_ID}", {}),
    (
        "POST",
        f"{API}/assessment-instruments/{INSTRUMENT_ID}/items",
        {
            "json": {
                "domain": "D1",
                "itemCode": "1.1",
                "question": "Q?",
                "allowedLevels": ["low", "high"],
            }
        },
    ),
    ("PATCH", f"{API}/assessment-instruments/items/{ITEM_ID}", {"json": {"question": "Q2?"}}),
    ("DELETE", f"{API}/assessment-instruments/items/{ITEM_ID}", {}),
]


@pytest_asyncio.fixture
async def api() -> AsyncGenerator[SimpleNamespace, None]:
    """HTTP client with a mocked DB session and an authenticated user."""
    mock_db = AsyncMock(spec=AsyncSession)
    # Resources resolved through db.get() (suggestion runs) belong to PROJECT_ID.
    mock_db.get = AsyncMock(return_value=SimpleNamespace(project_id=uuid.UUID(PROJECT_ID)))

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield mock_db

    async def override_get_current_user() -> TokenPayload:
        return TokenPayload(sub=USER_ID, email="user@example.com")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_supabase] = lambda: MagicMock()
    limiter.reset()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield SimpleNamespace(client=client, db=mock_db)

    app.dependency_overrides.clear()


@pytest.fixture
def project_resources():
    """Conflicts, suggestions, instruments and items all belong to PROJECT_ID."""
    project_uuid = uuid.UUID(PROJECT_ID)
    with (
        patch(
            "app.api.v1.endpoints.screening.ScreeningConflictRepository.get_by_id",
            AsyncMock(return_value=SimpleNamespace(project_id=project_uuid)),
        ),
        patch(
            "app.api.v1.endpoints.ai_assessment.AISuggestionRepository.get_by_id",
            AsyncMock(
                return_value=SimpleNamespace(
                    assessment_run_id=uuid.UUID(RUN_ID),
                    extraction_run_id=None,
                    screening_run_id=None,
                )
            ),
        ),
        patch(
            "app.api.v1.endpoints.project_assessment_instruments."
            "ProjectAssessmentInstrumentRepository.get_by_id",
            AsyncMock(return_value=SimpleNamespace(project_id=project_uuid)),
        ),
        patch(
            "app.api.v1.endpoints.project_assessment_instruments."
            "ProjectAssessmentItemRepository.get_by_id",
            AsyncMock(return_value=SimpleNamespace(project_instrument_id=uuid.UUID(INSTRUMENT_ID))),
        ),
    ):
        yield


@pytest.fixture
def guarded_services():
    """Replace every service reachable from the routes with a mock."""
    patchers = [patch(target) for target in GUARDED_SERVICES]
    mocks = [p.start() for p in patchers]
    yield mocks
    for p in patchers:
        p.stop()


def _membership(is_member: bool):
    return patch(
        "app.core.deps.ProjectMemberRepository.is_member",
        AsyncMock(return_value=is_member),
    )


def test_route_table_covers_all_project_scoped_routes():
    """Guard against new routes being added without a membership test."""
    expected = {
        "screening": 13,
        "ai-assessment": 4,
        "article-import": 3,
        "extraction/models": 1,
        "extraction/sections": 1,
        "assessment-instruments": 9,
    }
    counts = dict.fromkeys(expected, 0)
    for _, url, _ in PROJECT_SCOPED_ROUTES:
        for prefix in expected:
            if url.startswith(f"{API}/{prefix}"):
                counts[prefix] += 1
    assert counts == expected


@pytest.mark.asyncio
@pytest.mark.usefixtures("project_resources")
@pytest.mark.parametrize(
    ("method", "url", "kwargs"),
    PROJECT_SCOPED_ROUTES,
    ids=[f"{m} {u.removeprefix(API)}" for m, u, _ in PROJECT_SCOPED_ROUTES],
)
async def test_non_member_gets_403(api, guarded_services, method, url, kwargs):
    with _membership(False) as is_member:
        response = await api.client.request(method, url, **kwargs)

    assert response.status_code == 403, response.text
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "AUTHORIZATION_ERROR"

    is_member.assert_awaited_once()
    checked_project, checked_user = is_member.await_args.args
    assert str(checked_project) == PROJECT_ID
    assert str(checked_user) == USER_ID

    for service in guarded_services:
        service.assert_not_called()
    api.db.execute.assert_not_called()
    api.db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_member_reaches_the_service(api, guarded_services):
    screening_service = guarded_services[0]
    screening_service.return_value.get_progress = AsyncMock(
        return_value=ScreeningProgressStats(
            total_articles=3,
            screened=1,
            pending=2,
            included=1,
            excluded=0,
            maybe=0,
            conflicts=0,
        )
    )

    with _membership(True):
        response = await api.client.get(f"{API}/screening/progress/{PROJECT_ID}/title_abstract")

    assert response.status_code == 200, response.text
    assert response.json()["ok"] is True
    screening_service.return_value.get_progress.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.usefixtures("guarded_services")
async def test_suggestion_without_run_is_denied(api):
    orphan = SimpleNamespace(assessment_run_id=None, extraction_run_id=None, screening_run_id=None)
    with (
        _membership(True),
        patch(
            "app.api.v1.endpoints.ai_assessment.AISuggestionRepository.get_by_id",
            AsyncMock(return_value=orphan),
        ),
    ):
        response = await api.client.post(
            f"{API}/ai-assessment/ai/suggestions/{SUGGESTION_ID}/review",
            json={"action": "reject"},
        )

    assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.usefixtures("guarded_services")
async def test_unknown_instrument_is_404_not_403(api):
    with (
        _membership(False),
        patch(
            "app.api.v1.endpoints.project_assessment_instruments."
            "ProjectAssessmentInstrumentRepository.get_by_id",
            AsyncMock(return_value=None),
        ),
    ):
        response = await api.client.get(f"{API}/assessment-instruments/{INSTRUMENT_ID}")

    assert response.status_code == 404


class TestEnsureProjectMember:
    @pytest.mark.asyncio
    async def test_member_passes(self):
        with _membership(True) as is_member:
            await ensure_project_member(AsyncMock(), PROJECT_ID, USER_ID)
        is_member.assert_awaited_once_with(uuid.UUID(PROJECT_ID), uuid.UUID(USER_ID))

    @pytest.mark.asyncio
    async def test_non_member_raises_403(self):
        with _membership(False), pytest.raises(AuthorizationError) as exc_info:
            await ensure_project_member(AsyncMock(), PROJECT_ID, USER_ID)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("project_id", "user_id"),
        [("not-a-uuid", USER_ID), (PROJECT_ID, "test-user-id")],
    )
    async def test_invalid_ids_raise_403(self, project_id, user_id):
        with _membership(True) as is_member, pytest.raises(AuthorizationError):
            await ensure_project_member(AsyncMock(), project_id, user_id)
        is_member.assert_not_called()
