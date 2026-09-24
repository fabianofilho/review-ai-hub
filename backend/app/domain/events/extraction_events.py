"""
Extraction Domain Events.

Eventos relacionados a extração de dados.
"""

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.domain.events.base import DomainEvent


@dataclass
class ExtractionCompleted(DomainEvent):
    """
    Evento disparado quando uma extração de seção é completada.

    Usado para:
    - Atualizar progresso
    - Notificar usuários
    - Disparar próximas extrações
    """

    article_id: UUID = field(default_factory=lambda: UUID(int=0))
    run_id: str = ""
    entity_type_id: UUID = field(default_factory=lambda: UUID(int=0))
    project_id: UUID = field(default_factory=lambda: UUID(int=0))
    suggestions_created: int = 0
    duration_ms: int = 0

    @property
    def event_name(self) -> str:
        return "extraction.completed"

    def _payload(self) -> dict[str, Any]:
        return {
            "article_id": str(self.article_id),
            "run_id": self.run_id,
            "entity_type_id": str(self.entity_type_id),
            "project_id": str(self.project_id),
            "suggestions_created": self.suggestions_created,
            "duration_ms": self.duration_ms,
        }


@dataclass
class ModelsExtracted(DomainEvent):
    """
    Evento disparado quando modelos de predição são extraídos.

    Usado para:
    - Atualizar contagem de modelos
    - Disparar extração de seções filhas
    - Notificar usuários
    """

    article_id: UUID = field(default_factory=lambda: UUID(int=0))
    run_id: str = ""
    project_id: UUID = field(default_factory=lambda: UUID(int=0))
    models_count: int = 0
    child_instances_count: int = 0
    model_names: list[str] = field(default_factory=list)
    duration_ms: int = 0

    @property
    def event_name(self) -> str:
        return "models.extracted"

    def _payload(self) -> dict[str, Any]:
        return {
            "article_id": str(self.article_id),
            "run_id": self.run_id,
            "project_id": str(self.project_id),
            "models_count": self.models_count,
            "child_instances_count": self.child_instances_count,
            "model_names": self.model_names,
            "duration_ms": self.duration_ms,
        }


@dataclass
class SuggestionAccepted(DomainEvent):
    """
    Evento disparado quando uma sugestão AI é aceita.

    Usado para:
    - Atualizar valor extraído
    - Coletar feedback para melhorar AI
    - Atualizar estatísticas de acurácia
    """

    suggestion_id: UUID = field(default_factory=lambda: UUID(int=0))
    instance_id: UUID = field(default_factory=lambda: UUID(int=0))
    article_id: UUID = field(default_factory=lambda: UUID(int=0))
    project_id: UUID = field(default_factory=lambda: UUID(int=0))
    reviewer_id: UUID = field(default_factory=lambda: UUID(int=0))
    field_name: str = ""
    original_value: str = ""
    final_value: str = ""
    was_modified: bool = False

    @property
    def event_name(self) -> str:
        return "suggestion.accepted"

    def _payload(self) -> dict[str, Any]:
        return {
            "suggestion_id": str(self.suggestion_id),
            "instance_id": str(self.instance_id),
            "article_id": str(self.article_id),
            "project_id": str(self.project_id),
            "reviewer_id": str(self.reviewer_id),
            "field_name": self.field_name,
            "original_value": self.original_value,
            "final_value": self.final_value,
            "was_modified": self.was_modified,
        }
