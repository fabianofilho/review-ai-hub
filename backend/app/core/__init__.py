"""
Core Module.

Exporta componentes centrais da aplicação.
"""

from app.core.config import Settings, get_settings, settings
from app.core.error_handler import (
    AIExtractionError,
    AppError,
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    ExternalServiceError,
    NotFoundError,
    PDFProcessingError,
    RateLimitError,
    ValidationError,
    register_exception_handlers,
)
from app.core.factories import create_storage_adapter
from app.core.logging import (
    LoggerMixin,
    clear_log_context,
    configure_logging,
    get_logger,
    log_context,
)
from app.core.middleware import register_middlewares
from app.core.security import (
    TokenPayload,
    derive_encryption_key,
    get_current_active_user,
    get_current_user,
    require_aal2,
    verify_supabase_jwt,
)

__all__ = [
    # Config
    "Settings",
    "get_settings",
    "settings",
    # Factories
    "create_storage_adapter",
    # Security
    "TokenPayload",
    "get_current_user",
    "get_current_active_user",
    "require_aal2",
    "verify_supabase_jwt",
    "derive_encryption_key",
    # Logging
    "get_logger",
    "configure_logging",
    "log_context",
    "clear_log_context",
    "LoggerMixin",
    # Error Handler
    "AppError",
    "NotFoundError",
    "ValidationError",
    "AuthenticationError",
    "AuthorizationError",
    "ConflictError",
    "RateLimitError",
    "ExternalServiceError",
    "PDFProcessingError",
    "AIExtractionError",
    "register_exception_handlers",
    # Middleware
    "register_middlewares",
]

"""Core module - Configuration, security, and dependencies."""
