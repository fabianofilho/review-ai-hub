"""Integration tests for ZoteroIntegrationRepository."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.integration import ZoteroIntegration
from app.repositories.integration_repository import ZoteroIntegrationRepository
from tests.integration.repositories.factories import add


@pytest.fixture
def repo(session: AsyncSession) -> ZoteroIntegrationRepository:
    return ZoteroIntegrationRepository(session)


async def _create_integration(
    session: AsyncSession, user_id: UUID, *, is_active: bool = True
) -> ZoteroIntegration:
    return await add(
        session,
        ZoteroIntegration(
            user_id=user_id,
            zotero_user_id="12345",
            library_type="user",
            encrypted_api_key="encrypted-old",
            is_active=is_active,
        ),
    )


async def _stored_row(session: AsyncSession, user_id: UUID) -> tuple:
    """Read (is_active, last_sync_at) straight from the database."""
    result = await session.execute(
        select(ZoteroIntegration.is_active, ZoteroIntegration.last_sync_at).where(
            ZoteroIntegration.user_id == user_id
        )
    )
    return tuple(result.one())


class TestGetByUser:
    async def test_returns_active_integration(
        self, repo: ZoteroIntegrationRepository, session: AsyncSession, user_id: UUID
    ) -> None:
        integration = await _create_integration(session, user_id)

        assert await repo.get_by_user(str(user_id)) is integration

    async def test_skips_inactive_unless_requested(
        self, repo: ZoteroIntegrationRepository, session: AsyncSession, user_id: UUID
    ) -> None:
        integration = await _create_integration(session, user_id, is_active=False)

        assert await repo.get_by_user(user_id) is None
        assert await repo.get_by_user(user_id, active_only=False) is integration

    async def test_returns_none_without_integration(
        self, repo: ZoteroIntegrationRepository
    ) -> None:
        assert await repo.get_by_user(uuid4()) is None


class TestUpsert:
    async def test_creates_active_integration(
        self, repo: ZoteroIntegrationRepository, session: AsyncSession, user_id: UUID
    ) -> None:
        created = await repo.upsert(str(user_id), "999", "encrypted-key", "group")

        assert created.id is not None
        assert created.user_id == user_id
        assert created.zotero_user_id == "999"
        assert created.encrypted_api_key == "encrypted-key"
        assert created.library_type == "group"
        assert created.is_active is True
        assert await repo.get_by_user(user_id) is created

    async def test_updates_and_reactivates_existing_integration(
        self, repo: ZoteroIntegrationRepository, session: AsyncSession, user_id: UUID
    ) -> None:
        existing = await _create_integration(session, user_id, is_active=False)

        updated = await repo.upsert(user_id, "777", "encrypted-new", "group")

        assert updated is existing
        assert updated.zotero_user_id == "777"
        assert updated.encrypted_api_key == "encrypted-new"
        assert updated.library_type == "group"
        assert updated.is_active is True
        count = await session.execute(
            select(ZoteroIntegration.id).where(ZoteroIntegration.user_id == user_id)
        )
        assert len(count.all()) == 1


class TestUpdateLastSync:
    async def test_sets_last_sync_timestamp(
        self, repo: ZoteroIntegrationRepository, session: AsyncSession, user_id: UUID
    ) -> None:
        await _create_integration(session, user_id)
        before = datetime.now(UTC)

        await repo.update_last_sync(str(user_id))

        _, last_sync_at = await _stored_row(session, user_id)
        assert last_sync_at is not None
        assert last_sync_at >= before


class TestDeactivate:
    async def test_deactivates_existing_integration(
        self, repo: ZoteroIntegrationRepository, session: AsyncSession, user_id: UUID
    ) -> None:
        await _create_integration(session, user_id)

        assert await repo.deactivate(str(user_id)) is True

        is_active, _ = await _stored_row(session, user_id)
        assert is_active is False
        assert await repo.get_by_user(user_id) is None

    async def test_returns_false_when_user_has_no_integration(
        self, repo: ZoteroIntegrationRepository
    ) -> None:
        assert await repo.deactivate(uuid4()) is False
