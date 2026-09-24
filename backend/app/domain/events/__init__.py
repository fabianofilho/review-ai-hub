"""
Domain Events.

Eventos de domínio para desacoplamento e comunicação entre componentes.
"""

from app.domain.events.assessment_events import (
    ArticleAssessed,
    AssessmentApproved,
    AssessmentRejected,
)
from app.domain.events.base import DomainEvent, EventBus
from app.domain.events.extraction_events import (
    ExtractionCompleted,
    ModelsExtracted,
    SuggestionAccepted,
)

__all__ = [
    # Base
    "DomainEvent",
    "EventBus",
    # Assessment events
    "ArticleAssessed",
    "AssessmentApproved",
    "AssessmentRejected",
    # Extraction events
    "ExtractionCompleted",
    "ModelsExtracted",
    "SuggestionAccepted",
]
