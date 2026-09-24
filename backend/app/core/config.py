"""
Application Configuration.

Gerencia todas as configurações da aplicação via variáveis de ambiente
usando Pydantic Settings.
"""

from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from pydantic import PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Configurações da aplicação carregadas de variáveis de ambiente.

    Todas as variáveis podem ser sobrescritas via .env ou environment.
    """

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parents[2] / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # =================== APP ===================
    PROJECT_NAME: str = "Review Hub API"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"

    # =================== CORS ===================
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://localhost:8080,http://127.0.0.1:8080,https://review-ai-hub.vercel.app"

    @property
    def cors_origins_list(self) -> list[str]:
        """Retorna lista de origens CORS com fallback seguro para desenvolvimento."""
        configured = [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]
        # Mantem origens essenciais para desenvolvimento mesmo quando CORS_ORIGINS no .env estiver desatualizado.
        defaults = [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:3000",
            "http://localhost:8080",
            "http://127.0.0.1:8080",
            "https://review-ai-hub.vercel.app",
        ]
        merged: list[str] = []
        for origin in [*configured, *defaults]:
            if origin not in merged:
                merged.append(origin)
        return merged

    # =================== SUPABASE ===================
    SUPABASE_URL: str
    SUPABASE_SERVICE_ROLE_KEY: str
    SUPABASE_ANON_KEY: str
    SUPABASE_JWT_SECRET: str | None = None
    # local | production (default: production)
    SUPABASE_ENV: str | None = None

    # =================== DATABASE ===================
    # Connection string do Postgres (Supabase ou local)
    DATABASE_URL: PostgresDsn
    # Direct connection (bypasses PgBouncer) — required for Alembic migrations.
    # Set this to the Supabase "Direct connection" URL (port 5432, db.xxx.supabase.co).
    # Falls back to DATABASE_URL in local dev where there is no pooler.
    DIRECT_DATABASE_URL: str | None = None

    @property
    def async_database_url(self) -> str:
        """Retorna a URL do banco para uso com asyncpg."""
        url = str(self.DATABASE_URL)
        async_url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        parsed = urlparse(async_url)
        query_items = dict(parse_qsl(parsed.query, keep_blank_values=True))
        if "sslmode" in query_items and "ssl" not in query_items:
            query_items["ssl"] = query_items.pop("sslmode")
        return urlunparse(parsed._replace(query=urlencode(query_items)))

    # =================== OPENAI ===================
    # Opcional: fallback global para quando usuário não tem BYOK configurado
    OPENAI_API_KEY: str | None = None
    OPENAI_DEFAULT_MODEL: str = "gpt-4o-mini"

    # =================== RATE LIMITING ===================
    RATE_LIMIT_PER_MINUTE: int = 60

    # =================== SECURITY ===================
    # Chave para criptografia de dados sensíveis (ex: Zotero API key)
    ENCRYPTION_KEY: str = "review_hub_default_key_change_me_in_production"

    # =================== LANGSMITH (OPCIONAL) ===================
    LANGCHAIN_TRACING_V2: bool = False
    LANGCHAIN_API_KEY: str | None = None
    LANGCHAIN_PROJECT: str = "review-hub"

    @property
    def supabase_env(self) -> str:
        """Retorna o ambiente do Supabase (local | production)."""
        value = (self.SUPABASE_ENV or "").strip().lower()
        return "local" if value == "local" else "production"


@lru_cache
def get_settings() -> Settings:
    """
    Retorna instância singleton das configurações.

    Usa lru_cache para evitar re-parsing das variáveis de ambiente.
    """
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
