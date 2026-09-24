"""
Unit tests for app.core.security.

Covers Supabase JWT validation in both modes (local HS256 and JWKS based
RS256/ES256), the JWKS cache, the auth dependencies and the per-user
encryption key derivation. Every key is generated locally and every HTTP
call goes through httpx.MockTransport, so no test touches the network or
depends on the SUPABASE_* values of the environment.
"""

import hashlib
import time
import uuid
from collections.abc import Callable, Iterator
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi import HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from jose import JWTError, jwk, jwt
from pydantic import ValidationError

from app.core import security
from app.core.config import settings
from app.core.security import (
    SUPABASE_LOCAL_JWT_SECRET,
    JWKSCache,
    TokenPayload,
    derive_encryption_key,
    get_current_active_user,
    require_aal2,
    verify_supabase_jwt,
)

SUPABASE_URL = "https://project-ref.supabase.co"
ISSUER = f"{SUPABASE_URL}/auth/v1"
JWKS_URL = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
CUSTOM_JWT_SECRET = "custom-local-secret-with-at-least-32-characters"

_REAL_ASYNC_CLIENT = httpx.AsyncClient


# =================== HELPERS ===================


class KeyPair:
    """Locally generated asymmetric key pair exposed as PEM and JWK."""

    def __init__(self, private_pem: str, public_jwk: dict[str, Any], alg: str) -> None:
        self.private_pem = private_pem
        self.public_jwk = public_jwk
        self.alg = alg


