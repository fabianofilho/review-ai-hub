"""The plan token format: ``aip1.<b64url payload>.<b64url mac>``, HKDF-keyed HMAC."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.api.mcp import ai_run_plan_token
from app.api.mcp.ai_run_plan_token import PlanTokenError, mint, verify
from app.core.config import settings

_TOKEN = re.compile(r"^aip1\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")


def _b64decode(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def _claims(selection: object = "remaining") -> dict:
    return {
        "token_id": str(uuid4()),
        "user_id": str(uuid4()),
        "project_id": str(uuid4()),
        "template_id": str(uuid4()),
        "template_version_id": str(uuid4()),
        "selection": selection,
        "rerun": False,
        "will_run_digest": hashlib.sha256(b"x").hexdigest(),
        "will_run_count": 3,
        "engine": {"provider": "openai", "model": "m", "mode": "fast", "connection_id": None},
        "payer": "your_key",
        "iat": 1_760_000_000,
    }


def test_mint_shape_payload_mac_and_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", "unit-test-key")
    claims = _claims()

    token, digest = mint(claims)

    assert _TOKEN.match(token)
    _prefix, payload_b64, mac_b64 = token.split(".")
    payload = _b64decode(payload_b64)
    assert json.loads(payload) == {"v": "aip1", **claims}
    key = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=b"prumo:mcp:ai-run-plan:v1"
    ).derive(b"unit-test-key")
    assert _b64decode(mac_b64) == hmac.new(key, payload, hashlib.sha256).digest()
    assert digest == hashlib.sha256(payload).hexdigest()


def test_a_different_key_gives_a_different_mac(monkeypatch: pytest.MonkeyPatch) -> None:
    claims = _claims()
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", "key-one")
    first, _ = mint(claims)
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", "key-two")
    second, _ = mint(claims)

    assert first.split(".")[1] == second.split(".")[1]
    assert first.split(".")[2] != second.split(".")[2]


def test_one_hundred_explicit_ids_fit_the_start_argument_cap() -> None:
    ids = b"".join(uuid4().bytes for _ in range(100))
    selection = base64.urlsafe_b64encode(ids).rstrip(b"=").decode()

    token, _ = mint(_claims(selection))

    # start_ai_run caps plan_token at 4,096 chars (its Field max_length).
    assert len(token) <= 4096


def test_ttl_is_thirty_minutes() -> None:
    assert ai_run_plan_token.TOKEN_TTL.total_seconds() == 30 * 60


_NOW = datetime.fromtimestamp(1_760_000_000, UTC)


def test_verify_round_trips_claims_and_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", "unit-test-key")
    claims = _claims()
    token, digest = mint(claims)

    verified, verified_digest = verify(token, now=_NOW + timedelta(minutes=29))

    assert verified == {"v": "aip1", **claims}
    assert verified_digest == digest


def _swap_segment(token: str, index: int, value: str) -> str:
    parts = token.split(".")
    parts[index] = value
    return ".".join(parts)


def _edited_payload(token: str) -> str:
    payload = json.loads(_b64decode(token.split(".")[1]))
    payload["will_run_count"] = 99
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return _swap_segment(token, 1, base64.urlsafe_b64encode(raw).rstrip(b"=").decode())


@pytest.mark.parametrize(
    "tamper",
    [
        _edited_payload,
        lambda t: _swap_segment(t, 2, base64.urlsafe_b64encode(b"\0" * 32).rstrip(b"=").decode()),
        lambda t: _swap_segment(t, 0, "aip2"),
        lambda t: t + ".extra",
        lambda t: t.rsplit(".", 1)[0],
        lambda t: _swap_segment(t, 1, "!!!"),
        lambda _t: "",
    ],
    ids=["payload", "mac", "prefix", "extra-segment", "no-mac", "bad-base64", "empty"],
)
def test_a_tampered_token_is_invalid(monkeypatch: pytest.MonkeyPatch, tamper) -> None:
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", "unit-test-key")
    token, _ = mint(_claims())

    with pytest.raises(PlanTokenError) as raised:
        verify(tamper(token), now=_NOW)

    assert raised.value.reason == "invalid"


def test_a_token_signed_under_another_key_is_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", "key-one")
    token, _ = mint(_claims())
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", "key-two")

    with pytest.raises(PlanTokenError) as raised:
        verify(token, now=_NOW)

    assert raised.value.reason == "invalid"


def test_a_signed_payload_of_another_version_is_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", "unit-test-key")
    token, _ = mint({**_claims(), "v": "aip0"})

    with pytest.raises(PlanTokenError) as raised:
        verify(token, now=_NOW)

    assert raised.value.reason == "invalid"


def test_a_token_past_its_ttl_is_expired(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", "unit-test-key")
    token, _ = mint(_claims())

    with pytest.raises(PlanTokenError) as raised:
        verify(token, now=_NOW + timedelta(minutes=31))

    assert raised.value.reason == "expired"
