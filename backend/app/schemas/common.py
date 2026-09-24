"""
Common Schemas.

Schemas compartilhados usados em toda a API.
Mantém padrão de resposta consistente com Edge Functions anteriores.
"""

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorDetail(BaseModel):
    """Detalhes de erro padronizado."""

    code: str = Field(..., description="Código do erro")
    message: str = Field(..., description="Mensagem do erro")
    details: dict[str, Any] | None = Field(
        default=None,
        description="Detalhes adicionais do erro",
    )


class ApiResponse(BaseModel, Generic[T]):
    """
    Response padronizado da API.

    Mantém compatibilidade com formato usado nas Edge Functions:
    { ok: boolean, data?: T, error?: { code, message } }
    """

    ok: bool = Field(..., description="Indica se a operação foi bem-sucedida")
    data: T | None = Field(default=None, description="Dados da resposta")
    error: ErrorDetail | None = Field(default=None, description="Detalhes do erro")
    trace_id: str | None = Field(default=None, description="ID de rastreamento")

    @classmethod
    def success(cls, data: T, trace_id: str | None = None) -> "ApiResponse[T]":
        """Cria resposta de sucesso."""
        return cls(ok=True, data=data, trace_id=trace_id)

    @classmethod
    def failure(
        cls,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> "ApiResponse[T]":
        """Cria resposta de erro."""
        return cls(
            ok=False,
            error=ErrorDetail(code=code, message=message, details=details),
            trace_id=trace_id,
        )


class PaginatedResponse(BaseModel, Generic[T]):
    """Response paginada para listagens."""

    items: list[T] = Field(..., description="Lista de itens")
    total: int = Field(..., description="Total de itens disponíveis")
    page: int = Field(..., description="Página atual")
    page_size: int = Field(..., description="Tamanho da página")
    has_more: bool = Field(..., description="Indica se há mais páginas")

    @property
    def total_pages(self) -> int:
        """Calcula total de páginas."""
        return (self.total + self.page_size - 1) // self.page_size


class HealthResponse(BaseModel):
    """Response do health check."""

    status: str = Field(default="healthy")
    version: str = Field(default="0.1.0")
