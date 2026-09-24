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

from alembic.config import Config as AlembicConfig
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import create_engine, text

from app.api.v1.router import api_router
from app.core.config import settings, validate_encryption_key
from app.core.deps import AsyncSessionLocal
from app.core.error_handler import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import register_middlewares
from app.core.security import get_jwks
from app.models import Base  # noqa: F401  # Import all models so they are registered
from app.utils.rate_limiter import limiter

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


def check_encryption_key() -> None:
    """
    Abort startup when ENCRYPTION_KEY is empty or a publicly known default.

    Only enforced when DEBUG is off, so local development keeps working.
    Exits with SystemExit(1), like check_pending_migrations().
    """
    try:
        validate_encryption_key(settings)
    except RuntimeError as exc:
        logger.error("insecure_encryption_key", error=str(exc))
        raise SystemExit(1) from exc


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:  # noqa: ARG001
    """
    Manages application lifecycle.

    - Startup: Configure logging, DB connections, etc.
    - Shutdown: Close connections and clean up resources.
    """
    # Startup
    configure_logging()
    check_encryption_key()
    check_pending_migrations()
    logger.info(
        "application_startup",
        project_name=settings.PROJECT_NAME,
        debug=settings.DEBUG,
    )

    # Warm-up: avoid first request paying JWKS and DB pool latency
    try:
        await get_jwks()
        logger.debug("jwks_warm_ok")
    except Exception as e:
        logger.warning("jwks_warm_skipped", error=str(e))
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        logger.debug("db_pool_warm_ok")
    except Exception as e:
        logger.warning("db_pool_warm_skipped", error=str(e))

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
        description="Backend API for Review Hub - Systematic Review Platform",
        version="0.1.0",
        openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
        docs_url=f"{settings.API_V1_PREFIX}/docs",
        redoc_url=f"{settings.API_V1_PREFIX}/redoc",
        lifespan=lifespan,
    )

    # Rate Limiter
    app.state.limiter = limiter
    # Starlette types exception handlers as taking a bare Exception, so a handler
    # narrowed to RateLimitExceeded is rejected although it is only called for it.
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

    # Register custom exception handlers
    register_exception_handlers(app)

    # CORS Middleware (must come before other middlewares)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Trace-Id", "X-Response-Time"],
    )

    # Register custom middlewares (RequestId, Logging, Timing)
    register_middlewares(app)

    # API Routes
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    @app.get("/health", tags=["Health"])
    async def health_check() -> dict[str, str]:
        """Health check endpoint."""
        return {"status": "healthy", "version": "0.1.0"}

    @app.get("/", tags=["Root"])
    async def root() -> dict[str, str]:
        """
        Root endpoint with API info.
        To access the docs, visit {settings.API_V1_PREFIX}/docs, e.g. http://localhost:8000/api/v1/docs
        """
        return {
            "name": settings.PROJECT_NAME,
            "version": "0.1.0",
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
