"""
Integration Models.

Modelos para integrações externas como Zotero.
"""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.user import Profile


class ZoteroIntegration(BaseModel):
    """
    Integração Zotero por usuário.

    API keys são criptografadas com Fernet (chave derivada do user_id).
    """

    __tablename__ = "zotero_integrations"

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.profiles.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )

    zotero_user_id: Mapped[str] = mapped_column(Text, nullable=False)
    library_type: Mapped[str] = mapped_column(Text, nullable=False)  # 'user' ou 'group'

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    last_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # API key criptografada
    encrypted_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    user: Mapped["Profile"] = relationship(
        "Profile",
        back_populates="zotero_integration",
    )

    def __repr__(self) -> str:
        return f"<ZoteroIntegration user={self.user_id}>"
