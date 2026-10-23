"""The signed plan token ``plan_ai_run`` mints and ``start_ai_run`` verifies.

``aip1.<b64url payload>.<b64url mac>``: the payload is the compact JSON of the
plan's claims; the MAC is HMAC-SHA256 under a key derived (HKDF) from
``ENCRYPTION_KEY``, so the token carries no secret and cannot be forged or
edited. ``plan_digest`` (sha256 of the payload bytes) names the plan.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import string
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import settings

TOKEN_VERSION = "aip1"
TOKEN_TTL = timedelta(minutes=30)
_HKDF_INFO = b"prumo:mcp:ai-run-plan:v1"
_B64URL = frozenset(string.ascii_letters + string.digits + "-_")


class PlanTokenError(Exception):
    """The token is malformed, forged or edited (``invalid``), or past its TTL."""

    def __init__(self, reason: Literal["invalid", "expired"]) -> None:
        super().__init__(reason)
        self.reason = reason


def _key() -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_HKDF_INFO).derive(
        settings.ENCRYPTION_KEY.encode()
    )


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def mint(claims: dict[str, Any]) -> tuple[str, str]:
    """``(token, plan_digest)`` for ``claims`` (JSON-ready values only)."""
    payload = json.dumps({"v": TOKEN_VERSION, **claims}, separators=(",", ":")).encode()
    mac = hmac.new(_key(), payload, hashlib.sha256).digest()
    return f"{TOKEN_VERSION}.{_b64(payload)}.{_b64(mac)}", hashlib.sha256(payload).hexdigest()


def _unb64(segment: str) -> bytes:
    if not segment or not _B64URL.issuperset(segment):
        raise PlanTokenError("invalid")
    try:
        return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
    except (binascii.Error, ValueError) as exc:
        raise PlanTokenError("invalid") from exc


def verify(token: str, *, now: datetime) -> tuple[dict[str, Any], str]:
    """``(claims, plan_digest)`` of an untampered, unexpired token.

    The MAC is compared in constant time before the payload is parsed, so an
    edited token reveals nothing about the claims it would carry. The
    placeholder key never signs anything: the web service and the worker
    refuse to boot with it outside local dev (``check_encryption_key``)."""
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != TOKEN_VERSION:
        raise PlanTokenError("invalid")
    payload, mac = _unb64(parts[1]), _unb64(parts[2])
    if not hmac.compare_digest(mac, hmac.new(_key(), payload, hashlib.sha256).digest()):
        raise PlanTokenError("invalid")
    try:
        claims = json.loads(payload)
    except ValueError as exc:
        raise PlanTokenError("invalid") from exc
    if not isinstance(claims, dict) or claims.get("v") != TOKEN_VERSION:
        raise PlanTokenError("invalid")
    iat = claims.get("iat")
    if not isinstance(iat, int) or isinstance(iat, bool):
        raise PlanTokenError("invalid")
    if datetime.fromtimestamp(iat, UTC) + TOKEN_TTL <= now:
        raise PlanTokenError("expired")
    return claims, hashlib.sha256(payload).hexdigest()
