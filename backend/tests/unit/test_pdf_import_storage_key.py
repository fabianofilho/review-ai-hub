"""
Tests for the PDF import storage key and filename checks (REV-02).

pdf-create-article moves the object named by the client with the service role
storage client. The key must be inside the caller's temporary upload area and
the original filename must not be able to change the destination path.
"""

import uuid
from collections.abc import AsyncGenerator
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_supabase
from app.core.security import TokenPayload, get_current_user
from app.main import app
from app.services.article_import_service import (
    DEFAULT_PDF_FILENAME,
    ArticleImportService,
    is_user_temp_storage_key,
    sanitize_filename,
    temp_upload_prefix,
)
from app.utils.rate_limiter import limiter

USER_ID = str(uuid.uuid4())
OTHER_USER_ID = str(uuid.uuid4())
PROJECT_ID = str(uuid.uuid4())
ARTICLE_ID = uuid.uuid4()
OWN_KEY = f"temp/{USER_ID}/{uuid.uuid4()}/1700000000000.pdf"
VICTIM_KEY = f"{uuid.uuid4()}/{uuid.uuid4()}/paper.pdf"


class TestTempStorageKey:
    def test_prefix_is_per_user(self):
        assert temp_upload_prefix(USER_ID) == f"temp/{USER_ID}/"

    def test_own_temporary_upload_is_accepted(self):
        assert is_user_temp_storage_key(OWN_KEY, USER_ID)

    @pytest.mark.parametrize(
        "key",
        [
            VICTIM_KEY,  # permanent file of some project
            f"temp/{OTHER_USER_ID}/x/1.pdf",  # another user's upload
            f"temp/{USER_ID}/",  # the prefix itself
            f"temp/{USER_ID}",
            f"temp/{USER_ID}/../{OTHER_USER_ID}/1.pdf",
            f"temp/{USER_ID}/x/../../../{VICTIM_KEY}",
            f"temp/{USER_ID}/./1.pdf",
            f"temp/{USER_ID}//1.pdf",
            f"temp/{USER_ID}/x\\..\\1.pdf",
            f"/temp/{USER_ID}/x/1.pdf",
            "",
        ],
    )
    def test_other_keys_are_rejected(self, key):
        assert not is_user_temp_storage_key(key, USER_ID)


class TestSanitizeFilename:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("paper.pdf", "paper.pdf"),
            ("../../other-project/paper.pdf", "paper.pdf"),
            ("dir/sub/paper.pdf", "paper.pdf"),
            ("C:\\Users\\me\\paper.pdf", "paper.pdf"),
            ("  spaced name.pdf  ", "spaced name.pdf"),
            ("pa\x00per\n.pdf", "paper.pdf"),
            ("", DEFAULT_PDF_FILENAME),
            (None, DEFAULT_PDF_FILENAME),
            ("..", DEFAULT_PDF_FILENAME),
            ("folder/", DEFAULT_PDF_FILENAME),
        ],
    )
    def test_sanitize(self, raw, expected):
        assert sanitize_filename(raw) == expected


class TestCreateFromPdfMetadata:
    @pytest.mark.asyncio
    async def test_move_destination_uses_sanitized_basename(self):
        storage = MagicMock()
        storage.move = AsyncMock(return_value=True)
        db = AsyncMock(spec=AsyncSession)
        service = ArticleImportService(db=db, storage=storage)
        service.article_repo.upsert_by_canonical_identity = AsyncMock(
            return_value=(SimpleNamespace(id=ARTICLE_ID, title="A title"), True)
        )
        service.file_repo.create = AsyncMock()

        await service.create_from_pdf_metadata(
            project_id=uuid.UUID(PROJECT_ID),
            metadata={"title": "A title"},
            storage_key=OWN_KEY,
            original_filename="../../victim-project/evil.pdf",
        )

        storage.move.assert_awaited_once_with(
            "articles", OWN_KEY, f"{PROJECT_ID}/{ARTICLE_ID}/evil.pdf"
        )
        article_file = service.file_repo.create.await_args.args[0]
        assert article_file.storage_key == f"{PROJECT_ID}/{ARTICLE_ID}/evil.pdf"
        assert article_file.original_filename == "evil.pdf"


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    mock_db = AsyncMock(spec=AsyncSession)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield mock_db

    async def override_get_current_user() -> TokenPayload:
        return TokenPayload(sub=USER_ID, email="user@example.com")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_supabase] = lambda: MagicMock()
    limiter.reset()

    with patch(
        "app.core.deps.ProjectMemberRepository.is_member",
        AsyncMock(return_value=True),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac

    app.dependency_overrides.clear()


def _create_body(storage_key: str) -> dict:
    return {
        "projectId": PROJECT_ID,
        "storageKey": storage_key,
        "originalFilename": "paper.pdf",
        "title": "A title",
    }


class TestPdfImportEndpoints:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("key", [VICTIM_KEY, f"temp/{OTHER_USER_ID}/x/1.pdf"])
    async def test_create_article_rejects_foreign_storage_key(self, client, key):
        with (
            patch("app.api.v1.endpoints.article_import.ArticleImportService") as service_cls,
            patch("app.api.v1.endpoints.article_import.create_storage_adapter") as storage_factory,
        ):
            response = await client.post(
                "/api/v1/article-import/pdf-create-article", json=_create_body(key)
            )

        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "AUTHORIZATION_ERROR"
        service_cls.assert_not_called()
        storage_factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_article_accepts_own_temporary_upload(self, client):
        with (
            patch("app.api.v1.endpoints.article_import.ArticleImportService") as service_cls,
            patch("app.api.v1.endpoints.article_import.create_storage_adapter"),
        ):
            service_cls.return_value.create_from_pdf_metadata = AsyncMock(
                return_value=SimpleNamespace(id=ARTICLE_ID, title="A title")
            )
            response = await client.post(
                "/api/v1/article-import/pdf-create-article", json=_create_body(OWN_KEY)
            )

        assert response.status_code == 200, response.text
        assert response.json()["ok"] is True
        kwargs = service_cls.return_value.create_from_pdf_metadata.await_args.kwargs
        assert kwargs["storage_key"] == OWN_KEY

    @pytest.mark.asyncio
    async def test_extract_metadata_rejects_foreign_storage_key(self, client):
        with (
            patch("app.api.v1.endpoints.article_import.create_storage_adapter") as storage_factory,
            patch("app.api.v1.endpoints.article_import.APIKeyService") as api_key_service,
        ):
            response = await client.post(
                "/api/v1/article-import/pdf-extract-metadata",
                data={
                    "project_id": PROJECT_ID,
                    "storage_key": VICTIM_KEY,
                    "original_filename": "paper.pdf",
                },
            )

        assert response.status_code == 403, response.text
        storage_factory.assert_not_called()
        api_key_service.assert_not_called()
