"""
Integration tests for APIKeyService with the real repository and database.

They check that API keys are stored encrypted at rest and can be read back
through the service. Rows are created inside the test transaction and rolled
back at teardown; provider validation is mocked with httpx.MockTransport.
"""

import uuid
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import patch

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.api_key_service import APIKeyService

_REAL_ASYNC_CLIENT = httpx.AsyncClient


async def _create_user(session: AsyncSession) -> uuid.UUID:
    user_id = uuid.uuid4()
    email = f"api-key-service-{user_id}@example.com"
    await session.execute(
        text("INSERT INTO auth.users (id, email) VALUES (:id, :email)"),
        {"id": user_id, "email": email},
    )
    await session.execute(
        text(
            "INSERT INTO public.profiles (id, email) VALUES (:id, :email) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": user_id, "email": email},
    )
    return user_id


@pytest_asyncio.fixture
async def service(db_session: AsyncSession) -> AsyncGenerator[APIKeyService, None]:
    try:
        user_id = await _create_user(db_session)
        yield APIKeyService(db=db_session, user_id=str(user_id))
    finally:
        await db_session.rollback()


async def _row(session: AsyncSession, key_id: str) -> dict[str, Any]:
    result = await session.execute(
        text(
            "SELECT encrypted_api_key, is_default, validation_status, last_used_at, "
            "last_validated_at FROM public.user_api_keys WHERE id = :id"
        ),
        {"id": uuid.UUID(key_id)},
    )
    return dict(result.mappings().one())


class TestAPIKeyServicePersistence:
    async def test_key_is_encrypted_at_rest_and_readable_through_service(
        self, service: APIKeyService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-global")

        saved = await service.save_key(
            provider="openai", api_key="sk-user-secret", is_default=True, validate=False
        )

        row = await _row(service.db, saved["id"])
        assert row["encrypted_api_key"] != "sk-user-secret"
        assert "sk-user-secret" not in row["encrypted_api_key"]
        assert row["validation_status"] == "pending"
        assert row["last_used_at"] is None

        assert await service.get_key_for_provider("openai") == "sk-user-secret"
        assert await service.get_decrypted_key(saved["id"]) == "sk-user-secret"
        assert (await _row(service.db, saved["id"]))["last_used_at"] is not None

    async def test_set_default_and_deactivate_change_the_selected_key(
        self, service: APIKeyService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-global")
        first = await service.save_key(
            provider="openai", api_key="sk-first", is_default=True, validate=False
        )
        second = await service.save_key(provider="openai", api_key="sk-second", validate=False)

        assert await service.get_key_for_provider("openai") == "sk-first"

        assert await service.set_default(second["id"]) is True
        assert await service.get_key_for_provider("openai") == "sk-second"
        assert (await _row(service.db, first["id"]))["is_default"] is False

        assert await service.deactivate_key(second["id"]) is True
        assert await service.get_key_for_provider("openai") == "sk-global"
        assert [str(k.id) for k in await service.list_keys()] == [first["id"]]

        assert await service.delete_key(first["id"]) is True
        remaining = await service.list_keys(active_only=False)
        assert [str(k.id) for k in remaining] == [second["id"]]
        assert await service.get_decrypted_key(first["id"]) is None

    async def test_revalidate_key_updates_stored_status(self, service: APIKeyService) -> None:
        saved = await service.save_key(provider="grok", api_key="xai-secret", validate=False)
        seen_headers: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_headers.append(request.headers["Authorization"])
            return httpx.Response(200)

        def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
            return _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(handler))

        with patch("app.services.api_key_service.httpx.AsyncClient", side_effect=factory):
            result = await service.revalidate_key(saved["id"])

        assert result["status"] == "valid"
        assert seen_headers == ["Bearer xai-secret"]
        row = await _row(service.db, saved["id"])
        assert row["validation_status"] == "valid"
        assert row["last_validated_at"] is not None
