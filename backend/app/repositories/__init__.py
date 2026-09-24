"""
Repository Layer.

Implements the Repository pattern to abstract data access.
Facilitates testing, maintenance and query migration.
"""

from app.repositories.article_repository import ArticleFileRepository, ArticleRepository
from app.repositories.assessment_repository import (
    AIAssessmentConfigRepository,
    AIAssessmentPromptRepository,
    AIAssessmentRepository,
    AIAssessmentRunRepository,
    AssessmentEvidenceRepository,
    AssessmentInstanceRepository,
    AssessmentInstrumentRepository,
    AssessmentItemRepository,
    AssessmentResponseRepository,
    ProjectAssessmentItemRepository,
)
from app.repositories.base import BaseRepository
from app.repositories.extraction_repository import (
    AISuggestionRepository,
    ExtractionEntityTypeRepository,
    ExtractionInstanceRepository,
    ExtractionTemplateRepository,
    GlobalTemplateRepository,
)
from app.repositories.extraction_run_repository import ExtractionRunRepository
from app.repositories.integration_repository import ZoteroIntegrationRepository
from app.repositories.project_repository import ProjectMemberRepository, ProjectRepository
from app.repositories.unit_of_work import UnitOfWork
from app.repositories.user_api_key_repository import UserAPIKeyRepository

__all__ = [
    # Base
    "BaseRepository",
    "UnitOfWork",
    # Article
    "ArticleRepository",
    "ArticleFileRepository",
    # Project
    "ProjectRepository",
    "ProjectMemberRepository",
    # Assessment (new structure)
    "AssessmentInstanceRepository",
    "AssessmentResponseRepository",
    "AssessmentEvidenceRepository",
    "AssessmentInstrumentRepository",
    "AssessmentItemRepository",
    "ProjectAssessmentItemRepository",
    "AIAssessmentRepository",
    "AIAssessmentRunRepository",
    "AIAssessmentConfigRepository",
    "AIAssessmentPromptRepository",
    # Extraction
    "ExtractionTemplateRepository",
    "GlobalTemplateRepository",
    "ExtractionEntityTypeRepository",
    "ExtractionInstanceRepository",
    "AISuggestionRepository",
    "ExtractionRunRepository",
    # Integration
    "ZoteroIntegrationRepository",
    # User API Keys
    "UserAPIKeyRepository",
]
