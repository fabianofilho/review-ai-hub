"""
User API Key Model.

Modelo para armazenar API keys de provedores externos (OpenAI, Anthropic, etc.).
A criptografia é feita na aplicação via Fernet, seguindo o padrão de ZoteroIntegration.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.user import Profile


# Provedores suportados
SUPPORTED_PROVIDERS = ("openai", "anthropic", "gemini", "grok")

# Status de validação
VALIDATION_STATUSES = ("valid", "invalid", "pending")


class UserAPIKey(BaseModel):
    """
    API key de provedor externo por usuário.

    A criptografia é feita na aplicação via Fernet (mesmo padrão de ZoteroIntegration).
    Isso garante funcionamento tanto em ambiente local quanto em produção.

    Attributes:
        user_id: ID do usuário dono da key.
        provider: Provedor da API (openai, anthropic, gemini, grok).
        encrypted_api_key: API key criptografada via Fernet.
        key_name: Nome opcional para identificar a key.
        is_active: Se a key está ativa.
        is_default: Se é a key padrão para o provedor.
        last_used_at: Última vez que a key foi usada.
        last_validated_at: Última validação da key.
        validation_status: Status da validação (valid, invalid, pending).
        key_metadata: Metadados extras (modelo preferido, região, etc.).
    """

    __tablename__ = "user_api_keys"

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    provider: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        index=True,
    )

    # API key criptografada via Fernet (igual ao Zotero)
    encrypted_api_key: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    key_name: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    is_default: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    validation_status: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    key_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        default=dict,
        nullable=True,
        name="metadata",  # Nome da coluna no banco
    )

    # Relationships
    user: Mapped["Profile"] = relationship(
        "Profile",
        back_populates="api_keys",
    )

    __table_args__ = (
        CheckConstraint(
            "provider IN ('openai', 'anthropic', 'gemini', 'grok')",
            name="user_api_keys_provider_check",
        ),
        CheckConstraint(
            "validation_status IS NULL OR validation_status IN ('valid', 'invalid', 'pending')",
            name="user_api_keys_validation_status_check",
        ),
        {"schema": "public"},
    )

    def __repr__(self) -> str:
        return f"<UserAPIKey user={self.user_id} provider={self.provider}>"
