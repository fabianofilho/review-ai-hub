"""
Error Handler Unit Tests.
"""

from fastapi import status

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
)


class TestAppError:
    """Testes para AppError base."""

    def test_app_error_creation(self) -> None:
        """Test criação de AppError."""
        error = AppError(
            code="TEST_ERROR",
            message="Test message",
            status_code=400,
            details={"key": "value"},
        )

        assert error.code == "TEST_ERROR"
        assert error.message == "Test message"
        assert error.status_code == 400
        assert error.details == {"key": "value"}
        assert str(error) == "Test message"

    def test_app_error_defaults(self) -> None:
        """Test valores padrão de AppError."""
        error = AppError(code="TEST", message="Test")

        assert error.status_code == status.HTTP_400_BAD_REQUEST
        assert error.details is None


class TestNotFoundError:
    """Testes para NotFoundError."""

    def test_not_found_error(self) -> None:
        """Test criação de NotFoundError."""
        error = NotFoundError(resource="Article", resource_id="123")

        assert error.code == "NOT_FOUND"
        assert error.status_code == status.HTTP_404_NOT_FOUND
        assert error.details["resource"] == "Article"
        assert error.details["id"] == "123"

    def test_not_found_with_custom_message(self) -> None:
        """Test NotFoundError com mensagem customizada."""
        error = NotFoundError(
            resource="Article",
            message="Artigo não encontrado no projeto",
        )

        assert error.message == "Artigo não encontrado no projeto"


class TestValidationError:
    """Testes para ValidationError."""

    def test_validation_error(self) -> None:
        """Test criação de ValidationError."""
        error = ValidationError(
            message="Campo inválido",
            field="email",
            details={"format": "email"},
        )

        assert error.code == "VALIDATION_ERROR"
        assert error.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert error.details["field"] == "email"
        assert error.details["format"] == "email"


class TestAuthErrors:
    """Testes para erros de autenticação/autorização."""

    def test_authentication_error(self) -> None:
        """Test AuthenticationError."""
        error = AuthenticationError()

        assert error.code == "AUTHENTICATION_ERROR"
        assert error.status_code == status.HTTP_401_UNAUTHORIZED
        assert error.message == "Authentication required"

    def test_authorization_error(self) -> None:
        """Test AuthorizationError."""
        error = AuthorizationError()

        assert error.code == "AUTHORIZATION_ERROR"
        assert error.status_code == status.HTTP_403_FORBIDDEN
        assert error.message == "Permission denied"


class TestConflictError:
    """Testes para ConflictError."""

    def test_conflict_error(self) -> None:
        """Test criação de ConflictError."""
        error = ConflictError(
            message="Artigo já existe",
            resource="Article",
        )

        assert error.code == "CONFLICT"
        assert error.status_code == status.HTTP_409_CONFLICT
        assert error.details["resource"] == "Article"


class TestRateLimitError:
    """Testes para RateLimitError."""

    def test_rate_limit_error(self) -> None:
        """Test criação de RateLimitError."""
        error = RateLimitError(retry_after=60)

        assert error.code == "RATE_LIMIT_EXCEEDED"
        assert error.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert error.details["retry_after"] == 60


class TestExternalServiceError:
    """Testes para ExternalServiceError."""

    def test_external_service_error(self) -> None:
        """Test criação de ExternalServiceError."""
        error = ExternalServiceError(
            service="OpenAI",
            message="API timeout",
            details={"timeout": 30},
        )

        assert error.code == "EXTERNAL_SERVICE_ERROR"
        assert error.status_code == status.HTTP_502_BAD_GATEWAY
        assert "OpenAI" in error.message
        assert error.details["service"] == "OpenAI"


class TestPDFProcessingError:
    """Testes para PDFProcessingError."""

    def test_pdf_processing_error(self) -> None:
        """Test criação de PDFProcessingError."""
        error = PDFProcessingError(
            message="PDF corrompido",
            details={"page": 5},
        )

        assert error.code == "PDF_PROCESSING_ERROR"
        assert error.status_code == status.HTTP_400_BAD_REQUEST


class TestAIExtractionError:
    """Testes para AIExtractionError."""

    def test_ai_extraction_error(self) -> None:
        """Test criação de AIExtractionError."""
        error = AIExtractionError(
            message="Falha na extração",
            model="gpt-4o-mini",
        )

        assert error.code == "AI_EXTRACTION_ERROR"
        assert error.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert error.details["model"] == "gpt-4o-mini"
