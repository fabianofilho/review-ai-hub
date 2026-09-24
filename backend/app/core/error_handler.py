"""
Error Handler Centralizado.

Define exceções customizadas e handlers para a API.
"""

from typing import Any

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.logging import get_logger

logger = get_logger(__name__)


# =================== CUSTOM EXCEPTIONS ===================


class AppError(Exception):
    """
    Exceção base da aplicação.

    Todas as exceções customizadas devem herdar desta classe.
    """

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: dict[str, Any] | None = None,
    ):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(message)


class NotFoundError(AppError):
    """Recurso não encontrado."""

    def __init__(
        self,
        resource: str,
        resource_id: str | None = None,
        message: str | None = None,
    ):
        super().__init__(
            code="NOT_FOUND",
            message=message or f"{resource} not found",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"resource": resource, "id": resource_id},
        )


class ValidationError(AppError):
    """Erro de validação."""

    def __init__(
        self,
        message: str,
        field: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            code="VALIDATION_ERROR",
            message=message,
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            details={"field": field, **(details or {})},
        )


class AuthenticationError(AppError):
    """Erro de autenticação."""

    def __init__(self, message: str = "Authentication required"):
        super().__init__(
            code="AUTHENTICATION_ERROR",
            message=message,
            status_code=status.HTTP_401_UNAUTHORIZED,
        )


class AuthorizationError(AppError):
    """Erro de autorização."""

    def __init__(self, message: str = "Permission denied"):
        super().__init__(
            code="AUTHORIZATION_ERROR",
            message=message,
            status_code=status.HTTP_403_FORBIDDEN,
        )


class ConflictError(AppError):
    """Conflito de dados."""

    def __init__(
        self,
        message: str,
        resource: str | None = None,
    ):
        super().__init__(
            code="CONFLICT",
            message=message,
            status_code=status.HTTP_409_CONFLICT,
            details={"resource": resource} if resource else None,
        )


class RateLimitError(AppError):
    """Rate limit excedido."""

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        retry_after: int | None = None,
    ):
        super().__init__(
            code="RATE_LIMIT_EXCEEDED",
            message=message,
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            details={"retry_after": retry_after} if retry_after else None,
        )


class ExternalServiceError(AppError):
    """Erro em serviço externo (OpenAI, Zotero, etc)."""

    def __init__(
        self,
        service: str,
        message: str,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            code="EXTERNAL_SERVICE_ERROR",
            message=f"{service}: {message}",
            status_code=status.HTTP_502_BAD_GATEWAY,
            details={"service": service, **(details or {})},
        )


class PDFProcessingError(AppError):
    """Erro no processamento de PDF."""

    def __init__(
        self,
        message: str,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            code="PDF_PROCESSING_ERROR",
            message=message,
            status_code=status.HTTP_400_BAD_REQUEST,
            details=details,
        )


class AIExtractionError(AppError):
    """Erro na extração com IA."""

    def __init__(
        self,
        message: str,
        model: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            code="AI_EXTRACTION_ERROR",
            message=message,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            details={"model": model, **(details or {})},
        )


# =================== ERROR RESPONSE MODEL ===================


class ErrorResponse(BaseModel):
    """Response padronizada de erro."""

    ok: bool = False
    error: dict[str, Any]
    trace_id: str | None = None


# =================== EXCEPTION HANDLERS ===================


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Handler para exceções AppError."""
    trace_id = getattr(request.state, "trace_id", None)

    logger.warning(
        "app_error",
        trace_id=trace_id,
        code=exc.code,
        message=exc.message,
        status_code=exc.status_code,
        path=str(request.url.path),
    )

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "ok": False,
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            },
            "trace_id": trace_id,
        },
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Handler para HTTPException do FastAPI."""
    trace_id = getattr(request.state, "trace_id", None)

    logger.warning(
        "http_exception",
        trace_id=trace_id,
        status_code=exc.status_code,
        detail=exc.detail,
        path=str(request.url.path),
    )

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "ok": False,
            "error": {
                "code": "HTTP_ERROR",
                "message": str(exc.detail),
            },
            "trace_id": trace_id,
        },
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handler para exceções não tratadas."""
    trace_id = getattr(request.state, "trace_id", None)

    logger.error(
        "unhandled_exception",
        trace_id=trace_id,
        error=str(exc),
        error_type=type(exc).__name__,
        path=str(request.url.path),
        exc_info=True,
    )

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "ok": False,
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred",
            },
            "trace_id": trace_id,
        },
    )


def register_exception_handlers(app: Any) -> None:
    """
    Registra todos os exception handlers na aplicação.

    Args:
        app: Instância do FastAPI.
    """
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)
