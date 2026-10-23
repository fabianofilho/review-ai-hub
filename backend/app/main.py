"""
FastAPI Application Entry Point.

This module configures the main FastAPI application with:
- CORS, Logging and Request ID middleware
- Rate limiting
- Centralized error handling
- Structured logging
- API v1 routes
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import logfire
from alembic.config import Config as AlembicConfig
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import create_engine, text
from starlette.routing import Route

from app.api.mcp.asgi_auth import with_pat_auth
from app.api.mcp.oauth.routes import OAUTH_CORS_PATHS, build_oauth_routes
from app.api.mcp.server import build_mcp_asgi
from app.api.v1.router import api_router
from app.core.config import API_VERSION, settings
from app.core.deps import AsyncSessionLocal, get_supabase_client
from app.core.error_handler import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import PathScopedCORSMiddleware, register_middlewares
from app.core.security import check_encryption_key, get_jwks
from app.llm.observability import configure_observability
from app.utils.rate_limiter import limiter, log_storage_backend

logger = get_logger(__name__)


def check_pending_migrations() -> None:
    """
    Check for pending migrations before starting the application.

    Compares current DB revision with Alembic head revision.
    Exits with SystemExit(1) if there are pending migrations,
    preventing the app from starting with an outdated schema.
    """
    alembic_cfg = AlembicConfig("alembic.ini")
    script = ScriptDirectory.from_config(alembic_cfg)

    raw_database_url = settings.DIRECT_DATABASE_URL or settings.DATABASE_URL.unicode_string()
    sync_url = raw_database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(sync_url)
    try:
        with engine.connect() as conn:
            migration_ctx = MigrationContext.configure(conn)
            current_heads = set(migration_ctx.get_current_heads())
            target_heads = set(script.get_heads())
            pending = target_heads - current_heads
    finally:
        engine.dispose()

    if pending:
        logger.error(
            "unapplied_migrations_detected",
            pending_revisions=list(pending),
        )
        raise SystemExit(1)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Manages application lifecycle.

    - Startup: Configure logging, DB connections, etc.
    - Shutdown: Close connections and clean up resources.
    """
    # Startup
    configure_observability(service_name="prumo-api")
    configure_logging()
    logfire.instrument_fastapi(app)
    check_encryption_key()
    check_pending_migrations()
    logger.info(
        "application_startup",
        project_name=settings.PROJECT_NAME,
        debug=settings.DEBUG,
    )
    log_storage_backend(settings.RATE_LIMIT_STORAGE_URI)

    # Warm-up: avoid first request paying JWKS and DB pool latency
    app.state.jwks_ready = False
    app.state.db_ready = False
    app.state.storage_ready = False
    app.state.storage_error = None

    try:
        await get_jwks()
        app.state.jwks_ready = True
        logger.debug("jwks_warm_ok")
    except Exception as e:
        logger.warning("jwks_warm_skipped", error=str(e))
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        app.state.db_ready = True
        logger.debug("db_pool_warm_ok")
    except Exception as e:
        logger.warning("db_pool_warm_skipped", error=str(e))
    try:
        supabase = get_supabase_client()
        # Validate that storage bucket is reachable at startup.
        supabase.storage.from_("articles").list("", {"limit": 1})
        app.state.storage_ready = True
        logger.debug("storage_bucket_warm_ok", bucket="articles")
    except Exception as e:
        app.state.storage_error = str(e)
        logger.warning(
            "storage_bucket_warm_skipped",
            bucket="articles",
            error=str(e),
        )

    async with app.state.mcp_session_manager.run():
        yield

    # Shutdown
    logger.info("application_shutdown")


def create_app() -> FastAPI:
    """
    Factory function to create the FastAPI application.

    Returns:
        FastAPI: Configured application instance.
    """
    app = FastAPI(
        title=settings.PROJECT_NAME,
        description="Backend API for Prumo - Systematic Review Platform",
        version=API_VERSION,
        openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
        docs_url=f"{settings.API_V1_PREFIX}/docs",
        redoc_url=f"{settings.API_V1_PREFIX}/redoc",
        lifespan=lifespan,
    )

    # Rate Limiter
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # Register custom exception handlers
    register_exception_handlers(app)

    # CORS Middleware (must come before other middlewares). The credential-less
    # OAuth paths bypass it: their route-level CORS answers (ADR 0022).
    app.add_middleware(
        PathScopedCORSMiddleware,
        bypass_paths=OAUTH_CORS_PATHS,
        allow_origins=settings.cors_origins_list,
        # DEBUG only: additionally accept any localhost port so worktree
        # dev servers work without editing an untracked .env. None in
        # production, where the explicit list above is the only gate.
        allow_origin_regex=settings.cors_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Trace-Id", "X-Response-Time"],
    )

    # Register custom middlewares (RequestId, Logging, Timing)
    register_middlewares(app)

    # API Routes
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    # MCP (spec §3): excluded from the JWT dependency, the ApiResponse envelope and
    # the REST error handler; its manager runs in `lifespan`. An exact Route, not
    # app.mount: a Mount answers POST /mcp with a 307 to /mcp/. Starlette treats a
    # non-function endpoint as a raw ASGI app (starlette/routing.py Route.__init__).
    mcp_app, mcp_session_manager = build_mcp_asgi()
    app.state.mcp_session_manager = mcp_session_manager
    if settings.oauth_enabled:
        app.router.routes.extend(build_oauth_routes())
    app.router.routes.append(
        Route(
            "/mcp",
            endpoint=with_pat_auth(mcp_app),
            methods=["GET", "POST", "DELETE"],
            include_in_schema=False,
        )
    )

    @app.get("/health", tags=["Health"])
    async def health_check() -> dict[str, object]:
        """Health check endpoint."""
        return {
            "status": "healthy",
            "version": API_VERSION,
            # The deployed commit (Railway-injected); "unknown" off-platform.
            "commit": settings.RAILWAY_GIT_COMMIT_SHA or "unknown",
            "checks": {
                "jwks_ready": bool(getattr(app.state, "jwks_ready", False)),
                "db_ready": bool(getattr(app.state, "db_ready", False)),
                "storage_ready": bool(getattr(app.state, "storage_ready", False)),
                "storage_error": getattr(app.state, "storage_error", None),
            },
        }

    @app.get("/", tags=["Root"])
    async def root() -> dict[str, str]:
        """
        Root endpoint with API info.
        To access the docs, visit {settings.API_V1_PREFIX}/docs, e.g. http://localhost:8000/api/v1/docs
        """
        return {
            "name": settings.PROJECT_NAME,
            "version": API_VERSION,
            "docs": f"{settings.API_V1_PREFIX}/docs",
        }

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
    )
