"""
Application Configuration.

Manages todas as configuracoes da aplicacao via variaveis de ambiente
usando Pydantic Settings.
"""

from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config_validators import validate_linear_team_id

API_VERSION = "0.1.0"
"""The published API version: ``FastAPI(version=…)``, ``/health``, ``/`` and the MCP server."""


class Settings(BaseSettings):
    """
    Configuracoes da aplicacao carregadas de variaveis de ambiente.

    Todas as variaveis podem ser sobrescritas via .env or environment.
    """

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parents[2] / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # =================== APP ===================
    PROJECT_NAME: str = "Prumo API"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"

    # =================== CORS ===================
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://localhost:8080,http://127.0.0.1:8080,https://prumoai.vercel.app"

    # Public origin of the web app: links in agent (MCP) results point here.
    PUBLIC_APP_URL: str = "https://prumoai.vercel.app"

    # Public origin of this API (scheme://host[:port]). Setting it turns OAuth for
    # /mcp ON; unset or empty keeps it OFF (fail closed, ADR 0022).
    PUBLIC_API_URL: str | None = None

    @property
    def oauth_enabled(self) -> bool:
        return bool((self.PUBLIC_API_URL or "").strip())

    @property
    def public_api_url(self) -> str:
        """``PUBLIC_API_URL`` without a trailing slash; raises when OAuth is off."""
        if not self.oauth_enabled:
            raise RuntimeError("PUBLIC_API_URL is unset: OAuth for /mcp is off")
        return (self.PUBLIC_API_URL or "").strip().rstrip("/")

    @property
    def mcp_resource_url(self) -> str:
        return self.public_api_url + "/mcp"

    # Comma-separated OAuth redirect URIs a client may register (exact match);
    # loopback http URIs are always allowed (ADR 0022).
    MCP_OAUTH_REDIRECT_URIS: str = "https://claude.ai/api/mcp/auth_callback"

    @property
    def mcp_oauth_redirect_uris_list(self) -> list[str]:
        return [u.strip() for u in self.MCP_OAUTH_REDIRECT_URIS.split(",") if u.strip()]

    @property
    def cors_origins_list(self) -> list[str]:
        """Return the CORS allow-list with a safe development fallback."""
        configured = [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]
        # Always-allowed origins so a stale CORS_ORIGINS env can never lock
        # out local dev or the canonical production frontend. Only
        # prumoai.vercel.app is pinned: env drift between the Vercel domain
        # and this list caused the 2026-05-31 extraction outage (preflights
        # rejected as "Disallowed CORS origin"). Keep this list to origins
        # the project actually controls -- these bypass CORS_ORIGINS
        # entirely, so a host listed here cannot be revoked from the env.
        defaults = [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:3000",
            "http://localhost:8080",
            "http://127.0.0.1:8080",
            "https://prumoai.vercel.app",
        ]
        merged: list[str] = []
        for origin in [*configured, *defaults]:
            if origin not in merged:
                merged.append(origin)
        return merged

    @property
    def cors_origin_regex(self) -> str | None:
        """Return an extra CORS origin pattern for local development.

        In DEBUG, accept any ``http://localhost:<port>`` /
        ``http://127.0.0.1:<port>`` origin on top of the explicit
        allow-list. Concurrent git worktrees cannot all serve Vite on the
        pinned dev ports (the main checkout owns 8080), and a worktree on
        e.g. 8090 otherwise fails every preflight -- which surfaces not as
        a CORS error but as a page that never reaches ready, or an E2E
        spec that skips with a misleading reason.

        Returns ``None`` outside DEBUG so production keeps the explicit
        allow-list: constitution IV forbids wildcard origins in
        production, and this pattern is deliberately not one -- the
        scheme is pinned to http and the host to the loopback names, both
        anchored so ``http://localhost.evil.example:8090`` cannot match.
        """
        if not self.DEBUG:
            return None
        return r"^http://(localhost|127\.0\.0\.1):\d+$"

    # =================== MCP (/mcp mount) ===================
    # Comma-separated, like CORS_ORIGINS. "test" is the Host httpx sends for the
    # suite's base_url="http://test". Production sets MCP_ALLOWED_HOSTS to its
    # public host; unset there, every request gets 421 (fails closed).
    MCP_ALLOWED_HOSTS: str = "localhost:*,127.0.0.1:*,[::1]:*,test"
    # Empty: no browser Origin may call /mcp. CLI agents send no Origin and pass.
    MCP_ALLOWED_ORIGINS: str = ""
    # Concurrent /mcp requests per token per process; over it -> 429 with
    # Retry-After: 1, refused before any database checkout. Half the default
    # web pool (DB_POOL_SIZE + DB_MAX_OVERFLOW = 8), so one token's burst
    # leaves connections for every other caller.
    MCP_MAX_INFLIGHT_PER_TOKEN: int = Field(default=4, ge=1)

    @property
    def mcp_allowed_hosts(self) -> list[str]:
        """Host header allow-list for the MCP transport's DNS-rebinding guard."""
        return [h.strip() for h in self.MCP_ALLOWED_HOSTS.split(",") if h.strip()]

    @property
    def mcp_allowed_origins(self) -> list[str]:
        """Origin allow-list for /mcp; an absent Origin always passes."""
        return [o.strip() for o in self.MCP_ALLOWED_ORIGINS.split(",") if o.strip()]

    # =================== DEPLOY IDENTITY ===================
    # Injected by Railway on every deploy. Surfaced by /health so the
    # post-deploy smoke can prove WHICH build is live — reachability alone
    # cannot distinguish a fresh deploy from one stuck on an older SHA.
    # ``None`` outside Railway (local dev, tests, CI).
    RAILWAY_GIT_COMMIT_SHA: str | None = None

    # =================== SUPABASE ===================
    SUPABASE_URL: str
    SUPABASE_SERVICE_ROLE_KEY: str
    # No SUPABASE_ANON_KEY here: the anon key is a browser credential
    # (frontend ``VITE_SUPABASE_*``). The backend talks to Supabase as
    # service role, so declaring it would force every deploy to carry a
    # secret nothing reads.
    SUPABASE_JWT_SECRET: str | None = None
    # local | production (default: production)
    SUPABASE_ENV: str | None = None

    # =================== DATABASE ===================
    # Connection string do Postgres (Supabase or local)
    DATABASE_URL: PostgresDsn
    # Direct connection (bypasses PgBouncer) — required for Alembic migrations.
    # Set this to the Supabase "Direct connection" URL (port 5432, db.xxx.supabase.co).
    # Falls back to DATABASE_URL in local dev where there is in the pooler.
    DIRECT_DATABASE_URL: str | None = None
    # The web engine's pool (one gunicorn worker per container). Production
    # reaches the Supabase pooler in session mode, capped at 15 clients: the
    # web pool (size + overflow = 8) plus the Celery worker (2 children x up to
    # 2 sessions = 4) leaves headroom for migrations and admin sessions.
    # A checkout that waits past DB_POOL_TIMEOUT seconds raises
    # sqlalchemy.exc.TimeoutError (/mcp answers it with 503 + Retry-After).
    DB_POOL_SIZE: int = Field(default=5, ge=1)
    DB_MAX_OVERFLOW: int = Field(default=3, ge=0)  # 0 is valid: a fixed-size pool
    DB_POOL_TIMEOUT: float = Field(default=10.0, gt=0)

    @property
    def async_database_url(self) -> str:
        """Return a URL do banco for uso with asyncpg."""
        url = str(self.DATABASE_URL)
        async_url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        parsed = urlparse(async_url)
        query_items = dict(parse_qsl(parsed.query, keep_blank_values=True))
        if "sslmode" in query_items and "ssl" not in query_items:
            query_items["ssl"] = query_items.pop("sslmode")
        return urlunparse(parsed._replace(query=urlencode(query_items)))

    # =================== GLOBAL PROVIDER KEYS ===================
    # Optional operator keys. Each hosted provider in app.llm.registry names
    # ONE of these; when it is empty the provider needs a user or project
    # key in this deployment (the engine read's ``availability``). Never a
    # host-bearing provider — a host is a per-connection fact.
    # Read dynamically by app.llm.registry.global_key_for via
    # getattr(settings, spec.global_key_setting) — no static `settings.X`
    # reference exists, so the vulture dead-code scan cannot see the read.
    OPENAI_API_KEY: str | None = None
    ANTHROPIC_API_KEY: str | None = None
    GOOGLE_API_KEY: str | None = None
    OLLAMA_API_KEY: str | None = None

    # =================== LLM (provider-agnostic) ===================
    # Single authoritative model/provider for AI extraction. The former
    # OPENAI_DEFAULT_MODEL was defined but never read at runtime; it is
    # collapsed here. Providers and their optional operator keys are declared
    # in app.llm.registry (OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY,
    # OLLAMA_API_KEY);
    # a provider whose key is empty is BYOK-only in that deployment.
    # The default must stay in app.llm.catalog.CATALOG — a default that falls
    # off the roster reads as "retired" and blocks every run that never chose
    # an engine. No Railway env override exists for it: prod follows this code
    # default at deploy time.
    LLM_PROVIDER: str = "openai"
    LLM_DEFAULT_MODEL: str = "gpt-5.6-luna"
    LLM_TIMEOUT_SECONDS: float = 120.0
    # Token budget for the per-run block-markdown assembly window (A1). A paper
    # under this budget is sent in full; above it the assembler drops whole
    # low-priority sections (IMRaD ranking) and logs AssemblyInfo.truncated.
    # Sized against the SMALLEST context window in app.llm.catalog.CATALOG
    # (currently gpt-4o-mini at 128k), NOT the default model — a budget that
    # fits only the flagship windows overflows legacy-pinned projects. Leaves
    # headroom for system prompt + schema + output + reask. No hard per-run
    # cost ceiling (logged, not enforced — spec §8.5).
    LLM_ASSEMBLY_BUDGET_TOKENS: int = 96_000

    # =================== PARSING ===================
    # Per-project default resolution is "auto" (see ParserSettingsService +
    # parsing_tasks._run_parse): the LlamaParse cloud parser when a llama_cloud
    # key is configured, else the free PyMuPDF parser. This scalar is only the
    # factory's last-resort fallback when no per-call backend is given.
    PARSER_BACKEND: str = "pymupdf"
    # Optional global LlamaCloud key; per-user BYOK (llm_connections) takes
    # precedence over this global fallback.
    LLAMA_CLOUD_API_KEY: str | None = None
    # Cap the blocking LlamaParse parse() call. The SDK's own default is
    # 7200s (2h); left uncapped, a slow/stuck cloud job pins a worker slot
    # and leaves the ArticleFile at "pending" forever. On timeout the parser
    # degrades to the local PyMuPDF backend (see FallbackDocumentParser).
    # 240s gives the (slow) agentic tier a realistic window without disabling
    # it via constant fallback; tune against measured agentic latency. The
    # per-task Celery time limits (parsing_tasks) must stay above 2x this.
    LLAMA_PARSE_TIMEOUT_SECONDS: float = 240.0

    # =================== RATE LIMITING ===================
    RATE_LIMIT_PER_MINUTE: int = 60
    # Shared limiter storage (Redis in production) so budgets hold across
    # processes and restarts. Unset -> per-process ``memory://``.
    RATE_LIMIT_STORAGE_URI: str | None = None
    # Request header carrying the caller's IP, set by the hosting edge proxy
    # (Railway: ``X-Real-IP``). Per-IP buckets key on it only when set; unset
    # keys on the TCP peer. Trust assumption: the edge overwrites any copy the
    # caller sends, and no path bypasses the edge (docs/reference/deployment.md).
    TRUSTED_CLIENT_IP_HEADER: str | None = None

    # =================== REDIS ===================
    # Celery broker/result backend and the job-owner records.
    REDIS_URL: str = "redis://localhost:6379/0"

    # =================== SECURITY ===================
    # Chave for criptografia de data sensiveis (ex: Zotero API key)
    ENCRYPTION_KEY: str = "review_hub_default_key_change_me_in_production"
    # SSRF escape hatch for custom LLM endpoints (app/core/net_guard.py):
    # allows private/loopback ranges and plain http. Honored ONLY when
    # supabase_env == "local" — the flag is inert in production by code,
    # not convention (net_guard._private_ranges_allowed).
    ALLOW_PRIVATE_LLM_ENDPOINTS: bool = False

    # =================== FEEDBACK / LINEAR ===================
    LINEAR_API_KEY: str | None = None
    LINEAR_TEAM_ID: str | None = None
    FEEDBACK_MEDIA_BUCKET: str = "feedback-media"
    FEEDBACK_MAX_IMAGE_BYTES: int = 10 * 1024 * 1024
    FEEDBACK_MAX_VIDEO_BYTES: int = 50 * 1024 * 1024

    @field_validator("LINEAR_TEAM_ID")
    @classmethod
    def _validate_linear_team_id(cls, value: str | None) -> str | None:
        """Fail fast at boot if LINEAR_TEAM_ID is set to the team slug, not its UUID."""
        return validate_linear_team_id(value)

    @property
    def supabase_env(self) -> str:
        """Return o ambiente do Supabase (local | production)."""
        value = (self.SUPABASE_ENV or "").strip().lower()
        return "local" if value == "local" else "production"

    @property
    def encryption_key_is_placeholder(self) -> bool:
        """True while ``ENCRYPTION_KEY`` is blank or the published default."""
        key = self.ENCRYPTION_KEY.strip()
        return not key or key == type(self).model_fields["ENCRYPTION_KEY"].default


@lru_cache
def get_settings() -> Settings:
    """
    Return instance singleton of the configuracoes.

    Usa lru_cache for evitar re-parsing of the variaveis de ambiente.
    """
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
