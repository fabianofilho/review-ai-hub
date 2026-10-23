"""The boot guard that refuses a blank or published ``ENCRYPTION_KEY`` outside local dev."""

from __future__ import annotations

import pytest

from app.core.config import Settings, settings
from app.core.security import check_encryption_key

_DEFAULT_KEY = Settings.model_fields["ENCRYPTION_KEY"].default


@pytest.mark.parametrize(
    ("key", "env", "refused"),
    [
        (_DEFAULT_KEY, None, True),
        (_DEFAULT_KEY, "production", True),
        ("", "production", True),
        ("   ", None, True),
        (_DEFAULT_KEY, "local", False),
        ("", "local", False),
        ("real-secret", None, False),
        ("real-secret", "production", False),
    ],
    ids=[
        "placeholder-unset-env",
        "placeholder-production",
        "empty-production",
        "whitespace-unset-env",
        "placeholder-local",
        "empty-local",
        "real-key-unset-env",
        "real-key-production",
    ],
)
def test_check_encryption_key(
    monkeypatch: pytest.MonkeyPatch, key: str, env: str | None, refused: bool
) -> None:
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", key)
    monkeypatch.setattr(settings, "SUPABASE_ENV", env)

    if refused:
        with pytest.raises(SystemExit) as exc:
            check_encryption_key()
        assert exc.value.code == 1
    else:
        check_encryption_key()


def test_placeholder_property_tracks_the_field_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", f" {_DEFAULT_KEY} ")
    assert settings.encryption_key_is_placeholder is True

    monkeypatch.setattr(settings, "ENCRYPTION_KEY", "real-secret")
    assert settings.encryption_key_is_placeholder is False
