"""
User Models.

Modelo para perfis de usuários.
Sincronizado com tabela profiles criada pelo Supabase Auth.
"""

from uuid import UUID

from sqlalchemy import Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Profile(Base, TimestampMixin):
    """
    Perfil de usuário do sistema.

    Esta tabela é sincronizada com auth.users do Supabase.
    O id é o mesmo do usuário no Supabase Auth.
    """

    __tablename__ = "profiles"

    # PK é o mesmo do auth.users (não usar UUIDMixin)
    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
    )

    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    full_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    projects_created: Mapped[list["Project"]] = relationship(  # type: ignore  # noqa: F821
        "Project",
        back_populates="created_by",
        foreign_keys="Project.created_by_id",
    )
    project_memberships: Mapped[list["ProjectMember"]] = relationship(  # type: ignore  # noqa: F821
        "ProjectMember",
        back_populates="user",
        foreign_keys="ProjectMember.user_id",
    )

    # API keys de provedores externos (OpenAI, Anthropic, etc.)
    api_keys: Mapped[list["UserAPIKey"]] = relationship(  # type: ignore  # noqa: F821
        "UserAPIKey",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    # Integração Zotero
    zotero_integration: Mapped["ZoteroIntegration | None"] = relationship(  # type: ignore  # noqa: F821
        "ZoteroIntegration",
        back_populates="user",
        uselist=False,
    )

    def __repr__(self) -> str:
        return f"<Profile {self.email}>"
