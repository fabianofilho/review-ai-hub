"""
Integration tests for UserAPIKeyRepository against the real database.

Each test creates its own users (auth.users + public.profiles) and keys inside
the test transaction and rolls everything back at teardown, so the tests are
independent from each other and leave no rows behind.
"""

import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_api_key import UserAPIKey
from app.repositories.user_api_key_repository import UserAPIKeyRepository


@dataclass
class RepoContext:
    session: AsyncSession
    repo: UserAPIKeyRepository
    user_id: uuid.UUID
    other_user_id: uuid.UUID


async def _create_user(session: AsyncSession) -> uuid.UUID:
    user_id = uuid.uuid4()
    email = f"api-key-repo-{user_id}@example.com"
    await session.execute(
        text("INSERT INTO auth.users (id, email) VALUES (:id, :email)"),
        {"id": user_id, "email": email},
    )
    # The on_auth_user_created trigger normally creates the profile; keep the
    # fixture independent from it.
    await session.execute(
        text(
            "INSERT INTO public.profiles (id, email) VALUES (:id, :email) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": user_id, "email": email},
    )
    return user_id


@pytest_asyncio.fixture
async def ctx(db_session: AsyncSession) -> AsyncGenerator[RepoContext, None]:
    try:
        user_id = await _create_user(db_session)
        other_user_id = await _create_user(db_session)
        yield RepoContext(
            session=db_session,
            repo=UserAPIKeyRepository(db_session),
            user_id=user_id,
            other_user_id=other_user_id,
        )
    finally:
        await db_session.rollback()


async def _row(session: AsyncSession, key_id: uuid.UUID) -> dict[str, Any] | None:
    result = await session.execute(
        text(
            "SELECT user_id, provider, encrypted_api_key, key_name, is_active, is_default, "
            "validation_status, last_used_at, last_validated_at, metadata "
            "FROM public.user_api_keys WHERE id = :id"
        ),
        {"id": key_id},
    )
    row = result.mappings().one_or_none()
    return dict(row) if row is not None else None


async def _set_created_at(session: AsyncSession, key_id: uuid.UUID, value: datetime) -> None:
    await session.execute(
        text("UPDATE public.user_api_keys SET created_at = :value WHERE id = :id"),
        {"value": value, "id": key_id},
    )


async def _new_key(
    ctx: RepoContext,
    provider: str = "openai",
    *,
    user_id: uuid.UUID | None = None,
    is_default: bool = False,
    key_name: str | None = None,
) -> UserAPIKey:
    return await ctx.repo.create_key(
        user_id=user_id or ctx.user_id,
        provider=provider,
        encrypted_api_key=f"ciphertext-{uuid.uuid4()}",
        key_name=key_name,
        is_default=is_default,
    )


# =================== CREATE ===================


class TestCreateKey:
    async def test_persists_key_with_defaults(self, ctx: RepoContext) -> None:
        key = await ctx.repo.create_key(
            user_id=str(ctx.user_id),
            provider="anthropic",
            encrypted_api_key="gAAAAB-ciphertext",
            key_name="Personal",
        )

        assert isinstance(key.id, uuid.UUID)
        assert key.user_id == ctx.user_id
        assert key.is_active is True
        assert key.is_default is False
        assert key.validation_status == "pending"
        assert key.key_metadata == {}
        assert key.created_at is not None

        row = await _row(ctx.session, key.id)
        assert row is not None
        assert row["user_id"] == ctx.user_id
        assert row["provider"] == "anthropic"
        assert row["encrypted_api_key"] == "gAAAAB-ciphertext"
        assert row["key_name"] == "Personal"
        assert row["metadata"] == {}

    async def test_stores_metadata_and_default_flag(self, ctx: RepoContext) -> None:
        key = await ctx.repo.create_key(
            user_id=ctx.user_id,
            provider="gemini",
            encrypted_api_key="ciphertext",
            is_default=True,
            metadata={"model": "gemini-pro", "region": "us"},
        )

        row = await _row(ctx.session, key.id)
        assert row is not None
        assert row["is_default"] is True
        assert row["metadata"] == {"model": "gemini-pro", "region": "us"}


# =================== QUERIES ===================


