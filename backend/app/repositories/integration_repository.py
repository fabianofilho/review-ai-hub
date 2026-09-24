"""
Integration Repository.

Gerencia acesso a dados de integrações externas.
"""

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.integration import ZoteroIntegration
from app.repositories.base import BaseRepository


class ZoteroIntegrationRepository(BaseRepository[ZoteroIntegration]):
    """
    Repository para integrações Zotero.
    """

    def __init__(self, db: AsyncSession):
        super().__init__(db, ZoteroIntegration)

    async def get_by_user(
        self,
        user_id: UUID | str,
        active_only: bool = True,
    ) -> ZoteroIntegration | None:
        """
        Busca integração Zotero de um usuário.

        Args:
            user_id: ID do usuário.
            active_only: Se deve buscar apenas ativas.

        Returns:
            Integração ou None.
        """
        if isinstance(user_id, str):
            user_id = UUID(user_id)

        query = select(ZoteroIntegration).where(ZoteroIntegration.user_id == user_id)

        if active_only:
            query = query.where(ZoteroIntegration.is_active.is_(True))

        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def upsert(
        self,
        user_id: UUID | str,
        zotero_user_id: str,
        encrypted_api_key: str,
        library_type: str,
    ) -> ZoteroIntegration:
        """
        Cria ou atualiza integração Zotero.

        Args:
            user_id: ID do usuário.
            zotero_user_id: ID do usuário no Zotero.
            encrypted_api_key: API key criptografada.
            library_type: Tipo de biblioteca ('user' ou 'group').

        Returns:
            Integração criada/atualizada.
        """
        if isinstance(user_id, str):
            user_id = UUID(user_id)

        # Verificar se existe
        existing = await self.get_by_user(user_id, active_only=False)

        if existing:
            # Atualizar
            existing.zotero_user_id = zotero_user_id
            existing.encrypted_api_key = encrypted_api_key
            existing.library_type = library_type
            existing.is_active = True
            await self.db.flush()
            await self.db.refresh(existing)
            return existing
        else:
            # Criar nova
            integration = ZoteroIntegration(
                user_id=user_id,
                zotero_user_id=zotero_user_id,
                encrypted_api_key=encrypted_api_key,
                library_type=library_type,
                is_active=True,
            )
            self.db.add(integration)
            await self.db.flush()
            await self.db.refresh(integration)
            return integration

    async def update_last_sync(self, user_id: UUID | str) -> None:
        """
        Atualiza timestamp do último sync.

        Args:
            user_id: ID do usuário.
        """
        if isinstance(user_id, str):
            user_id = UUID(user_id)

        await self.db.execute(
            update(ZoteroIntegration)
            .where(ZoteroIntegration.user_id == user_id)
            .values(last_sync_at=datetime.now(UTC))
        )
        await self.db.flush()

    async def deactivate(self, user_id: UUID | str) -> bool:
        """
        Desativa integração de um usuário.

        Args:
            user_id: ID do usuário.

        Returns:
            True se desativada.
        """
        if isinstance(user_id, str):
            user_id = UUID(user_id)

        result = await self.db.execute(
            update(ZoteroIntegration)
            .where(ZoteroIntegration.user_id == user_id)
            .values(is_active=False)
        )
        await self.db.flush()
        # Session.execute() is typed as Result; an UPDATE runs as a CursorResult.
        return cast(CursorResult[Any], result).rowcount > 0
