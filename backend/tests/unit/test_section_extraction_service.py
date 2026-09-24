"""
Unit tests for SectionExtractionService.

Testa funcionalidades de extração de seções:
- Construção de schemas
- Processamento de PDFs
- Extração com LLM
- Criação de sugestões
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.storage import StorageAdapter
from app.services.section_extraction_service import SectionExtractionService


@pytest.fixture
def mock_db():
    """Mock da sessão de banco."""
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def mock_storage():
    """Mock do StorageAdapter."""
    mock = MagicMock(spec=StorageAdapter)
    mock.download = AsyncMock(return_value=b"%PDF-1.4 test content")
    return mock


@pytest.fixture
def service(mock_db, mock_storage):
    """Fixture do SectionExtractionService com mocks."""
    with (
        patch("app.services.section_extraction_service.PDFProcessor") as mock_pdf,
        patch("app.services.section_extraction_service.OpenAIService") as mock_openai,
        patch("app.services.section_extraction_service.ArticleFileRepository") as mock_article_repo,
        patch(
            "app.services.section_extraction_service.ExtractionEntityTypeRepository"
        ) as mock_entity_repo,
        patch(
            "app.services.section_extraction_service.ExtractionInstanceRepository"
        ) as mock_instance_repo,
        patch(
            "app.services.section_extraction_service.AISuggestionRepository"
        ) as mock_suggestion_repo,
        patch("app.services.section_extraction_service.ExtractionRunRepository") as mock_run_repo,
    ):
        mock_pdf_instance = MagicMock()
        mock_pdf.return_value = mock_pdf_instance

        mock_openai_instance = MagicMock()
        mock_openai.return_value = mock_openai_instance

        # Mock repositories
        mock_article_repo_instance = MagicMock()
        mock_article_repo.return_value = mock_article_repo_instance

        mock_entity_repo_instance = MagicMock()
        mock_entity_repo.return_value = mock_entity_repo_instance

        mock_instance_repo_instance = MagicMock()
        mock_instance_repo.return_value = mock_instance_repo_instance

        mock_suggestion_repo_instance = MagicMock()
        mock_suggestion_repo.return_value = mock_suggestion_repo_instance

        mock_run_repo_instance = MagicMock()
        mock_run_repo.return_value = mock_run_repo_instance

        svc = SectionExtractionService(
            db=mock_db,
            user_id="12345678-1234-1234-1234-123456789012",
            storage=mock_storage,
            trace_id="trace-123",
        )
        svc.pdf_processor = mock_pdf_instance
        svc.openai_service = mock_openai_instance
        svc._article_files = mock_article_repo_instance
        svc._entity_types = mock_entity_repo_instance
        svc._instances = mock_instance_repo_instance
        svc._suggestions = mock_suggestion_repo_instance
        svc._runs = mock_run_repo_instance
        # Article ownership check: the article belongs to the project by default.
        svc._articles = MagicMock()
        svc._articles.ensure_in_project = AsyncMock()

        return svc


class TestSectionExtractionSchema:
    """Testes de construção de schemas."""

    def test_build_extraction_schema_basic(self, service):
        """Testa construção de schema básico."""
        # Entity type como objeto mock com atributo .fields
        mock_field1 = MagicMock()
        mock_field1.name = "sample_size"
        mock_field1.field_type = "integer"
        mock_field1.description = "Number of participants"
        mock_field1.is_required = True

        mock_field2 = MagicMock()
        mock_field2.name = "study_type"
        mock_field2.field_type = "string"
        mock_field2.description = "Type of study"
        mock_field2.is_required = True

        mock_field3 = MagicMock()
        mock_field3.name = "has_control_group"
        mock_field3.field_type = "boolean"
        mock_field3.description = "Whether study has control"
        mock_field3.is_required = False

        entity_type = MagicMock()
        entity_type.name = "Study Characteristics"
        entity_type.fields = [mock_field1, mock_field2, mock_field3]

        schema = service._build_extraction_schema(entity_type)

        assert schema["type"] == "object"
        assert "sample_size" in schema["properties"]
        assert schema["properties"]["sample_size"]["type"] == "number"
        assert schema["properties"]["study_type"]["type"] == "string"
        assert schema["properties"]["has_control_group"]["type"] == "boolean"
        assert "sample_size" in schema["required"]
        assert "study_type" in schema["required"]
        assert "has_control_group" not in schema["required"]

    def test_build_extraction_schema_array_type(self, service):
        """Testa schema com campos array."""
        mock_field = MagicMock()
        mock_field.name = "primary_outcomes"
        mock_field.field_type = "array"
        mock_field.description = "List of primary outcomes"
        mock_field.is_required = False

        entity_type = MagicMock()
        entity_type.name = "Outcomes"
        entity_type.fields = [mock_field]

        schema = service._build_extraction_schema(entity_type)

        assert schema["properties"]["primary_outcomes"]["type"] == "array"

    def test_build_extraction_schema_empty_fields(self, service):
        """Testa schema sem campos."""
        entity_type = MagicMock()
        entity_type.name = "Empty Entity"
        entity_type.fields = []

        schema = service._build_extraction_schema(entity_type)

        assert schema["properties"] == {}
        assert schema["required"] == []


class TestSectionExtractionPDF:
    """Testes de processamento de PDFs."""

    @pytest.mark.asyncio
    async def test_get_pdf_success(self, service, mock_storage):
        """Testa busca de PDF com sucesso."""
        article_id = uuid4()
        pdf_content = b"%PDF-1.4 test content"

        # Mock article_files repository
        mock_file = MagicMock()
        mock_file.storage_key = "project-1/article-1/paper.pdf"
        service._article_files.get_latest_pdf = AsyncMock(return_value=mock_file)

        # Mock storage adapter - note: takes (bucket, key)
        mock_storage.download = AsyncMock(return_value=pdf_content)

        result = await service._get_pdf(article_id)

        assert result == pdf_content
        service._article_files.get_latest_pdf.assert_called_once_with(article_id)
        mock_storage.download.assert_called_once_with("articles", "project-1/article-1/paper.pdf")

    @pytest.mark.asyncio
    async def test_get_pdf_not_found(self, service, mock_storage):
        """Testa erro quando PDF não encontrado."""
        article_id = uuid4()

        # Mock article_files repository returns None
        service._article_files.get_latest_pdf = AsyncMock(return_value=None)

        with pytest.raises(FileNotFoundError, match="PDF not found"):
            await service._get_pdf(article_id)


class TestSectionExtractionEntityTypes:
    """Testes de busca de entity types."""

    @pytest.mark.asyncio
    async def test_get_entity_type_success(self, service):
        """Testa busca de entity type com sucesso."""
        entity_type_id = uuid4()

        # Mock entity type com fields
        mock_field = MagicMock()
        mock_field.name = "sample_size"
        mock_field.field_type = "integer"

        mock_entity = MagicMock()
        mock_entity.id = entity_type_id
        mock_entity.name = "Study Characteristics"
        mock_entity.fields = [mock_field]

        service._entity_types.get_with_fields = AsyncMock(return_value=mock_entity)

        result = await service._get_entity_type(entity_type_id)

        # Returns the entity type object directly
        assert result.name == "Study Characteristics"
        assert len(result.fields) == 1

    @pytest.mark.asyncio
    async def test_get_entity_type_not_found(self, service):
        """Testa erro quando entity type não encontrado."""
        entity_type_id = uuid4()

        # Mock repository returns None
        service._entity_types.get_with_fields = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="Entity type not found"):
            await service._get_entity_type(entity_type_id)

    @pytest.mark.asyncio
    async def test_get_child_entity_types(self, service):
        """Test fetch of child entity types."""
        template_id = uuid4()
        parent_instance_id = uuid4()
        parent_entity_type_id = uuid4()

        # Mock parent instance
        mock_parent = MagicMock()
        mock_parent.entity_type_id = parent_entity_type_id
        service._instances.get_by_id = AsyncMock(return_value=mock_parent)

        # Mock child entity types
        mock_child1 = MagicMock()
        mock_child1.id = uuid4()
        mock_child1.name = "Section 1"

        mock_child2 = MagicMock()
        mock_child2.id = uuid4()
        mock_child2.name = "Section 2"

        service._entity_types.get_children = AsyncMock(return_value=[mock_child1, mock_child2])

        result = await service._get_child_entity_types(
            template_id=template_id,
            parent_instance_id=parent_instance_id,
        )

        assert len(result) == 2
        assert result[0].name == "Section 1"


class TestSectionExtractionLLM:
    """Testes de extração com LLM."""

    @pytest.mark.asyncio
    async def test_extract_with_llm_success(self, service):
        """Testa extração bem-sucedida com LLM."""
        # Mock OpenAI response with usage stats
        from app.services.openai_service import OpenAIResponse, OpenAIUsage

        mock_response = OpenAIResponse(
            content=json.dumps(
                {
                    "sample_size": 150,
                    "study_type": "RCT",
                    "duration_weeks": 12,
                }
            ),
            usage=OpenAIUsage(
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
            ),
            model="gpt-4o-mini",
        )

        service.openai_service.chat_completion_full = AsyncMock(return_value=mock_response)

        # Entity type mock
        entity_type = MagicMock()
        entity_type.name = "Study Characteristics"
        entity_type.description = "Basic study information"

        schema = {
            "type": "object",
            "properties": {
                "sample_size": {"type": "number"},
                "study_type": {"type": "string"},
            },
        }

        # Returns tuple (extracted_data, response)
        extracted, response = await service._extract_with_llm(
            pdf_text="Sample text from PDF...",
            entity_type=entity_type,
            schema=schema,
            model="gpt-4o-mini",
        )

        assert extracted["sample_size"] == 150
        assert extracted["study_type"] == "RCT"
        assert response.usage.total_tokens == 150


class TestSectionExtractionFullFlow:
    """Testes de fluxo completo."""

    @pytest.mark.asyncio
    async def test_extract_section_full_flow(self, service, mock_storage):
        """Testa fluxo completo de extração de seção."""
        project_id = uuid4()
        article_id = uuid4()
        template_id = uuid4()
        entity_type_id = uuid4()
        run_id = uuid4()

        # Mock _get_pdf
        pdf_content = b"%PDF-1.4 test"
        mock_storage.download = AsyncMock(return_value=pdf_content)

        # Mock article file
        mock_file = MagicMock()
        mock_file.storage_key = "test.pdf"
        service._article_files.get_latest_pdf = AsyncMock(return_value=mock_file)

        # Mock entity type
        mock_field = MagicMock()
        mock_field.name = "field_1"
        mock_field.field_type = "string"
        mock_field.description = "Test field"
        mock_field.is_required = True

        mock_entity = MagicMock()
        mock_entity.id = entity_type_id
        mock_entity.name = "Test Entity"
        mock_entity.description = "Test description"
        mock_entity.fields = [mock_field]
        service._entity_types.get_with_fields = AsyncMock(return_value=mock_entity)

        # Mock run creation
        mock_run = MagicMock()
        mock_run.id = run_id
        service._runs.create_run = AsyncMock(return_value=mock_run)
        service._runs.start_run = AsyncMock()
        service._runs.complete_run = AsyncMock()
        service._runs.fail_run = AsyncMock()

        # Mock suggestions
        service._suggestions.create = AsyncMock(return_value=MagicMock())

        # Mock instances (for _create_suggestions)
        service._instances.get_by_article = AsyncMock(return_value=[])

        # Mock PDF processor
        service.pdf_processor.extract_text = AsyncMock(return_value="Extracted text from PDF")

        # Mock OpenAI
        from app.services.openai_service import OpenAIResponse, OpenAIUsage

        mock_openai_response = OpenAIResponse(
            content=json.dumps({"field_1": "Extracted value"}),
            usage=OpenAIUsage(
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
            ),
            model="gpt-4o-mini",
        )
        service.openai_service.chat_completion_full = AsyncMock(return_value=mock_openai_response)

        # Mock SQLAlchemy model classes to avoid mapper issues
        with (
            patch(
                "app.services.section_extraction_service.ExtractionInstance"
            ) as mock_instance_class,
            patch("app.services.section_extraction_service.AISuggestion") as mock_suggestion_class,
        ):
            mock_created_instance = MagicMock()
            mock_created_instance.id = uuid4()
            mock_instance_class.return_value = mock_created_instance
            service._instances.create = AsyncMock(return_value=mock_created_instance)

            mock_suggestion = MagicMock()
            mock_suggestion.id = uuid4()
            mock_suggestion_class.return_value = mock_suggestion

            result = await service.extract_section(
                project_id=project_id,
                article_id=article_id,
                template_id=template_id,
                entity_type_id=entity_type_id,
            )

        assert result.run_id is not None
        assert result.entity_type_id == str(entity_type_id)
        assert result.tokens_total == 150
