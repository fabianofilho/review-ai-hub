"""
API Key Service.

Gerencia API keys de provedores externos com criptografia via Fernet.
Segue o mesmo padrão de ZoteroService para consistência.
"""

import base64
from typing import Any
from uuid import UUID

import httpx
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import LoggerMixin
from app.core.security import derive_encryption_key
from app.models.user_api_key import SUPPORTED_PROVIDERS, UserAPIKey
from app.repositories.user_api_key_repository import UserAPIKeyRepository


class APIKeyService(LoggerMixin):
    """
    Service para gerenciar API keys de usuários.

    Responsabilidades:
    - CRUD de API keys com criptografia Fernet
    - Validação de keys por provedor
    - Obtenção de key default com fallback para global

    Segue o mesmo padrão de ZoteroService para criptografia.
    """

    def __init__(self, db: AsyncSession, user_id: str | UUID):
        """
        Inicializa o service.

        Args:
            db: Sessão async do SQLAlchemy.
            user_id: ID do usuário autenticado.
        """
        self.db = db
        self._user_id_str = str(user_id)
        self._user_id: UUID | None = None

        # Tenta converter para UUID, mas não falha se for inválido (ex: testes)
        if isinstance(user_id, UUID):
            self._user_id = user_id
        elif isinstance(user_id, str):
            try:
                self._user_id = UUID(user_id)
            except ValueError:
                # user_id não é UUID válido (ex: "test-user-id" em testes)
                self._user_id = None

        self._fernet: Fernet | None = None
        self._repo = UserAPIKeyRepository(db)

    @property
    def user_id(self) -> UUID:
        """Retorna o user_id como UUID. Lança ValueError se inválido."""
        if self._user_id is None:
            raise ValueError(f"user_id '{self._user_id_str}' não é um UUID válido")
        return self._user_id

    @property
    def fernet(self) -> Fernet:
        """Retorna instância Fernet para criptografia."""
        if self._fernet is None:
            key = derive_encryption_key(self._user_id_str)
            # Fernet requer chave base64 de 32 bytes
            fernet_key = base64.urlsafe_b64encode(key)
            self._fernet = Fernet(fernet_key)
        return self._fernet

    def _encrypt(self, text: str) -> str:
        """Criptografa texto sensível."""
        return self.fernet.encrypt(text.encode()).decode()

    def _decrypt(self, encrypted: str) -> str:
        """Descriptografa texto."""
        return self.fernet.decrypt(encrypted.encode()).decode()

    async def list_keys(self, active_only: bool = True) -> list[UserAPIKey]:
        """
        Lista API keys do usuário.

        Args:
            active_only: Se deve filtrar apenas ativas.

        Returns:
            Lista de API keys (sem api_key descriptografada).
        """
        return await self._repo.list_by_user(self.user_id, active_only=active_only)

    async def save_key(
        self,
        provider: str,
        api_key: str,
        key_name: str | None = None,
        is_default: bool = False,
        key_metadata: dict[str, Any] | None = None,
        validate: bool = True,
    ) -> dict[str, Any]:
        """
        Salva nova API key com validação opcional.

        Args:
            provider: Provedor (openai, anthropic, gemini, grok).
            api_key: API key em texto plano.
            key_name: Nome opcional.
            is_default: Se deve ser default.
            key_metadata: Metadados extras.
            validate: Se deve validar antes de salvar.

        Returns:
            Dict com id, validation_status e mensagem.

        Raises:
            ValueError: Se provedor não suportado ou key inválida.
        """
        if provider not in SUPPORTED_PROVIDERS:
            raise ValueError(f"Provedor '{provider}' não suportado. Use: {SUPPORTED_PROVIDERS}")

        # Validar key se solicitado
        validation_status = "pending"
        validation_message = None

        if validate:
            validation_result = await self._validate_key(provider, api_key)
            validation_status = validation_result["status"]
            validation_message = validation_result.get("message")

            if validation_status == "invalid":
                self.logger.warning(
                    "api_key_validation_failed",
                    user_id=str(self.user_id),
                    provider=provider,
                    message=validation_message,
                )

        # Criptografar a API key antes de salvar
        encrypted_key = self._encrypt(api_key)

        # Criar a key
        key = await self._repo.create_key(
            user_id=self.user_id,
            provider=provider,
            encrypted_api_key=encrypted_key,
            key_name=key_name,
            is_default=is_default,
            metadata=key_metadata,
        )

        # Atualizar status de validação
        if validation_status != "pending":
            await self._repo.set_validation_status(key.id, validation_status)

        self.logger.info(
            "api_key_saved",
            user_id=str(self.user_id),
            provider=provider,
            key_id=str(key.id),
            validation_status=validation_status,
        )

        return {
            "id": str(key.id),
            "provider": provider,
            "validation_status": validation_status,
            "validation_message": validation_message,
            "is_default": key.is_default,
        }

    async def get_key_for_provider(
        self,
        provider: str,
        use_fallback: bool = True,
    ) -> str | None:
        """
        Obtém API key descriptografada para um provedor.

        Prioridade:
        1. Key default do usuário para o provedor
        2. Fallback para key global (se use_fallback=True)

        Args:
            provider: Provedor.
            use_fallback: Se deve usar key global como fallback.

        Returns:
            API key descriptografada ou None.
        """
        # Se user_id não é válido (ex: testes), vai direto para fallback
        if self._user_id is not None:
            # Tentar obter key do usuário
            default_key = await self._repo.get_default(self._user_id, provider)

            if default_key and default_key.encrypted_api_key:
                # Atualizar last_used_at
                await self._repo.update_last_used(default_key.id)
                # Descriptografar e retornar
                return self._decrypt(default_key.encrypted_api_key)

        # Fallback para key global
        if use_fallback:
            return self._get_global_key(provider)

        return None

    async def get_decrypted_key(
        self,
        key_id: UUID | str,
    ) -> str | None:
        """
        Obtém API key descriptografada por ID.

        Args:
            key_id: ID da API key.

        Returns:
            API key descriptografada ou None.
        """
        key = await self._repo.get_by_id_and_user(key_id, self.user_id)

        if key and key.encrypted_api_key:
            return self._decrypt(key.encrypted_api_key)

        return None

    def _get_global_key(self, provider: str) -> str | None:
        """
        Retorna a API key global do provedor (das settings).

        Args:
            provider: Provedor.

        Returns:
            API key global ou None.
        """
        if provider == "openai":
            return settings.OPENAI_API_KEY
        # Outros provedores podem ser adicionados aqui quando tiverem keys globais
        return None

    async def set_default(self, key_id: str | UUID) -> bool:
        """
        Define uma key como default para seu provedor.

        Args:
            key_id: ID da key.

        Returns:
            True se atualizada.
        """
        success = await self._repo.set_default(key_id, self.user_id)

        if success:
            self.logger.info(
                "api_key_set_default",
                user_id=str(self.user_id),
                key_id=str(key_id),
            )

        return success

    async def deactivate_key(self, key_id: str | UUID) -> bool:
        """
        Desativa uma API key.

        Args:
            key_id: ID da key.

        Returns:
            True se desativada.
        """
        success = await self._repo.deactivate(key_id, self.user_id)

        if success:
            self.logger.info(
                "api_key_deactivated",
                user_id=str(self.user_id),
                key_id=str(key_id),
            )

        return success

    async def delete_key(self, key_id: str | UUID) -> bool:
        """
        Remove permanentemente uma API key.

        Args:
            key_id: ID da key.

        Returns:
            True se removida.
        """
        success = await self._repo.hard_delete(key_id, self.user_id)

        if success:
            self.logger.info(
                "api_key_deleted",
                user_id=str(self.user_id),
                key_id=str(key_id),
            )

        return success

    async def revalidate_key(self, key_id: str | UUID) -> dict[str, Any]:
        """
        Revalida uma API key existente.

        Args:
            key_id: ID da key.

        Returns:
            Dict com status e mensagem.
        """
        if isinstance(key_id, str):
            key_id = UUID(key_id)

        # Buscar a key
        key = await self._repo.get_by_id_and_user(key_id, self.user_id)
        if not key:
            raise ValueError("API key não encontrada")

        # Descriptografar a key
        decrypted_key = self._decrypt(key.encrypted_api_key)

        # Validar
        result = await self._validate_key(key.provider, decrypted_key)

        # Atualizar status
        await self._repo.set_validation_status(key_id, result["status"])

        self.logger.info(
            "api_key_revalidated",
            user_id=str(self.user_id),
            key_id=str(key_id),
            status=result["status"],
        )

        return result

    async def _validate_key(
        self,
        provider: str,
        api_key: str,
    ) -> dict[str, Any]:
        """
        Valida API key fazendo chamada de teste ao provedor.

        Args:
            provider: Provedor.
            api_key: API key.

        Returns:
            Dict com status ('valid', 'invalid', 'pending') e message.
        """
        try:
            if provider == "openai":
                return await self._validate_openai(api_key)
            elif provider == "anthropic":
                return await self._validate_anthropic(api_key)
            elif provider == "gemini":
                return await self._validate_gemini(api_key)
            elif provider == "grok":
                return await self._validate_grok(api_key)
            else:
                return {"status": "pending", "message": "Provedor sem validação implementada"}
        except Exception as e:
            self.logger.error(
                "api_key_validation_error",
                provider=provider,
                error=str(e),
            )
            return {"status": "pending", "message": f"Erro na validação: {str(e)}"}

    async def _validate_openai(self, api_key: str) -> dict[str, Any]:
        """Valida API key da OpenAI listando modelos."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10.0,
            )

            if response.status_code == 200:
                return {"status": "valid", "message": "API key válida"}
            elif response.status_code == 401:
                return {"status": "invalid", "message": "API key inválida ou expirada"}
            elif response.status_code == 429:
                return {"status": "valid", "message": "API key válida (rate limited)"}
            else:
                return {"status": "invalid", "message": f"Erro: {response.status_code}"}

    async def _validate_anthropic(self, api_key: str) -> dict[str, Any]:
        """Valida API key da Anthropic."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "claude-3-haiku-20240307",
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "hi"}],
                },
                timeout=10.0,
            )

            if response.status_code == 200:
                return {"status": "valid", "message": "API key válida"}
            elif response.status_code in (401, 403):
                return {"status": "invalid", "message": "API key inválida"}
            elif response.status_code == 429:
                return {"status": "valid", "message": "API key válida (rate limited)"}
            else:
                error_data = response.json() if response.text else {}
                if "authentication" in str(error_data).lower():
                    return {"status": "invalid", "message": "API key inválida"}
                return {"status": "valid", "message": "API key provavelmente válida"}

    async def _validate_gemini(self, api_key: str) -> dict[str, Any]:
        """Valida API key do Google Gemini."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://generativelanguage.googleapis.com/v1/models?key={api_key}",
                timeout=10.0,
            )

            if response.status_code == 200:
                return {"status": "valid", "message": "API key válida"}
            elif response.status_code in (400, 401, 403):
                return {"status": "invalid", "message": "API key inválida"}
            elif response.status_code == 429:
                return {"status": "valid", "message": "API key válida (rate limited)"}
            else:
                return {"status": "invalid", "message": f"Erro: {response.status_code}"}

    async def _validate_grok(self, api_key: str) -> dict[str, Any]:
        """Valida API key do Grok (xAI)."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.x.ai/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10.0,
            )

            if response.status_code == 200:
                return {"status": "valid", "message": "API key válida"}
            elif response.status_code == 401:
                return {"status": "invalid", "message": "API key inválida"}
            elif response.status_code == 429:
                return {"status": "valid", "message": "API key válida (rate limited)"}
            else:
                return {"status": "invalid", "message": f"Erro: {response.status_code}"}
