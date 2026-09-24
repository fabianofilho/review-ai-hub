"""
Logging Configuration.

Configura logging estruturado usando structlog para:
- Logs JSON em produção
- Logs coloridos em desenvolvimento
- Contexto automático (trace_id, user_id, etc.)
"""

import logging
import sys
from typing import Any

import structlog
from structlog.types import Processor

from app.core.config import settings


def configure_logging() -> None:
    """
    Configura logging estruturado para a aplicação.

    Em DEBUG: Logs coloridos e formatados para console.
    Em produção: Logs JSON para parsing automatizado.
    """
    # Processadores compartilhados
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if settings.DEBUG:
        # Desenvolvimento: Logs coloridos
        processors: list[Processor] = [
            *shared_processors,
            structlog.dev.ConsoleRenderer(colors=True),
        ]
    else:
        # Produção: Logs JSON
        processors = [
            *shared_processors,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configurar logging stdlib
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.DEBUG if settings.DEBUG else logging.INFO,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """
    Retorna logger configurado.

    Args:
        name: Nome do módulo/componente.

    Returns:
        Logger estruturado.
    """
    return structlog.stdlib.get_logger(name)


class LoggerMixin:
    """
    Mixin que adiciona logger a classes.

    Exemplo:
        class MyService(LoggerMixin):
            def do_something(self):
                self.logger.info("doing something", extra_data="value")
    """

    @property
    def logger(self) -> structlog.stdlib.BoundLogger:
        """Logger com nome da classe."""
        return get_logger(self.__class__.__name__)


def log_context(**kwargs: Any) -> None:
    """
    Adiciona contexto ao logger para a request atual.

    Args:
        **kwargs: Chave-valor para adicionar ao contexto.
    """
    structlog.contextvars.bind_contextvars(**kwargs)


def clear_log_context() -> None:
    """Limpa contexto de log da request atual."""
    structlog.contextvars.clear_contextvars()