class TestListByUser:
    async def test_lists_only_own_keys_newest_first(self, ctx: RepoContext) -> None:
        oldest = await _new_key(ctx, "openai")
        newest = await _new_key(ctx, "anthropic")
        middle = await _new_key(ctx, "grok")
        await _new_key(ctx, "openai", user_id=ctx.other_user_id)
        now = datetime.now(UTC)
        await _set_created_at(ctx.session, oldest.id, now - timedelta(hours=3))
        await _set_created_at(ctx.session, middle.id, now - timedelta(hours=2))
        await _set_created_at(ctx.session, newest.id, now - timedelta(hours=1))

        keys = await ctx.repo.list_by_user(ctx.user_id)

        assert [k.id for k in keys] == [newest.id, middle.id, oldest.id]

    async def test_active_only_filters_deactivated_keys(self, ctx: RepoContext) -> None:
        active = await _new_key(ctx, "openai")
        inactive = await _new_key(ctx, "anthropic")
        assert await ctx.repo.deactivate(inactive.id, ctx.user_id) is True

        active_ids = {k.id for k in await ctx.repo.list_by_user(str(ctx.user_id))}
        all_ids = {k.id for k in await ctx.repo.list_by_user(str(ctx.user_id), active_only=False)}

        assert active_ids == {active.id}
        assert all_ids == {active.id, inactive.id}

    async def test_user_without_keys_gets_empty_list(self, ctx: RepoContext) -> None:
        await _new_key(ctx, "openai", user_id=ctx.other_user_id)

        assert await ctx.repo.list_by_user(ctx.user_id) == []


class TestGetDefault:
    async def test_returns_active_default_for_provider(self, ctx: RepoContext) -> None:
        await _new_key(ctx, "openai", is_default=False)
        default = await _new_key(ctx, "openai", is_default=True)
        await _new_key(ctx, "openai", user_id=ctx.other_user_id, is_default=True)

        found = await ctx.repo.get_default(str(ctx.user_id), "openai")

        assert found is not None
        assert found.id == default.id

    async def test_returns_none_for_other_provider(self, ctx: RepoContext) -> None:
        await _new_key(ctx, "openai", is_default=True)

        assert await ctx.repo.get_default(ctx.user_id, "anthropic") is None

    async def test_ignores_deactivated_default(self, ctx: RepoContext) -> None:
        default = await _new_key(ctx, "grok", is_default=True)
        await ctx.repo.deactivate(default.id, ctx.user_id)

        assert await ctx.repo.get_default(ctx.user_id, "grok") is None

    async def test_new_default_replaces_previous_one(self, ctx: RepoContext) -> None:
        first = await _new_key(ctx, "openai", is_default=True)
        second = await _new_key(ctx, "openai", is_default=True)

        found = await ctx.repo.get_default(ctx.user_id, "openai")
        first_row = await _row(ctx.session, first.id)

        assert found is not None
        assert found.id == second.id
        assert first_row is not None
        assert first_row["is_default"] is False


class TestGetByUserAndProvider:
    async def test_filters_by_provider_and_activity(self, ctx: RepoContext) -> None:
        active = await _new_key(ctx, "openai")
        inactive = await _new_key(ctx, "openai")
        await _new_key(ctx, "anthropic")
        await _new_key(ctx, "openai", user_id=ctx.other_user_id)
        await ctx.repo.deactivate(inactive.id, ctx.user_id)

        active_keys = await ctx.repo.get_by_user_and_provider(str(ctx.user_id), "openai")
        all_keys = await ctx.repo.get_by_user_and_provider(ctx.user_id, "openai", active_only=False)

        assert {k.id for k in active_keys} == {active.id}
        assert {k.id for k in all_keys} == {active.id, inactive.id}


class TestGetByIdAndUser:
    async def test_returns_key_for_owner(self, ctx: RepoContext) -> None:
        key = await _new_key(ctx, "openai")

        found = await ctx.repo.get_by_id_and_user(str(key.id), str(ctx.user_id))

        assert found is not None
        assert found.id == key.id

    async def test_returns_none_for_other_user(self, ctx: RepoContext) -> None:
        key = await _new_key(ctx, "openai")

        assert await ctx.repo.get_by_id_and_user(key.id, ctx.other_user_id) is None

    async def test_returns_none_for_unknown_id(self, ctx: RepoContext) -> None:
        assert await ctx.repo.get_by_id_and_user(uuid.uuid4(), ctx.user_id) is None


# =================== DEFAULT MANAGEMENT ===================


