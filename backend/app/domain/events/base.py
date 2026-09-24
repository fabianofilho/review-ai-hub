"""
Base Domain Event Infrastructure.

Implementa o padrão Event Bus para desacoplamento.
"""

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TypeVar
from uuid import UUID, uuid4

import structlog

logger = structlog.get_logger()

# Type var para eventos
E = TypeVar("E", bound="DomainEvent")


@dataclass
class DomainEvent(ABC):
    """
    Base class para eventos de domínio.

    Todos os eventos devem herdar desta classe.
    """

    event_id: UUID = field(default_factory=uuid4)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    @abstractmethod
    def event_name(self) -> str:
        """Nome único do evento."""
        pass

    def to_dict(self) -> dict[str, Any]:
        """Serializa evento para dict."""
        return {
            "event_id": str(self.event_id),
            "event_name": self.event_name,
            "timestamp": self.timestamp.isoformat(),
            **self._payload(),
        }

    @abstractmethod
    def _payload(self) -> dict[str, Any]:
        """Payload específico do evento."""
        pass


# Tipo para handler de eventos
EventHandler = Callable[[DomainEvent], Any]


class EventBus:
    """
    Event Bus para dispatch de eventos de domínio.

    Implementa pub/sub simples para handlers síncronos e assíncronos.

    Usage:
        bus = EventBus()

        @bus.subscribe(ArticleAssessed)
        async def on_article_assessed(event: ArticleAssessed):
            # Handle event
            pass

        await bus.publish(ArticleAssessed(...))
    """

    _instance: "EventBus | None" = None

    def __new__(cls) -> "EventBus":
        """Singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._handlers: dict[str, list[EventHandler]] = {}
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (útil para testes)."""
        cls._instance = None

    def subscribe(self, event_type: type[E]) -> Callable[[EventHandler], EventHandler]:
        """
        Decorator para registrar handler de evento.

        Args:
            event_type: Tipo do evento a escutar.

        Returns:
            Decorator que registra o handler.
        """

        def decorator(handler: EventHandler) -> EventHandler:
            event_name = event_type.__name__

            if event_name not in self._handlers:
                self._handlers[event_name] = []

            self._handlers[event_name].append(handler)

            logger.debug(
                "event_handler_registered",
                event_name=event_name,
                handler=handler.__name__,
            )

            return handler

        return decorator

    def register(self, event_type: type[E], handler: EventHandler) -> None:
        """
        Registra handler programaticamente.

        Args:
            event_type: Tipo do evento.
            handler: Função handler.
        """
        event_name = event_type.__name__

        if event_name not in self._handlers:
            self._handlers[event_name] = []

        self._handlers[event_name].append(handler)

    async def publish(self, event: DomainEvent) -> list[Any]:
        """
        Publica evento para todos os handlers registrados.

        Args:
            event: Evento a publicar.

        Returns:
            Lista de resultados dos handlers.
        """
        event_name = event.__class__.__name__
        handlers = self._handlers.get(event_name, [])

        logger.info(
            "event_published",
            event_name=event_name,
            event_id=str(event.event_id),
            handlers_count=len(handlers),
        )

        if not handlers:
            return []

        results = []

        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    result = await handler(event)
                else:
                    result = handler(event)

                results.append(result)

                logger.debug(
                    "event_handled",
                    event_name=event_name,
                    handler=handler.__name__,
                )

            except Exception as e:
                logger.error(
                    "event_handler_error",
                    event_name=event_name,
                    handler=handler.__name__,
                    error=str(e),
                )

        return results

    def publish_sync(self, event: DomainEvent) -> None:
        """
        Publica evento de forma síncrona (para contextos sync).

        Dispara task assíncrona em background.
        """
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.publish(event))
        except RuntimeError:
            # Não há loop rodando, criar um
            asyncio.run(self.publish(event))


# Instância global do event bus
event_bus = EventBus()
