"""The boot guard that refuses a blank or published ``ENCRYPTION_KEY`` outside local dev."""

from __future__ import annotations

from pathlib import Path

import pytest
from celery.signals import worker_init

from app.core.config import settings
from app.core.security import check_encryption_key

# The literal shipped in backend/.env.example, not the Settings default: the
# test must fail if the two drift apart.
_DEFAULT_KEY = "review_hub_default_key_change_me_in_production"


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


def test_placeholder_property_matches_the_shipped_literal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", f" {_DEFAULT_KEY} ")
    assert settings.encryption_key_is_placeholder is True

    monkeypatch.setattr(settings, "ENCRYPTION_KEY", "real-secret")
    assert settings.encryption_key_is_placeholder is False


def test_env_example_ships_the_literal_the_guard_refuses() -> None:
    env_example = Path(__file__).resolve().parents[2] / ".env.example"
    assert f'ENCRYPTION_KEY="{_DEFAULT_KEY}"' in env_example.read_text()


async def test_web_lifespan_refuses_to_boot_with_the_placeholder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Driven directly: TestClient's portal turns the SystemExit into a cancellation.

    The lifespan's logging and observability setup is process-global (structlog
    caches loggers on first use), so it is stubbed out to keep later tests'
    log capture intact. The migration check fails the test if reached: the
    SystemExit must come from the key guard, not from pending migrations.
    """
    import app.main as main
    from app.main import app, lifespan

    monkeypatch.setattr(main, "configure_observability", lambda **_: None)
    monkeypatch.setattr(main, "configure_logging", lambda: None)
    monkeypatch.setattr(main.logfire, "instrument_fastapi", lambda _app: None)
    monkeypatch.setattr(
        main, "check_pending_migrations", lambda: pytest.fail("key guard did not refuse")
    )
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", _DEFAULT_KEY)
    monkeypatch.setattr(settings, "SUPABASE_ENV", None)

    with pytest.raises(SystemExit) as exc:
        async with lifespan(app):
            pass
    assert exc.value.code == 1


def test_worker_init_refuses_to_boot_with_the_placeholder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Celery's ``Signal.send`` swallows ``Exception`` but not ``SystemExit``."""
    import app.worker.celery_app  # noqa: F401  (registers the handler)

    monkeypatch.setattr(settings, "ENCRYPTION_KEY", _DEFAULT_KEY)
    monkeypatch.setattr(settings, "SUPABASE_ENV", None)

    with pytest.raises(SystemExit) as exc:
        worker_init.send(sender=None)
    assert exc.value.code == 1