class TestUnsetDefault:
    async def test_clears_default_of_provider_only(self, ctx: RepoContext) -> None:
        openai_default = await _new_key(ctx, "openai", is_default=True)
        anthropic_default = await _new_key(ctx, "anthropic", is_default=True)
        other_user_default = await _new_key(
            ctx, "openai", user_id=ctx.other_user_id, is_default=True
        )

        updated = await ctx.repo.unset_default(str(ctx.user_id), "openai")

        assert updated == 1
        openai_row = await _row(ctx.session, openai_default.id)
        anthropic_row = await _row(ctx.session, anthropic_default.id)
        other_row = await _row(ctx.session, other_user_default.id)
        assert openai_row is not None and openai_row["is_default"] is False
        assert anthropic_row is not None and anthropic_row["is_default"] is True
        assert other_row is not None and other_row["is_default"] is True

    async def test_excluded_key_keeps_default(self, ctx: RepoContext) -> None:
        default = await _new_key(ctx, "openai", is_default=True)

        updated = await ctx.repo.unset_default(ctx.user_id, "openai", exclude_id=str(default.id))

        assert updated == 0
        row = await _row(ctx.session, default.id)
        assert row is not None and row["is_default"] is True

    async def test_returns_zero_without_defaults(self, ctx: RepoContext) -> None:
        await _new_key(ctx, "openai", is_default=False)

        assert await ctx.repo.unset_default(ctx.user_id, "openai", exclude_id=uuid.uuid4()) == 0


class TestSetDefault:
    async def test_moves_default_within_provider(self, ctx: RepoContext) -> None:
        current = await _new_key(ctx, "openai", is_default=True)
        target = await _new_key(ctx, "openai", is_default=False)
        other_provider = await _new_key(ctx, "anthropic", is_default=True)

        assert await ctx.repo.set_default(str(target.id), str(ctx.user_id)) is True

        current_row = await _row(ctx.session, current.id)
        target_row = await _row(ctx.session, target.id)
        other_row = await _row(ctx.session, other_provider.id)
        assert current_row is not None and current_row["is_default"] is False
        assert target_row is not None and target_row["is_default"] is True
        assert other_row is not None and other_row["is_default"] is True
        found = await ctx.repo.get_default(ctx.user_id, "openai")
        assert found is not None and found.id == target.id

    async def test_refuses_key_of_another_user(self, ctx: RepoContext) -> None:
        foreign = await _new_key(ctx, "openai", user_id=ctx.other_user_id)

        assert await ctx.repo.set_default(foreign.id, ctx.user_id) is False

        row = await _row(ctx.session, foreign.id)
        assert row is not None and row["is_default"] is False

    async def test_returns_false_for_unknown_key(self, ctx: RepoContext) -> None:
        assert await ctx.repo.set_default(uuid.uuid4(), ctx.user_id) is False


# =================== TIMESTAMPS AND STATUS ===================


class TestUsageAndValidation:
    async def test_update_last_used_sets_timestamp(self, ctx: RepoContext) -> None:
        key = await _new_key(ctx, "openai")
        before = await _row(ctx.session, key.id)
        assert before is not None and before["last_used_at"] is None

        await ctx.repo.update_last_used(str(key.id))

        after = await _row(ctx.session, key.id)
        assert after is not None
        assert after["last_used_at"] is not None
        assert abs(after["last_used_at"] - datetime.now(UTC)) < timedelta(minutes=5)

    async def test_set_validation_status_records_status_and_time(self, ctx: RepoContext) -> None:
        key = await _new_key(ctx, "gemini")

        await ctx.repo.set_validation_status(str(key.id), "valid")

        row = await _row(ctx.session, key.id)
        assert row is not None
        assert row["validation_status"] == "valid"
        assert row["last_validated_at"] is not None

        await ctx.repo.set_validation_status(key.id, "invalid")

        row = await _row(ctx.session, key.id)
        assert row is not None and row["validation_status"] == "invalid"


# =================== DEACTIVATE AND DELETE ===================


class TestDeactivate:
    async def test_owner_can_deactivate(self, ctx: RepoContext) -> None:
        key = await _new_key(ctx, "openai")

        assert await ctx.repo.deactivate(str(key.id), str(ctx.user_id)) is True

        row = await _row(ctx.session, key.id)
        assert row is not None and row["is_active"] is False

    async def test_other_user_cannot_deactivate(self, ctx: RepoContext) -> None:
        key = await _new_key(ctx, "openai")

        assert await ctx.repo.deactivate(key.id, ctx.other_user_id) is False

        row = await _row(ctx.session, key.id)
        assert row is not None and row["is_active"] is True


class TestHardDelete:
    async def test_only_owner_can_delete(self, ctx: RepoContext) -> None:
        key = await _new_key(ctx, "openai")

        assert await ctx.repo.hard_delete(key.id, ctx.other_user_id) is False
        assert await _row(ctx.session, key.id) is not None

        assert await ctx.repo.hard_delete(str(key.id), str(ctx.user_id)) is True
        assert await _row(ctx.session, key.id) is None

    async def test_deleting_missing_key_returns_false(self, ctx: RepoContext) -> None:
        assert await ctx.repo.hard_delete(uuid.uuid4(), ctx.user_id) is False