def _make_key_pair(private_key: Any, alg: str, kid: str) -> KeyPair:
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = (
        private_key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    public_jwk = jwk.construct(public_pem, alg).to_dict()
    public_jwk["kid"] = kid
    return KeyPair(private_pem, public_jwk, alg)


@pytest.fixture(scope="module")
def rsa_keys() -> KeyPair:
    """RSA key pair used to sign RS256 tokens."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return _make_key_pair(key, "RS256", "rsa-kid-1")


@pytest.fixture(scope="module")
def other_rsa_keys() -> KeyPair:
    """Second RSA key pair, published under a different kid."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return _make_key_pair(key, "RS256", "rsa-kid-2")


@pytest.fixture(scope="module")
def ec_keys() -> KeyPair:
    """EC P-256 key pair used to sign ES256 tokens."""
    key = ec.generate_private_key(ec.SECP256R1())
    return _make_key_pair(key, "ES256", "ec-kid-1")


def _claims(**overrides: Any) -> dict[str, Any]:
    now = int(time.time())
    claims: dict[str, Any] = {
        "sub": str(uuid.uuid4()),
        "email": "reviewer@example.com",
        "role": "authenticated",
        "aal": "aal1",
        "session_id": "session-123",
        "aud": "authenticated",
        "iss": ISSUER,
        "iat": now,
        "exp": now + 3600,
        "app_metadata": {"provider": "email"},
        "user_metadata": {"full_name": "Jane Reviewer"},
    }
    claims.update(overrides)
    return {key: value for key, value in claims.items() if value is not None}


def _hs256_token(secret: str = SUPABASE_LOCAL_JWT_SECRET, **overrides: Any) -> str:
    return str(jwt.encode(_claims(**overrides), secret, algorithm="HS256"))


def _signed_token(keys: KeyPair, kid: str | None = None, **overrides: Any) -> str:
    """Sign a token with keys, using the kid of keys unless another one is given."""
    headers = {"kid": kid or keys.public_jwk["kid"]}
    token = jwt.encode(_claims(**overrides), keys.private_pem, algorithm=keys.alg, headers=headers)
    return str(token)


def _credentials(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def _auth_error_reason(exc: HTTPException) -> str:
    """Return the most specific detail of an auth error.

    verify_supabase_jwt may wrap an HTTPException raised inside its try block
    in a generic one, so the specific reason can live in __cause__.
    """
    cause = exc.__cause__
    if isinstance(cause, HTTPException):
        return str(cause.detail)
    return str(exc.detail)


def _mock_http(handler: Callable[[httpx.Request], httpx.Response]) -> Any:
    """Route every httpx.AsyncClient created by the code under test to handler."""

    def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        return _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(handler))

    return patch("app.core.security.httpx.AsyncClient", side_effect=factory)


@pytest.fixture(autouse=True)
def supabase_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Pin the Supabase settings and isolate the global JWKS cache."""
    monkeypatch.setattr(settings, "SUPABASE_URL", SUPABASE_URL)
    monkeypatch.setattr(settings, "SUPABASE_ENV", None)
    monkeypatch.setattr(settings, "SUPABASE_JWT_SECRET", None)
    monkeypatch.setattr(security, "_jwks_cache", JWKSCache())
    yield


@pytest.fixture
def local_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SUPABASE_ENV", "local")


def _patch_jwks(monkeypatch: pytest.MonkeyPatch, jwks: dict[str, Any]) -> AsyncMock:
    mock = AsyncMock(return_value=jwks)
    monkeypatch.setattr(security, "get_jwks", mock)
    return mock


# =================== TOKEN PAYLOAD ===================


class TestTokenPayload:
    def test_defaults_for_optional_claims(self) -> None:
        payload = TokenPayload(sub="user-1")

        assert payload.sub == "user-1"
        assert payload.role == "authenticated"
        assert payload.aal == "aal1"
        assert payload.email is None
        assert payload.session_id is None
        assert payload.app_metadata is None
        assert payload.exp is None

    def test_sub_is_required(self) -> None:
        with pytest.raises(ValidationError):
            TokenPayload.model_validate({"email": "no-subject@example.com"})


# =================== JWKS CACHE ===================


class TestJWKSCache:
    async def test_fetches_once_and_serves_from_cache(self) -> None:
        requests: list[httpx.Request] = []
        jwks = {"keys": [{"kid": "a"}]}

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, json=jwks)

        cache = JWKSCache(ttl_seconds=300)
        with _mock_http(handler):
            first = await cache.get_jwks(JWKS_URL)
            second = await cache.get_jwks(JWKS_URL)

        assert first == jwks
        assert second == jwks
        assert len(requests) == 1
        assert requests[0].method == "GET"
        assert str(requests[0].url) == JWKS_URL

    async def test_invalidate_forces_a_new_fetch(self) -> None:
        responses = iter([{"keys": [{"kid": "old"}]}, {"keys": [{"kid": "new"}]}])

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=next(responses))

        cache = JWKSCache()
        with _mock_http(handler):
            assert await cache.get_jwks(JWKS_URL) == {"keys": [{"kid": "old"}]}
            cache.invalidate()
            assert await cache.get_jwks(JWKS_URL) == {"keys": [{"kid": "new"}]}

    async def test_expired_entry_is_refetched(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, json={"keys": [{"kid": str(calls)}]})

        cache = JWKSCache(ttl_seconds=0)
        with _mock_http(handler):
            first = await cache.get_jwks(JWKS_URL)
            second = await cache.get_jwks(JWKS_URL)

        assert calls == 2
        assert first == {"keys": [{"kid": "1"}]}
        assert second == {"keys": [{"kid": "2"}]}

    async def test_http_error_propagates_and_is_not_cached(self) -> None:
        statuses = iter([500, 200])

        def handler(request: httpx.Request) -> httpx.Response:
            code = next(statuses)
            return httpx.Response(code, json={"keys": []} if code == 200 else {})

        cache = JWKSCache()
        with _mock_http(handler):
            with pytest.raises(httpx.HTTPStatusError):
                await cache.get_jwks(JWKS_URL)
            assert await cache.get_jwks(JWKS_URL) == {"keys": []}

    async def test_get_jwks_uses_the_supabase_well_known_url(self) -> None:
        requested: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requested.append(str(request.url))
            return httpx.Response(200, json={"keys": [{"kid": "k"}]})

        with _mock_http(handler):
            result = await security.get_jwks()

        assert result == {"keys": [{"kid": "k"}]}
        assert requested == [JWKS_URL]


# =================== ISSUER AND JWKS DECODING ===================


class TestExpectedIssuer:
    def test_appends_auth_path(self) -> None:
        assert security._expected_issuer() == ISSUER

    def test_strips_trailing_slash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "SUPABASE_URL", f"{SUPABASE_URL}/")
        assert security._expected_issuer() == ISSUER


class TestDecodeWithJWKS:
    async def test_decodes_with_matching_kid(
        self,
        monkeypatch: pytest.MonkeyPatch,
        rsa_keys: KeyPair,
        other_rsa_keys: KeyPair,
    ) -> None:
        jwks_mock = _patch_jwks(
            monkeypatch, {"keys": [other_rsa_keys.public_jwk, rsa_keys.public_jwk]}
        )
        token = _signed_token(rsa_keys, sub="user-42")

        payload = await security._decode_with_jwks(
            token=token, alg="RS256", kid="rsa-kid-1", expected_issuer=ISSUER
        )

        assert payload["sub"] == "user-42"
        assert payload["iss"] == ISSUER
        jwks_mock.assert_awaited_once_with()

    @pytest.mark.parametrize("jwks", [{"keys": []}, {}])
    async def test_rejects_when_jwks_has_no_keys(
        self, monkeypatch: pytest.MonkeyPatch, rsa_keys: KeyPair, jwks: dict[str, Any]
    ) -> None:
        _patch_jwks(monkeypatch, jwks)

        with pytest.raises(HTTPException) as exc_info:
            await security._decode_with_jwks(
                token=_signed_token(rsa_keys), alg="RS256", kid="rsa-kid-1", expected_issuer=ISSUER
            )

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc_info.value.detail == "Token signing keys not available for Supabase JWKS"
        assert exc_info.value.headers == {"WWW-Authenticate": "Bearer"}

    @pytest.mark.parametrize("kid", ["unknown-kid", None])
    async def test_rejects_unknown_or_missing_kid(
        self, monkeypatch: pytest.MonkeyPatch, rsa_keys: KeyPair, kid: str | None
    ) -> None:
        _patch_jwks(monkeypatch, {"keys": [rsa_keys.public_jwk]})

        with pytest.raises(HTTPException) as exc_info:
            await security._decode_with_jwks(
                token=_signed_token(rsa_keys), alg="RS256", kid=kid, expected_issuer=ISSUER
            )

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc_info.value.detail == "Token signing key not found"

    async def test_rejects_wrong_issuer(
        self, monkeypatch: pytest.MonkeyPatch, rsa_keys: KeyPair
    ) -> None:
        _patch_jwks(monkeypatch, {"keys": [rsa_keys.public_jwk]})
        token = _signed_token(rsa_keys, iss="https://evil.example.com/auth/v1")

        with pytest.raises(JWTError, match="issuer"):
            await security._decode_with_jwks(
                token=token, alg="RS256", kid="rsa-kid-1", expected_issuer=ISSUER
            )


# =================== VERIFY JWT: LOCAL MODE ===================


@pytest.mark.usefixtures("local_env")
class TestVerifySupabaseJWTLocal:
    async def test_accepts_hs256_signed_with_default_local_secret(self) -> None:
        user_id = str(uuid.uuid4())
        token = _hs256_token(sub=user_id, aal="aal2")

        payload = await verify_supabase_jwt(_credentials(token))

        assert isinstance(payload, TokenPayload)
        assert payload.sub == user_id
        assert payload.email == "reviewer@example.com"
        assert payload.aal == "aal2"
        assert payload.session_id == "session-123"
        assert payload.app_metadata == {"provider": "email"}
        assert payload.user_metadata == {"full_name": "Jane Reviewer"}

    async def test_uses_configured_jwt_secret(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "SUPABASE_JWT_SECRET", CUSTOM_JWT_SECRET)

        payload = await verify_supabase_jwt(
            _credentials(_hs256_token(secret=CUSTOM_JWT_SECRET, sub="custom-user"))
        )
        assert payload.sub == "custom-user"

        with pytest.raises(HTTPException) as exc_info:
            await verify_supabase_jwt(_credentials(_hs256_token(secret=SUPABASE_LOCAL_JWT_SECRET)))
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc_info.value.detail.startswith("Invalid token:")
        assert "Signature verification failed" in exc_info.value.detail

    async def test_retries_without_audience_check_in_local_mode(self) -> None:
        token = _hs256_token(aud="some-other-audience", sub="lenient-user")

        payload = await verify_supabase_jwt(_credentials(token))

        assert payload.sub == "lenient-user"

    async def test_rejects_issuer_mismatch_after_lenient_retry(self) -> None:
        token = _hs256_token(iss="https://other-project.supabase.co/auth/v1")

        with pytest.raises(HTTPException) as exc_info:
            await verify_supabase_jwt(_credentials(token))

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc_info.value.headers == {"WWW-Authenticate": "Bearer"}
        assert "issuer mismatch" in _auth_error_reason(exc_info.value)

    async def test_rejects_expired_token_even_after_retry(self) -> None:
        now = int(time.time())
        token = _hs256_token(iat=now - 7200, exp=now - 3600)

        with pytest.raises(HTTPException) as exc_info:
            await verify_supabase_jwt(_credentials(token))

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc_info.value.detail.startswith("Invalid token:")
        assert "expired" in exc_info.value.detail.lower()

    async def test_rejects_unsupported_algorithm(self) -> None:
        token = jwt.encode(_claims(), SUPABASE_LOCAL_JWT_SECRET, algorithm="HS512")

        with pytest.raises(HTTPException) as exc_info:
            await verify_supabase_jwt(_credentials(token))

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert "expected HS256/RS256/ES256" in _auth_error_reason(exc_info.value)

    async def test_accepts_rs256_via_jwks_in_local_mode(
        self, monkeypatch: pytest.MonkeyPatch, rsa_keys: KeyPair
    ) -> None:
        jwks_mock = _patch_jwks(monkeypatch, {"keys": [rsa_keys.public_jwk]})

        payload = await verify_supabase_jwt(_credentials(_signed_token(rsa_keys, sub="rs-user")))

        assert payload.sub == "rs-user"
        jwks_mock.assert_awaited_once_with()


# =================== VERIFY JWT: PRODUCTION MODE ===================


class TestVerifySupabaseJWTProduction:
    async def test_accepts_rs256_token_from_jwks(
        self, monkeypatch: pytest.MonkeyPatch, rsa_keys: KeyPair
    ) -> None:
        jwks_mock = _patch_jwks(monkeypatch, {"keys": [rsa_keys.public_jwk]})
        user_id = str(uuid.uuid4())

        payload = await verify_supabase_jwt(_credentials(_signed_token(rsa_keys, sub=user_id)))

        assert payload.sub == user_id
        assert payload.email == "reviewer@example.com"
        jwks_mock.assert_awaited_once_with()

    async def test_accepts_es256_token_from_jwks(
        self, monkeypatch: pytest.MonkeyPatch, rsa_keys: KeyPair, ec_keys: KeyPair
    ) -> None:
        _patch_jwks(monkeypatch, {"keys": [rsa_keys.public_jwk, ec_keys.public_jwk]})

        payload = await verify_supabase_jwt(_credentials(_signed_token(ec_keys, sub="ec-user")))

        assert payload.sub == "ec-user"

    async def test_any_non_local_env_uses_production_rules(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "SUPABASE_ENV", "staging")
        jwks_mock = _patch_jwks(monkeypatch, {"keys": []})

        with pytest.raises(HTTPException) as exc_info:
            await verify_supabase_jwt(_credentials(_hs256_token()))

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert "expected RS256/ES256" in _auth_error_reason(exc_info.value)
        jwks_mock.assert_not_awaited()

    async def test_rejects_hs256_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        jwks_mock = _patch_jwks(monkeypatch, {"keys": []})

        with pytest.raises(HTTPException) as exc_info:
            await verify_supabase_jwt(_credentials(_hs256_token()))

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc_info.value.headers == {"WWW-Authenticate": "Bearer"}
        assert "expected RS256/ES256" in _auth_error_reason(exc_info.value)
        jwks_mock.assert_not_awaited()

    async def test_rejects_wrong_audience(
        self, monkeypatch: pytest.MonkeyPatch, rsa_keys: KeyPair
    ) -> None:
        _patch_jwks(monkeypatch, {"keys": [rsa_keys.public_jwk]})
        token = _signed_token(rsa_keys, aud="anon")

        with pytest.raises(HTTPException) as exc_info:
            await verify_supabase_jwt(_credentials(token))

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc_info.value.detail.startswith("Invalid token:")
        assert "audience" in exc_info.value.detail.lower()
        assert isinstance(exc_info.value.__cause__, JWTError)

    async def test_rejects_token_signed_by_another_key(
        self, monkeypatch: pytest.MonkeyPatch, rsa_keys: KeyPair, other_rsa_keys: KeyPair
    ) -> None:
        _patch_jwks(monkeypatch, {"keys": [rsa_keys.public_jwk]})
        # Signed with a different private key but claiming the published kid.
        forged = _signed_token(other_rsa_keys, kid=rsa_keys.public_jwk["kid"])

        with pytest.raises(HTTPException) as exc_info:
            await verify_supabase_jwt(_credentials(forged))

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Signature verification failed" in exc_info.value.detail

    async def test_rejects_unknown_kid(
        self, monkeypatch: pytest.MonkeyPatch, rsa_keys: KeyPair, other_rsa_keys: KeyPair
    ) -> None:
        _patch_jwks(monkeypatch, {"keys": [rsa_keys.public_jwk]})

        with pytest.raises(HTTPException) as exc_info:
            await verify_supabase_jwt(_credentials(_signed_token(other_rsa_keys)))

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert _auth_error_reason(exc_info.value) == "Token signing key not found"

    @pytest.mark.parametrize("token", ["not-a-jwt", "definitely.not.a.valid.jwt.token.value"])
    async def test_rejects_malformed_token(self, token: str) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await verify_supabase_jwt(_credentials(token))

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc_info.value.detail.startswith("Invalid token:")

    async def test_jwks_fetch_failure_is_reported_as_401(self, rsa_keys: KeyPair) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        with _mock_http(handler), pytest.raises(HTTPException) as exc_info:
            await verify_supabase_jwt(_credentials(_signed_token(rsa_keys)))

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc_info.value.detail == "Token validation failed"
        assert isinstance(exc_info.value.__cause__, httpx.ConnectError)

    async def test_token_without_subject_is_rejected(
        self, monkeypatch: pytest.MonkeyPatch, rsa_keys: KeyPair
    ) -> None:
        _patch_jwks(monkeypatch, {"keys": [rsa_keys.public_jwk]})
        claims = _claims()
        del claims["sub"]
        token = jwt.encode(
            claims, rsa_keys.private_pem, algorithm="RS256", headers={"kid": "rsa-kid-1"}
        )

        with pytest.raises(HTTPException) as exc_info:
            await verify_supabase_jwt(_credentials(token))

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc_info.value.detail == "Token validation failed"
        assert isinstance(exc_info.value.__cause__, ValidationError)

    def test_get_current_user_is_an_alias(self) -> None:
        assert security.get_current_user is verify_supabase_jwt


# =================== DEPENDENCIES ===================


class TestGetCurrentActiveUser:
    async def test_returns_user_without_exp(self) -> None:
        user = TokenPayload(sub="u1")
        assert await get_current_active_user(user) is user

    async def test_returns_user_with_future_exp(self) -> None:
        # Two days of margin keeps the check independent of the host timezone.
        user = TokenPayload(sub="u1", exp=int(time.time()) + 2 * 86400)
        assert await get_current_active_user(user) is user

    async def test_rejects_expired_token(self) -> None:
        user = TokenPayload(sub="u1", exp=int(time.time()) - 2 * 86400)

        with pytest.raises(HTTPException) as exc_info:
            await get_current_active_user(user)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc_info.value.detail == "Token expired"
        assert exc_info.value.headers == {"WWW-Authenticate": "Bearer"}


class TestRequireAal2:
    def test_allows_mfa_session(self) -> None:
        user = TokenPayload(sub="u1", aal="aal2")
        assert require_aal2(user) is user

    def test_rejects_single_factor_session(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            require_aal2(TokenPayload(sub="u1", aal="aal1"))

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert exc_info.value.detail == "Multi-factor authentication required"


# =================== ENCRYPTION KEY DERIVATION ===================


class TestDeriveEncryptionKey:
    def test_matches_pbkdf2_reference(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "ENCRYPTION_KEY", "unit-test-master-key")

        expected = hashlib.pbkdf2_hmac(
            "sha256", b"unit-test-master-keyuser-1", b"review_hub_salt", 100000, dklen=32
        )

        assert derive_encryption_key("user-1") == expected

    def test_is_deterministic_and_32_bytes(self) -> None:
        first = derive_encryption_key("user-1")

        assert len(first) == 32
        assert derive_encryption_key("user-1") == first

    def test_differs_per_user(self) -> None:
        assert derive_encryption_key("user-1") != derive_encryption_key("user-2")

    def test_depends_on_master_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "ENCRYPTION_KEY", "master-key-a")
        key_a = derive_encryption_key("user-1")
        monkeypatch.setattr(settings, "ENCRYPTION_KEY", "master-key-b")
        key_b = derive_encryption_key("user-1")

        assert key_a != key_b
