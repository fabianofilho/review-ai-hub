"""
Unit tests for APIKeyService.

The repository is replaced by an AsyncMock and every provider validation call
goes through httpx.MockTransport, so the tests never reach the network and do
not depend on the API keys configured in the environment.
"""

import uuid
from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from cryptography.fernet import InvalidToken
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user_api_key import UserAPIKey
from app.repositories.user_api_key_repository import UserAPIKeyRepository
from app.services.api_key_service import APIKeyService

_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _mock_http(handler: Callable[[httpx.Request], httpx.Response]) -> Any:
    """Route every httpx.AsyncClient created by the service to handler."""

    def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        return _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(handler))

    return patch("app.services.api_key_service.httpx.AsyncClient", side_effect=factory)


def _recording_handler(
    response: httpx.Response, requests: list[httpx.Request]
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return response

    return handler


@pytest.fixture
def user_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def repo() -> AsyncMock:
    return AsyncMock(spec=UserAPIKeyRepository)


@pytest.fixture
def service(user_id: uuid.UUID, repo: AsyncMock) -> APIKeyService:
    svc = APIKeyService(db=AsyncMock(spec=AsyncSession), user_id=user_id)
    svc._repo = repo
    return svc


def _stored_key(
    service: APIKeyService,
    plaintext: str = "sk-user-key",
    provider: str = "openai",
    **overrides: Any,
) -> UserAPIKey:
    key = UserAPIKey(
        id=uuid.uuid4(),
        user_id=service.user_id,
        provider=provider,
        encrypted_api_key=service._encrypt(plaintext),
        is_active=True,
        is_default=True,
        validation_status="pending",
    )
    for name, value in overrides.items():
        setattr(key, name, value)
    return key


# =================== CONSTRUCTION ===================


class TestInit:
    def test_accepts_uuid_instance(self, user_id: uuid.UUID) -> None:
        svc = APIKeyService(db=AsyncMock(), user_id=user_id)
        assert svc.user_id == user_id

    def test_parses_uuid_string(self, user_id: uuid.UUID) -> None:
        svc = APIKeyService(db=AsyncMock(), user_id=str(user_id))
        assert svc.user_id == user_id

    def test_invalid_user_id_raises_on_access(self) -> None:
        svc = APIKeyService(db=AsyncMock(), user_id="test-user-id")

        with pytest.raises(ValueError, match="test-user-id"):
            _ = svc.user_id

    def test_builds_repository_with_the_session(self) -> None:
        db = AsyncMock(spec=AsyncSession)
        svc = APIKeyService(db=db, user_id=uuid.uuid4())

        assert isinstance(svc._repo, UserAPIKeyRepository)
        assert svc._repo.db is db


# =================== ENCRYPTION ===================


class TestEncryption:
    def test_roundtrip(self, service: APIKeyService) -> None:
        encrypted = service._encrypt("sk-secret-value")

        assert encrypted != "sk-secret-value"
        assert "sk-secret-value" not in encrypted
        assert service._decrypt(encrypted) == "sk-secret-value"

    def test_fernet_is_cached(self, service: APIKeyService) -> None:
        assert service.fernet is service.fernet

    def test_same_user_in_another_instance_can_decrypt(self, user_id: uuid.UUID) -> None:
        first = APIKeyService(db=AsyncMock(), user_id=user_id)
        second = APIKeyService(db=AsyncMock(), user_id=user_id)

        assert second._decrypt(first._encrypt("sk-shared")) == "sk-shared"

    def test_other_user_cannot_decrypt(self, service: APIKeyService) -> None:
        other = APIKeyService(db=AsyncMock(), user_id=uuid.uuid4())

        with pytest.raises(InvalidToken):
            other._decrypt(service._encrypt("sk-private"))


# =================== LIST / SAVE ===================


class TestListKeys:
    @pytest.mark.parametrize("active_only", [True, False])
    async def test_delegates_to_repository(
        self, service: APIKeyService, repo: AsyncMock, user_id: uuid.UUID, active_only: bool
    ) -> None:
        keys = [MagicMock(spec=UserAPIKey)]
        repo.list_by_user.return_value = keys

        result = await service.list_keys(active_only=active_only)

        assert result is keys
        repo.list_by_user.assert_awaited_once_with(user_id, active_only=active_only)


class TestSaveKey:
    async def test_rejects_unsupported_provider(
        self, service: APIKeyService, repo: AsyncMock
    ) -> None:
        with pytest.raises(ValueError, match="mistral"):
            await service.save_key(provider="mistral", api_key="k", validate=False)

        repo.create_key.assert_not_awaited()

    async def test_saves_encrypted_key_without_validation(
        self, service: APIKeyService, repo: AsyncMock, user_id: uuid.UUID
    ) -> None:
        created = _stored_key(service, is_default=True)
        repo.create_key.return_value = created
        validate = AsyncMock()

        with patch.object(service, "_validate_key", validate):
            result = await service.save_key(
                provider="anthropic",
                api_key="sk-ant-plain",
                key_name="Work",
                is_default=True,
                key_metadata={"model": "claude"},
                validate=False,
            )

        validate.assert_not_awaited()
        repo.create_key.assert_awaited_once()
        kwargs = repo.create_key.await_args.kwargs
        assert kwargs["user_id"] == user_id
        assert kwargs["provider"] == "anthropic"
        assert kwargs["key_name"] == "Work"
        assert kwargs["is_default"] is True
        assert kwargs["metadata"] == {"model": "claude"}
        assert kwargs["encrypted_api_key"] != "sk-ant-plain"
        assert service._decrypt(kwargs["encrypted_api_key"]) == "sk-ant-plain"
        repo.set_validation_status.assert_not_awaited()
        assert result == {
            "id": str(created.id),
            "provider": "anthropic",
            "validation_status": "pending",
            "validation_message": None,
            "is_default": True,
        }

    @pytest.mark.parametrize(
        ("status", "message"),
        [("valid", "API key válida"), ("invalid", "API key inválida ou expirada")],
    )
    async def test_validates_and_records_status(
        self, service: APIKeyService, repo: AsyncMock, status: str, message: str
    ) -> None:
        created = _stored_key(service, is_default=False)
        repo.create_key.return_value = created
        validate = AsyncMock(return_value={"status": status, "message": message})

        with patch.object(service, "_validate_key", validate):
            result = await service.save_key(provider="openai", api_key="sk-live")

        validate.assert_awaited_once_with("openai", "sk-live")
        repo.set_validation_status.assert_awaited_once_with(created.id, status)
        assert result["validation_status"] == status
        assert result["validation_message"] == message
        assert result["is_default"] is False

    async def test_pending_validation_does_not_update_status(
        self, service: APIKeyService, repo: AsyncMock
    ) -> None:
        repo.create_key.return_value = _stored_key(service)
        validate = AsyncMock(return_value={"status": "pending", "message": "Erro na validação"})

        with patch.object(service, "_validate_key", validate):
            result = await service.save_key(provider="gemini", api_key="g-key")

        repo.set_validation_status.assert_not_awaited()
        assert result["validation_status"] == "pending"
        assert result["validation_message"] == "Erro na validação"


# =================== READ KEYS ===================


class TestGetKeyForProvider:
    async def test_returns_decrypted_user_default_and_marks_usage(
        self, service: APIKeyService, repo: AsyncMock, user_id: uuid.UUID
    ) -> None:
        stored = _stored_key(service, plaintext="sk-user-default")
        repo.get_default.return_value = stored

        result = await service.get_key_for_provider("openai")

        assert result == "sk-user-default"
        repo.get_default.assert_awaited_once_with(user_id, "openai")
        repo.update_last_used.assert_awaited_once_with(stored.id)

    async def test_falls_back_to_global_openai_key(
        self, service: APIKeyService, repo: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-global")
        repo.get_default.return_value = None

        assert await service.get_key_for_provider("openai") == "sk-global"
        repo.update_last_used.assert_not_awaited()

    async def test_no_global_key_for_other_providers(
        self, service: APIKeyService, repo: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-global")
        repo.get_default.return_value = None

        assert await service.get_key_for_provider("anthropic") is None

    async def test_falls_back_when_stored_key_is_empty(
        self, service: APIKeyService, repo: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-global")
        repo.get_default.return_value = _stored_key(service, encrypted_api_key="")

        assert await service.get_key_for_provider("openai") == "sk-global"
        repo.update_last_used.assert_not_awaited()

    async def test_without_fallback_returns_none(
        self, service: APIKeyService, repo: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-global")
        repo.get_default.return_value = None

        assert await service.get_key_for_provider("openai", use_fallback=False) is None

    async def test_invalid_user_id_skips_repository(
        self, repo: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-global")
        svc = APIKeyService(db=AsyncMock(), user_id="test-user-id")
        svc._repo = repo

        assert await svc.get_key_for_provider("openai") == "sk-global"
        repo.get_default.assert_not_awaited()


class TestGetDecryptedKey:
    async def test_returns_plaintext_for_owned_key(
        self, service: APIKeyService, repo: AsyncMock, user_id: uuid.UUID
    ) -> None:
        stored = _stored_key(service, plaintext="sk-by-id")
        repo.get_by_id_and_user.return_value = stored

        assert await service.get_decrypted_key(stored.id) == "sk-by-id"
        repo.get_by_id_and_user.assert_awaited_once_with(stored.id, user_id)

    async def test_returns_none_when_missing(self, service: APIKeyService, repo: AsyncMock) -> None:
        repo.get_by_id_and_user.return_value = None

        assert await service.get_decrypted_key(str(uuid.uuid4())) is None


# =================== MUTATIONS ===================


class TestMutations:
    @pytest.mark.parametrize("success", [True, False])
    async def test_set_default(
        self, service: APIKeyService, repo: AsyncMock, user_id: uuid.UUID, success: bool
    ) -> None:
        key_id = uuid.uuid4()
        repo.set_default.return_value = success

        assert await service.set_default(key_id) is success
        repo.set_default.assert_awaited_once_with(key_id, user_id)

    @pytest.mark.parametrize("success", [True, False])
    async def test_deactivate_key(
        self, service: APIKeyService, repo: AsyncMock, user_id: uuid.UUID, success: bool
    ) -> None:
        key_id = str(uuid.uuid4())
        repo.deactivate.return_value = success

        assert await service.deactivate_key(key_id) is success
        repo.deactivate.assert_awaited_once_with(key_id, user_id)

    @pytest.mark.parametrize("success", [True, False])
    async def test_delete_key(
        self, service: APIKeyService, repo: AsyncMock, user_id: uuid.UUID, success: bool
    ) -> None:
        key_id = uuid.uuid4()
        repo.hard_delete.return_value = success

        assert await service.delete_key(key_id) is success
        repo.hard_delete.assert_awaited_once_with(key_id, user_id)


class TestRevalidateKey:
    async def test_revalidates_and_stores_new_status(
        self, service: APIKeyService, repo: AsyncMock, user_id: uuid.UUID
    ) -> None:
        stored = _stored_key(service, plaintext="sk-grok-key", provider="grok")
        repo.get_by_id_and_user.return_value = stored
        validate = AsyncMock(return_value={"status": "invalid", "message": "API key inválida"})

        with patch.object(service, "_validate_key", validate):
            result = await service.revalidate_key(str(stored.id))

        assert result == {"status": "invalid", "message": "API key inválida"}
        repo.get_by_id_and_user.assert_awaited_once_with(stored.id, user_id)
        validate.assert_awaited_once_with("grok", "sk-grok-key")
        repo.set_validation_status.assert_awaited_once_with(stored.id, "invalid")

    async def test_missing_key_raises(self, service: APIKeyService, repo: AsyncMock) -> None:
        repo.get_by_id_and_user.return_value = None

        with pytest.raises(ValueError, match="não encontrada"):
            await service.revalidate_key(uuid.uuid4())

        repo.set_validation_status.assert_not_awaited()


# =================== VALIDATION DISPATCH ===================


class TestValidateKeyDispatch:
    @pytest.mark.parametrize(
        ("provider", "validator"),
        [
            ("openai", "_validate_openai"),
            ("anthropic", "_validate_anthropic"),
            ("gemini", "_validate_gemini"),
            ("grok", "_validate_grok"),
        ],
    )
    async def test_routes_to_provider_validator(
        self, service: APIKeyService, provider: str, validator: str
    ) -> None:
        expected = {"status": "valid", "message": provider}
        mock = AsyncMock(return_value=expected)

        with patch.object(service, validator, mock):
            assert await service._validate_key(provider, "the-key") == expected

        mock.assert_awaited_once_with("the-key")

    async def test_unknown_provider_is_pending(self, service: APIKeyService) -> None:
        result = await service._validate_key("mistral", "k")

        assert result["status"] == "pending"

    async def test_validator_error_is_pending(self, service: APIKeyService) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("timed out", request=request)

        with _mock_http(handler):
            result = await service._validate_key("openai", "sk-timeout")

        assert result["status"] == "pending"
        assert "timed out" in result["message"]


# =================== PROVIDER VALIDATORS ===================


class TestValidateOpenAI:
    @pytest.mark.parametrize(
        ("status_code", "expected_status"),
        [(200, "valid"), (401, "invalid"), (429, "valid"), (500, "invalid")],
    )
    async def test_maps_status_codes(
        self, service: APIKeyService, status_code: int, expected_status: str
    ) -> None:
        requests: list[httpx.Request] = []

        with _mock_http(_recording_handler(httpx.Response(status_code), requests)):
            result = await service._validate_openai("sk-openai")

        assert result["status"] == expected_status
        assert len(requests) == 1
        assert requests[0].method == "GET"
        assert str(requests[0].url) == "https://api.openai.com/v1/models"
        assert requests[0].headers["Authorization"] == "Bearer sk-openai"

    async def test_unexpected_status_is_reported(self, service: APIKeyService) -> None:
        with _mock_http(_recording_handler(httpx.Response(503), [])):
            result = await service._validate_openai("sk-openai")

        assert result == {"status": "invalid", "message": "Erro: 503"}


class TestValidateAnthropic:
    @pytest.mark.parametrize(
        ("status_code", "expected_status"),
        [(200, "valid"), (401, "invalid"), (403, "invalid"), (429, "valid")],
    )
    async def test_maps_status_codes(
        self, service: APIKeyService, status_code: int, expected_status: str
    ) -> None:
        requests: list[httpx.Request] = []

        with _mock_http(_recording_handler(httpx.Response(status_code), requests)):
            result = await service._validate_anthropic("sk-ant")

        assert result["status"] == expected_status
        request = requests[0]
        assert request.method == "POST"
        assert str(request.url) == "https://api.anthropic.com/v1/messages"
        assert request.headers["x-api-key"] == "sk-ant"
        assert request.headers["anthropic-version"] == "2023-06-01"
        body = httpx.Response(200, content=request.content).json()
        assert body["max_tokens"] == 1
        assert body["messages"] == [{"role": "user", "content": "hi"}]

    async def test_authentication_error_body_is_invalid(self, service: APIKeyService) -> None:
        response = httpx.Response(
            400, json={"type": "error", "error": {"type": "authentication_error"}}
        )

        with _mock_http(_recording_handler(response, [])):
            result = await service._validate_anthropic("sk-ant")

        assert result == {"status": "invalid", "message": "API key inválida"}

    async def test_other_error_body_is_probably_valid(self, service: APIKeyService) -> None:
        response = httpx.Response(529, json={"type": "error", "error": {"type": "overloaded"}})

        with _mock_http(_recording_handler(response, [])):
            result = await service._validate_anthropic("sk-ant")

        assert result == {"status": "valid", "message": "API key provavelmente válida"}

    async def test_empty_error_body_is_probably_valid(self, service: APIKeyService) -> None:
        with _mock_http(_recording_handler(httpx.Response(500), [])):
            result = await service._validate_anthropic("sk-ant")

        assert result["status"] == "valid"


class TestValidateGemini:
    @pytest.mark.parametrize(
        ("status_code", "expected_status"),
        [(200, "valid"), (400, "invalid"), (401, "invalid"), (403, "invalid"), (429, "valid")],
    )
    async def test_maps_status_codes(
        self, service: APIKeyService, status_code: int, expected_status: str
    ) -> None:
        requests: list[httpx.Request] = []

        with _mock_http(_recording_handler(httpx.Response(status_code), requests)):
            result = await service._validate_gemini("g-key")

        assert result["status"] == expected_status
        url = requests[0].url
        assert requests[0].method == "GET"
        assert url.host == "generativelanguage.googleapis.com"
        assert url.path == "/v1/models"
        assert url.params["key"] == "g-key"

    async def test_unexpected_status_is_reported(self, service: APIKeyService) -> None:
        with _mock_http(_recording_handler(httpx.Response(500), [])):
            result = await service._validate_gemini("g-key")

        assert result == {"status": "invalid", "message": "Erro: 500"}


class TestValidateGrok:
    @pytest.mark.parametrize(
        ("status_code", "expected_status"),
        [(200, "valid"), (401, "invalid"), (429, "valid"), (502, "invalid")],
    )
    async def test_maps_status_codes(
        self, service: APIKeyService, status_code: int, expected_status: str
    ) -> None:
        requests: list[httpx.Request] = []

        with _mock_http(_recording_handler(httpx.Response(status_code), requests)):
            result = await service._validate_grok("xai-key")

        assert result["status"] == expected_status
        assert str(requests[0].url) == "https://api.x.ai/v1/models"
        assert requests[0].headers["Authorization"] == "Bearer xai-key"

    async def test_unexpected_status_is_reported(self, service: APIKeyService) -> None:
        with _mock_http(_recording_handler(httpx.Response(502), [])):
            result = await service._validate_grok("xai-key")

        assert result == {"status": "invalid", "message": "Erro: 502"}


class TestSaveKeyEndToEndValidation:
    async def test_save_key_validates_against_mocked_provider(
        self, service: APIKeyService, repo: AsyncMock
    ) -> None:
        created = _stored_key(service)
        repo.create_key.return_value = created
        requests: list[httpx.Request] = []

        with _mock_http(_recording_handler(httpx.Response(401), requests)):
            result = await service.save_key(provider="openai", api_key="sk-revoked")

        assert requests[0].headers["Authorization"] == "Bearer sk-revoked"
        assert result["validation_status"] == "invalid"
        repo.set_validation_status.assert_awaited_once_with(created.id, "invalid")
