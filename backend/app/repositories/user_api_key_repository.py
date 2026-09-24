"""
User API Key Repository.

Gerencia acesso a dados de API keys de usuários.
A criptografia/descriptografia é feita no nível do Service (Fernet),
seguindo o mesmo padrão de ZoteroIntegration.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_api_key import UserAPIKey
from app.repositories.base import BaseRepository


class UserAPIKeyRepository(BaseRepository[UserAPIKey]):
    """
    Repository para API keys de usuários.

    Gerencia CRUD das keys. A criptografia é feita no Service layer.
    """

    def __init__(self, db: AsyncSession):
        super().__init__(db, UserAPIKey)

    async def list_by_user(
        self,
        user_id: UUID | str,
        active_only: bool = True,
    ) -> list[UserAPIKey]:
        """
        Lista API keys de um usuário.

        Args:
            user_id: ID do usuário.
            active_only: Se deve filtrar apenas ativas.

        Returns:
            Lista de API keys.
        """
        if isinstance(user_id, str):
            user_id = UUID(user_id)

        query = select(UserAPIKey).where(UserAPIKey.user_id == user_id)

        if active_only:
            query = query.where(UserAPIKey.is_active == True)  # noqa: E712

        query = query.order_by(UserAPIKey.created_at.desc())

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_default(
        self,
        user_id: UUID | str,
        provider: str,
    ) -> UserAPIKey | None:
        """
        Busca a API key default de um provedor para um usuário.

        Args:
            user_id: ID do usuário.
            provider: Provedor (openai, anthropic, gemini, grok).

        Returns:
            API key default ou None.
        """
        if isinstance(user_id, str):
            user_id = UUID(user_id)

        query = select(UserAPIKey).where(
            UserAPIKey.user_id == user_id,
            UserAPIKey.provider == provider,
            UserAPIKey.is_active == True,  # noqa: E712
            UserAPIKey.is_default == True,  # noqa: E712
        )

        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_by_user_and_provider(
        self,
        user_id: UUID | str,
        provider: str,
        active_only: bool = True,
    ) -> list[UserAPIKey]:
        """
        Lista API keys de um usuário para um provedor específico.

        Args:
            user_id: ID do usuário.
            provider: Provedor.
            active_only: Se deve filtrar apenas ativas.

        Returns:
            Lista de API keys.
        """
        if isinstance(user_id, str):
            user_id = UUID(user_id)

        query = select(UserAPIKey).where(
            UserAPIKey.user_id == user_id,
            UserAPIKey.provider == provider,
        )

        if active_only:
            query = query.where(UserAPIKey.is_active == True)  # noqa: E712

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_id_and_user(
        self,
        key_id: UUID | str,
        user_id: UUID | str,
    ) -> UserAPIKey | None:
        """
        Busca API key por ID validando ownership.

        Args:
            key_id: ID da API key.
            user_id: ID do usuário (para validação de ownership).

        Returns:
            API key ou None se não encontrada.
        """
        if isinstance(key_id, str):
            key_id = UUID(key_id)
        if isinstance(user_id, str):
            user_id = UUID(user_id)

        query = select(UserAPIKey).where(
            UserAPIKey.id == key_id,
            UserAPIKey.user_id == user_id,
        )

        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def create_key(
        self,
        user_id: UUID | str,
        provider: str,
        encrypted_api_key: str,
        key_name: str | None = None,
        is_default: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> UserAPIKey:
        """
        Cria nova API key.

        NOTA: A API key deve ser criptografada pelo Service antes de chamar este método.

        Args:
            user_id: ID do usuário.
            provider: Provedor.
            encrypted_api_key: API key já criptografada via Fernet.
            key_name: Nome opcional.
            is_default: Se deve ser a default.
            metadata: Metadados extras.

        Returns:
            API key criada.
        """
        if isinstance(user_id, str):
            user_id = UUID(user_id)

        key = UserAPIKey(
            user_id=user_id,
            provider=provider,
            encrypted_api_key=encrypted_api_key,
            key_name=key_name,
            is_default=is_default,
            is_active=True,
            validation_status="pending",
            key_metadata=metadata or {},
        )

        return await self.create(key)

    async def unset_default(
        self,
        user_id: UUID | str,
        provider: str,
        exclude_id: UUID | str | None = None,
    ) -> int:
        """
        Desmarca todas as keys default de um provedor.

        Args:
            user_id: ID do usuário.
            provider: Provedor.
            exclude_id: ID de key para excluir da operação.

        Returns:
            Número de keys atualizadas.
        """
        if isinstance(user_id, str):
            user_id = UUID(user_id)

        stmt = (
            update(UserAPIKey)
            .where(
                UserAPIKey.user_id == user_id,
                UserAPIKey.provider == provider,
                UserAPIKey.is_default == True,  # noqa: E712
            )
            .values(is_default=False)
        )

        if exclude_id:
            if isinstance(exclude_id, str):
                exclude_id = UUID(exclude_id)
            stmt = stmt.where(UserAPIKey.id != exclude_id)

        result = await self.db.execute(stmt)
        await self.db.flush()
        return result.rowcount

    async def set_default(
        self,
        key_id: UUID | str,
        user_id: UUID | str,
    ) -> bool:
        """
        Define uma key como default para seu provedor.

        Desmarca automaticamente outras keys do mesmo provedor.

        Args:
            key_id: ID da key.
            user_id: ID do usuário.

        Returns:
            True se atualizada.
        """
        if isinstance(key_id, str):
            key_id = UUID(key_id)
        if isinstance(user_id, str):
            user_id = UUID(user_id)

        # Buscar a key e seu provedor
        key = await self.get_by_id(key_id)
        if not key or key.user_id != user_id:
            return False

        # Desmarcar outras defaults do mesmo provedor
        await self.unset_default(user_id, key.provider, exclude_id=key_id)

        # Marcar esta como default
        key.is_default = True
        await self.db.flush()
        await self.db.refresh(key)

        return True

    async def update_last_used(self, key_id: UUID | str) -> None:
        """
        Atualiza timestamp de último uso.

        Args:
            key_id: ID da key.
        """
        if isinstance(key_id, str):
            key_id = UUID(key_id)

        await self.db.execute(
            update(UserAPIKey).where(UserAPIKey.id == key_id).values(last_used_at=datetime.now(UTC))
        )
        await self.db.flush()

    async def set_validation_status(
        self,
        key_id: UUID | str,
        status: str,
    ) -> None:
        """
        Atualiza status de validação.

        Args:
            key_id: ID da key.
            status: Status (valid, invalid, pending).
        """
        if isinstance(key_id, str):
            key_id = UUID(key_id)

        await self.db.execute(
            update(UserAPIKey)
            .where(UserAPIKey.id == key_id)
            .values(
                validation_status=status,
                last_validated_at=datetime.now(UTC),
            )
        )
        await self.db.flush()

    async def deactivate(
        self,
        key_id: UUID | str,
        user_id: UUID | str,
    ) -> bool:
        """
        Desativa uma API key.

        Args:
            key_id: ID da key.
            user_id: ID do usuário (para validação).

        Returns:
            True se desativada.
        """
        if isinstance(key_id, str):
            key_id = UUID(key_id)
        if isinstance(user_id, str):
            user_id = UUID(user_id)

        result = await self.db.execute(
            update(UserAPIKey)
            .where(
                UserAPIKey.id == key_id,
                UserAPIKey.user_id == user_id,
            )
            .values(is_active=False)
        )
        await self.db.flush()
        return result.rowcount > 0

    async def hard_delete(
        self,
        key_id: UUID | str,
        user_id: UUID | str,
    ) -> bool:
        """
        Remove permanentemente uma API key.

        Args:
            key_id: ID da key.
            user_id: ID do usuário (para validação).

        Returns:
            True se removida.
        """
        if isinstance(key_id, str):
            key_id = UUID(key_id)
        if isinstance(user_id, str):
            user_id = UUID(user_id)

        result = await self.db.execute(
            delete(UserAPIKey).where(
                UserAPIKey.id == key_id,
                UserAPIKey.user_id == user_id,
            )
        )
        await self.db.flush()
        return result.rowcount > 0
