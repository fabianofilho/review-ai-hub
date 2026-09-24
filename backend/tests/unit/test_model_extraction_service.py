"""
Unit tests for ModelExtractionService.

Tests model extraction features:
- Model identification with LLM
- Instance creation
- Child instance hierarchy
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.model_extraction_service import ModelExtractionService
from app.infrastructure.storage import StorageAdapter


@pytest.fixture
def mock_db():
    """Mock database session."""
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def mock_storage():
    """Mock StorageAdapter."""
    mock = MagicMock(spec=StorageAdapter)
    mock.download = AsyncMock(return_value=b"%PDF-1.4 test content")
    return mock


@pytest.fixture
def service(mock_db, mock_storage):
    """ModelExtractionService fixture with mocks."""
    with patch("app.services.model_extraction_service.PDFProcessor") as mock_pdf, \
         patch("app.services.model_extraction_service.OpenAIService") as mock_openai, \
         patch("app.services.model_extraction_service.ArticleFileRepository") as mock_article_repo, \
         patch("app.services.model_extraction_service.ExtractionTemplateRepository") as mock_template_repo, \
         patch("app.services.model_extraction_service.GlobalTemplateRepository") as mock_global_repo, \
         patch("app.services.model_extraction_service.ExtractionEntityTypeRepository") as mock_entity_repo, \
         patch("app.services.model_extraction_service.ExtractionInstanceRepository") as mock_instance_repo, \
         patch("app.services.model_extraction_service.ExtractionRunRepository") as mock_run_repo:
        
        mock_pdf_instance = MagicMock()
        mock_pdf.return_value = mock_pdf_instance
        
        mock_openai_instance = MagicMock()
        mock_openai.return_value = mock_openai_instance
        
        # Mock repositories
        mock_article_repo_instance = MagicMock()
        mock_article_repo.return_value = mock_article_repo_instance
        
        mock_template_repo_instance = MagicMock()
        mock_template_repo.return_value = mock_template_repo_instance
        
        mock_global_repo_instance = MagicMock()
        mock_global_repo.return_value = mock_global_repo_instance
        
        mock_entity_repo_instance = MagicMock()
        mock_entity_repo.return_value = mock_entity_repo_instance
        
        mock_instance_repo_instance = MagicMock()
        mock_instance_repo.return_value = mock_instance_repo_instance
        
        mock_run_repo_instance = MagicMock()
        mock_run_repo.return_value = mock_run_repo_instance
        
        svc = ModelExtractionService(
            db=mock_db,
            user_id="12345678-1234-1234-1234-123456789012",
            storage=mock_storage,
            trace_id="trace-123",
        )
        svc.pdf_processor = mock_pdf_instance
        svc.openai_service = mock_openai_instance
        svc._article_files = mock_article_repo_instance
        svc._templates = mock_template_repo_instance
        svc._global_templates = mock_global_repo_instance
        svc._entity_types = mock_entity_repo_instance
        svc._instances = mock_instance_repo_instance
        svc._runs = mock_run_repo_instance
        # Article ownership check: the article belongs to the project by default.
        svc._articles = MagicMock()
        svc._articles.ensure_in_project = AsyncMock()
        
        return svc


class TestModelExtractionPDF:
    """Tests for PDF fetch and download."""

    @pytest.mark.asyncio
    async def test_get_pdf_success(self, service, mock_storage):
        """Test successful PDF fetch."""
        article_id = uuid4()
        pdf_content = b"%PDF-1.4 test content"
        
        # Mock article_files repository
        mock_file = MagicMock()
        mock_file.storage_key = "test-project/article.pdf"
        service._article_files.get_latest_pdf = AsyncMock(return_value=mock_file)
        
        # Mock storage adapter - note: takes (bucket, key)
        mock_storage.download = AsyncMock(return_value=pdf_content)
        
        result = await service._get_pdf(article_id)
        
        assert result == pdf_content
        service._article_files.get_latest_pdf.assert_called_once_with(article_id)
        mock_storage.download.assert_called_once_with("articles", "test-project/article.pdf")

    @pytest.mark.asyncio
    async def test_get_pdf_not_found(self, service, mock_storage):
        """Test error when PDF not found."""
        article_id = uuid4()
        
        # Mock article_files repository returns None
        service._article_files.get_latest_pdf = AsyncMock(return_value=None)
        
        with pytest.raises(FileNotFoundError, match="PDF not found"):
            await service._get_pdf(article_id)


class TestModelExtractionTemplate:
    """Tests for template lookup."""

    @pytest.mark.asyncio
    async def test_get_template_project_template(self, service):
        """Test project template lookup."""
        template_id = uuid4()
        
        # Mock project template
        mock_entity_type = MagicMock()
        mock_entity_type.name = "prediction_models"
        
        mock_template = MagicMock()
        mock_template.id = template_id
        mock_template.name = "Project Template"
        mock_template.entity_types = [mock_entity_type]
        
        service._templates.get_with_entity_types = AsyncMock(return_value=mock_template)
        
        result = await service._get_template(template_id)
        
        # Returns template object directly
        assert result.name == "Project Template"
        service._templates.get_with_entity_types.assert_called_once_with(template_id)

    @pytest.mark.asyncio
    async def test_get_template_global_fallback(self, service):
        """Test fallback to global template."""
        template_id = uuid4()
        
        # Mock project template returns None (not found)
        service._templates.get_with_entity_types = AsyncMock(return_value=None)
        
        # Mock global template
        mock_global = MagicMock()
        mock_global.id = template_id
        mock_global.name = "Global Template"
        mock_global.entity_types = []
        
        service._global_templates.get_by_id = AsyncMock(return_value=mock_global)
        
        result = await service._get_template(template_id)
        
        assert result.name == "Global Template"

    @pytest.mark.asyncio
    async def test_get_template_not_found(self, service):
        """Test error when template not found."""
        template_id = uuid4()
        
        # Mock both repos return None
        service._templates.get_with_entity_types = AsyncMock(return_value=None)
        service._global_templates.get_by_id = AsyncMock(return_value=None)
        
        with pytest.raises(ValueError, match="Template not found"):
            await service._get_template(template_id)


class TestModelIdentification:
    """Tests for model identification."""

    @pytest.mark.asyncio
    async def test_identify_models_success(self, service):
        """Test successful model identification."""
        from app.services.openai_service import OpenAIResponse, OpenAIUsage
        
        mock_response = OpenAIResponse(
            content=json.dumps({
                "models": [
                    {
                        "model_name": "QSOFA Score",
                        "model_type": "Logistic Regression",
                        "target_outcome": "Sepsis prediction",
                    },
                    {
                        "model_name": "NEWS Score",
                        "model_type": "Point-based scoring",
                        "target_outcome": "Deterioration risk",
                    },
                ]
            }),
            usage=OpenAIUsage(
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
            ),
            model="gpt-4o-mini",
        )
        
        service.openai_service.chat_completion_full = AsyncMock(return_value=mock_response)
        
        # Mock entity type in template
        mock_entity_type = MagicMock()
        mock_entity_type.name = "prediction_models"
        
        template = MagicMock()
        template.entity_types = [mock_entity_type]
        
        # Returns tuple (models, response)
        models, response = await service._identify_models(
            pdf_text="Sample PDF text with model descriptions...",
            template=template,
            model="gpt-4o-mini",
        )
        
        assert len(models) == 2
        assert models[0]["model_name"] == "QSOFA Score"
        assert models[1]["model_type"] == "Point-based scoring"

    @pytest.mark.asyncio
    async def test_identify_models_no_models_found(self, service):
        """Test when no model is found."""
        from app.services.openai_service import OpenAIResponse, OpenAIUsage
        
        mock_response = OpenAIResponse(
            content=json.dumps({"models": []}),
            usage=OpenAIUsage(prompt_tokens=50, completion_tokens=20, total_tokens=70),
            model="gpt-4o-mini",
        )
        
        service.openai_service.chat_completion_full = AsyncMock(return_value=mock_response)
        
        template = MagicMock()
        template.entity_types = []
        
        models, response = await service._identify_models(
            pdf_text="Generic article text without models...",
            template=template,
            model="gpt-4o-mini",
        )
        
        assert models == []


class TestEntityTypeLookup:
    """Tests for entity type lookup."""

    @pytest.mark.asyncio
    async def test_get_prediction_models_entity_type_id(self, service):
        """Test entity type lookup for prediction_models."""
        template_id = uuid4()
        entity_type_id = uuid4()
        
        # Mock entity type for prediction_models
        mock_entity = MagicMock()
        mock_entity.id = entity_type_id
        
        service._entity_types.get_by_name = AsyncMock(return_value=mock_entity)
        
        result = await service._get_prediction_models_entity_type_id(template_id)
        
        # Returns str of entity_type_id
        assert result == str(entity_type_id)

    @pytest.mark.asyncio
    async def test_get_child_entity_types(self, service):
        """Test child entity types lookup."""
        template_id = uuid4()
        parent_id = str(uuid4())
        
        # Mock child entity types
        mock_child1 = MagicMock()
        mock_child1.id = uuid4()
        mock_child1.name = "predictors"
        mock_child1.label = "Predictors"
        mock_child1.cardinality = "one"
        
        mock_child2 = MagicMock()
        mock_child2.id = uuid4()
        mock_child2.name = "performance"
        mock_child2.label = "Model Performance"
        mock_child2.cardinality = "one"
        
        service._entity_types.get_children = AsyncMock(return_value=[mock_child1, mock_child2])
        
        result = await service._get_child_entity_types(parent_id, template_id)
        
        # Returns entity type objects directly, not dicts
        assert len(result) == 2
        assert result[0].name == "predictors"


class TestFullExtractionFlow:
    """Tests for full extraction flow."""

    @pytest.mark.asyncio
    async def test_extract_full_flow(self, service, mock_storage):
        """Test full model extraction flow."""
        project_id = uuid4()
        article_id = uuid4()
        template_id = uuid4()
        run_id = uuid4()
        entity_type_id = uuid4()
        
        # Mock _get_pdf
        pdf_content = b"%PDF test"
        mock_storage.download = AsyncMock(return_value=pdf_content)
        
        # Mock article file
        mock_file = MagicMock()
        mock_file.storage_key = "test.pdf"
        service._article_files.get_latest_pdf = AsyncMock(return_value=mock_file)
        
        # Mock template with entity types
        mock_entity_type = MagicMock()
        mock_entity_type.name = "prediction_models"
        
        mock_template = MagicMock()
        mock_template.id = template_id
        mock_template.name = "Test Template"
        mock_template.entity_types = [mock_entity_type]
        service._templates.get_with_entity_types = AsyncMock(return_value=mock_template)
        
        # Mock entity type lookup
        mock_entity = MagicMock()
        mock_entity.id = entity_type_id
        service._entity_types.get_by_name = AsyncMock(return_value=mock_entity)
        service._entity_types.get_children = AsyncMock(return_value=[])
        
        # Mock run creation
        mock_run = MagicMock()
        mock_run.id = run_id
        service._runs.create_run = AsyncMock(return_value=mock_run)
        service._runs.start_run = AsyncMock()
        service._runs.complete_run = AsyncMock()
        service._runs.fail_run = AsyncMock()
        
        # Mock instance creation
        mock_instance = MagicMock()
        mock_instance.id = uuid4()
        mock_instance.label = "Test Model"
        mock_instance.metadata = {}
        service._instances.create = AsyncMock(return_value=mock_instance)
        
        # Mock PDF processor
        service.pdf_processor.extract_text = AsyncMock(return_value="PDF text with models described...")
        
        # Mock OpenAI
        from app.services.openai_service import OpenAIResponse, OpenAIUsage
        mock_openai_response = OpenAIResponse(
            content=json.dumps({
                "models": [
                    {"model_name": "Extracted Model", "model_type": "LR", "target_outcome": "Outcome"}
                ]
            }),
            usage=OpenAIUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
            model="gpt-4o-mini",
        )
        service.openai_service.chat_completion_full = AsyncMock(return_value=mock_openai_response)
        
        # Mock ExtractionInstance class to avoid SQLAlchemy mapper issues
        with patch("app.services.model_extraction_service.ExtractionInstance") as mock_instance_class:
            mock_created_instance = MagicMock()
            mock_created_instance.id = uuid4()
            mock_created_instance.label = "Extracted Model"
            mock_instance_class.return_value = mock_created_instance
            
            result = await service.extract(
                project_id=project_id,
                article_id=article_id,
                template_id=template_id,
            )
        
        assert result.run_id is not None
        assert result.total_models >= 0

    @pytest.mark.asyncio
    async def test_extract_no_models_found(self, service, mock_storage):
        """Test when no model is found."""
        project_id = uuid4()
        article_id = uuid4()
        template_id = uuid4()
        run_id = uuid4()
        
        # Mock _get_pdf
        pdf_content = b"%PDF test"
        mock_storage.download = AsyncMock(return_value=pdf_content)
        
        # Mock article file
        mock_file = MagicMock()
        mock_file.storage_key = "test.pdf"
        service._article_files.get_latest_pdf = AsyncMock(return_value=mock_file)
        
        # Mock template
        mock_template = MagicMock()
        mock_template.id = template_id
        mock_template.name = "Test Template"
        mock_template.entity_types = []
        service._templates.get_with_entity_types = AsyncMock(return_value=mock_template)
        
        # Mock entity type not found
        service._entity_types.get_by_name = AsyncMock(return_value=None)
        
        # Mock run creation
        mock_run = MagicMock()
        mock_run.id = run_id
        service._runs.create_run = AsyncMock(return_value=mock_run)
        service._runs.start_run = AsyncMock()
        service._runs.complete_run = AsyncMock()
        service._runs.fail_run = AsyncMock()
        
        service.pdf_processor.extract_text = AsyncMock(return_value="Generic text")
        
        # Mock OpenAI
        from app.services.openai_service import OpenAIResponse, OpenAIUsage
        mock_openai_response = OpenAIResponse(
            content=json.dumps({"models": []}),
            usage=OpenAIUsage(prompt_tokens=50, completion_tokens=20, total_tokens=70),
            model="gpt-4o-mini",
        )
        service.openai_service.chat_completion_full = AsyncMock(return_value=mock_openai_response)
        
        result = await service.extract(
            project_id=project_id,
            article_id=article_id,
            template_id=template_id,
        )
        
        assert result.total_models == 0
        assert result.models_created == []
