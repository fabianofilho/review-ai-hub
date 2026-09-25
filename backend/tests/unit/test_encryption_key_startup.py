"""
Tests for the ENCRYPTION_KEY startup guard (REV-16).

Outside DEBUG the API must refuse to start with an empty or publicly known
ENCRYPTION_KEY, because every stored API key would be decryptable by anyone
who reads the repository.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.core.config import (
    KNOWN_INSECURE_ENCRYPTION_KEYS,
    Settings,
    validate_encryption_key,
)
from app.main import app, lifespan

SECURE_KEY = "a-unique-secret-generated-for-this-deployment-0123456789"


def _settings(**overrides) -> Settings:
    return Settings(**overrides)


def test_code_default_is_listed_as_insecure():
    default_key = Settings.model_fields["ENCRYPTION_KEY"].default
    assert default_key in KNOWN_INSECURE_ENCRYPTION_KEYS


@pytest.mark.parametrize("key", sorted(KNOWN_INSECURE_ENCRYPTION_KEYS) + ["", "   "])
def test_insecure_key_is_rejected_without_debug(key):
    with pytest.raises(RuntimeError, match="ENCRYPTION_KEY"):
        validate_encryption_key(_settings(DEBUG=False, ENCRYPTION_KEY=key))


@pytest.mark.parametrize("key", sorted(KNOWN_INSECURE_ENCRYPTION_KEYS))
def test_insecure_key_is_allowed_in_debug(key):
    validate_encryption_key(_settings(DEBUG=True, ENCRYPTION_KEY=key))


def test_unique_key_is_accepted_without_debug():
    validate_encryption_key(_settings(DEBUG=False, ENCRYPTION_KEY=SECURE_KEY))


@pytest.mark.asyncio
async def test_lifespan_aborts_before_migrations_with_insecure_key():
    insecure = _settings(
        DEBUG=False,
        ENCRYPTION_KEY="review_hub_default_key_change_me_in_production",
    )
    migrations_check = MagicMock()
    with (
        patch("app.main.settings", insecure),
        patch("app.main.check_pending_migrations", migrations_check),
        pytest.raises(SystemExit) as exc_info,
    ):
        async with lifespan(app):
            pass

    assert exc_info.value.code == 1
    migrations_check.assert_not_called()
