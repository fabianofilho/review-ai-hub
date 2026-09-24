"""
Assessment Domain Events.

Eventos relacionados a avaliações de artigos.
"""

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.domain.events.base import DomainEvent


@dataclass
class ArticleAssessed(DomainEvent):
    """
    Evento disparado quando um artigo é avaliado pela AI.

    Usado para:
    - Atualizar contadores de progresso
    - Notificar usuários
    - Disparar workflows automáticos
    """

    article_id: UUID = field(default_factory=lambda: UUID(int=0))
    assessment_id: UUID = field(default_factory=lambda: UUID(int=0))
    project_id: UUID = field(default_factory=lambda: UUID(int=0))
    user_id: UUID = field(default_factory=lambda: UUID(int=0))
    selected_level: str = ""
    confidence_score: float = 0.0
    processing_time_ms: int = 0
    ai_model: str = "gpt-4o-mini"

    @property
    def event_name(self) -> str:
        return "article.assessed"

    def _payload(self) -> dict[str, Any]:
        return {
            "article_id": str(self.article_id),
            "assessment_id": str(self.assessment_id),
            "project_id": str(self.project_id),
            "user_id": str(self.user_id),
            "selected_level": self.selected_level,
            "confidence_score": self.confidence_score,
            "processing_time_ms": self.processing_time_ms,
            "ai_model": self.ai_model,
        }


@dataclass
class AssessmentApproved(DomainEvent):
    """
    Evento disparado quando um assessment AI é aprovado por um revisor.

    Usado para:
    - Marcar artigo como avaliado
    - Atualizar estatísticas
    - Notificar equipe
    """

    assessment_id: UUID = field(default_factory=lambda: UUID(int=0))
    article_id: UUID = field(default_factory=lambda: UUID(int=0))
    project_id: UUID = field(default_factory=lambda: UUID(int=0))
    reviewer_id: UUID = field(default_factory=lambda: UUID(int=0))
    final_level: str = ""
    modifications_made: bool = False

    @property
    def event_name(self) -> str:
        return "assessment.approved"

    def _payload(self) -> dict[str, Any]:
        return {
            "assessment_id": str(self.assessment_id),
            "article_id": str(self.article_id),
            "project_id": str(self.project_id),
            "reviewer_id": str(self.reviewer_id),
            "final_level": self.final_level,
            "modifications_made": self.modifications_made,
        }


@dataclass
class AssessmentRejected(DomainEvent):
    """
    Evento disparado quando um assessment AI é rejeitado.

    Usado para:
    - Re-agendar avaliação
    - Notificar AI team
    - Coletar feedback
    """

    assessment_id: UUID = field(default_factory=lambda: UUID(int=0))
    article_id: UUID = field(default_factory=lambda: UUID(int=0))
    project_id: UUID = field(default_factory=lambda: UUID(int=0))
    reviewer_id: UUID = field(default_factory=lambda: UUID(int=0))
    rejection_reason: str = ""

    @property
    def event_name(self) -> str:
        return "assessment.rejected"

    def _payload(self) -> dict[str, Any]:
        return {
            "assessment_id": str(self.assessment_id),
            "article_id": str(self.article_id),
            "project_id": str(self.project_id),
            "reviewer_id": str(self.reviewer_id),
            "rejection_reason": self.rejection_reason,
        }
