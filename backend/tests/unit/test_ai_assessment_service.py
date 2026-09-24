"""
Unit tests for AIAssessmentService.

Tests refactored service with:
- Run tracking lifecycle
- AI Suggestion workflow
- BYOK support
- Memory context in batch
- PDF optimization
"""

import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.storage import StorageAdapter
from app.services.ai_assessment_service import AIAssessmentService


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
    """Fixture do AIAssessmentService com mocks (Phase 2 refactored)."""
    with (
        patch("app.services.ai_assessment_service.ArticleRepository") as mock_article_repo,
        patch("app.services.ai_assessment_service.ArticleFileRepository") as mock_file_repo,
        patch("app.services.ai_assessment_service.ProjectRepository") as mock_project_repo,
        patch("app.services.ai_assessment_service.AssessmentItemRepository") as mock_item_repo,
        patch("app.services.ai_assessment_service.AIAssessmentRunRepository") as mock_run_repo,
        patch(
            "app.services.ai_assessment_service.AIAssessmentConfigRepository"
        ) as mock_config_repo,
        patch(
            "app.services.ai_assessment_service.AIAssessmentPromptRepository"
        ) as mock_prompt_repo,
        patch("app.services.ai_assessment_service.AISuggestionRepository") as mock_suggestion_repo,
    ):
        # Mock repositories (Phase 2 includes new repos)
        mock_article_repo_instance = MagicMock()
        mock_article_repo.return_value = mock_article_repo_instance

        mock_file_repo_instance = MagicMock()
        mock_file_repo.return_value = mock_file_repo_instance

        mock_project_repo_instance = MagicMock()
        mock_project_repo.return_value = mock_project_repo_instance

        mock_item_repo_instance = MagicMock()
        mock_item_repo.return_value = mock_item_repo_instance

        mock_run_repo_instance = MagicMock()
        mock_run_repo.return_value = mock_run_repo_instance

        mock_config_repo_instance = MagicMock()
        mock_config_repo.return_value = mock_config_repo_instance

        mock_prompt_repo_instance = MagicMock()
        mock_prompt_repo.return_value = mock_prompt_repo_instance

        mock_suggestion_repo_instance = MagicMock()
        mock_suggestion_repo.return_value = mock_suggestion_repo_instance

        svc = AIAssessmentService(
            db=mock_db,
            user_id="12345678-1234-1234-1234-123456789012",
            storage=mock_storage,
            trace_id="trace-123",
            openai_api_key="test-api-key",  # BYOK
        )
        svc._articles = mock_article_repo_instance
        svc._article_files = mock_file_repo_instance
        svc._projects = mock_project_repo_instance
        svc._assessment_items = mock_item_repo_instance
        svc._runs = mock_run_repo_instance
        svc._configs = mock_config_repo_instance
        svc._prompts = mock_prompt_repo_instance
        svc._suggestions = mock_suggestion_repo_instance

        return svc


class TestAIAssessmentServicePrompt:
    """Testes de construção de prompts."""

    def test_build_user_prompt_basic(self, service):
        """Testa construção do prompt de usuário básico."""
        item = MagicMock()
        item.question = "Is the study design clearly described?"
        item.guidance = "Look for explicit methodology section"
        item.allowed_levels = ["Yes", "Partially", "No", "Unclear"]

        project_summary = {
            "review_title": "Systematic Review of Treatment X",
            "condition_studied": "Type 2 Diabetes",
        }

        prompt = service._build_user_prompt(
            item, project_summary, ["Yes", "Partially", "No"], memory_context=None
        )

        assert "study design" in prompt.lower() or "Is the study design" in prompt
        assert "Yes" in prompt or "yes" in prompt.lower()
        assert "methodology" in prompt.lower()

    def test_build_user_prompt_with_memory_context(self, service):
        """Testa prompt com contexto de memória (batch)."""
        item = MagicMock()
        item.question = "Is randomization adequate?"
        item.guidance = None
        item.allowed_levels = ["Yes", "No"]

        project_summary = {"review_title": "Test Review"}

        memory_context = [
            {
                "item_code": "D1.1",
                "question": "Previous question?",
                "selected_level": "Low",
                "justification": "Clear evidence in methods section...",
            },
            {
                "item_code": "D1.2",
                "question": "Another question?",
                "selected_level": "High",
                "justification": "No information provided about...",
            },
        ]

        prompt = service._build_user_prompt(
            item, project_summary, ["Yes", "No"], memory_context=memory_context
        )

        # Should include previous assessments
        assert "Previous assessments" in prompt or "previous" in prompt.lower()
        assert "D1.1" in prompt
        assert "Low" in prompt

    def test_build_response_schema(self, service):
        """Testa construção do schema de resposta."""
        allowed_levels = ["High", "Medium", "Low"]

        schema = service._build_response_schema(allowed_levels)

        assert schema["type"] == "json_schema"
        assert "selected_level" in schema["json_schema"]["schema"]["properties"]

    def test_build_response_schema_empty_levels(self, service):
        """Testa schema com níveis vazios."""
        schema = service._build_response_schema([])

        assert schema["type"] == "json_schema"
        assert "selected_level" in schema["json_schema"]["schema"]["properties"]


class TestAIAssessmentServicePDF:
    """Testes de preparação de PDFs."""

    @pytest.mark.asyncio
    async def test_prepare_pdf_with_file_id(self, service):
        """Testa preparação com file_id existente."""
        result, size = await service._prepare_pdf_file(
            pdf_file_id="file-abc123",
            pdf_base64=None,
            pdf_filename=None,
            storage_key=None,
        )

        assert result["type"] == "input_file"
        assert result["file_id"] == "file-abc123"
        assert size is None

    @pytest.mark.asyncio
    async def test_prepare_pdf_with_base64(self, service):
        """Testa preparação com base64."""
        pdf_content = b"%PDF-1.4 test content"
        pdf_base64 = base64.b64encode(pdf_content).decode()

        result, size = await service._prepare_pdf_file(
            pdf_file_id=None,
            pdf_base64=pdf_base64,
            pdf_filename="test.pdf",
            storage_key=None,
        )

        assert result["type"] == "input_file"
        assert result["filename"] == "test.pdf"
        assert "data:application/pdf;base64," in result["file_data"]
        assert size == len(pdf_content)

    @pytest.mark.asyncio
    async def test_prepare_pdf_with_storage_key(self, service, mock_storage):
        """Testa preparação com storage_key."""
        pdf_content = b"%PDF-1.4 stored content"

        mock_storage.download = AsyncMock(return_value=pdf_content)

        result, size = await service._prepare_pdf_file(
            pdf_file_id=None,
            pdf_base64=None,
            pdf_filename=None,
            storage_key="project-123/article-456/paper.pdf",
        )

        assert result["type"] == "input_file"
        assert result["filename"] == "paper.pdf"
        assert size == len(pdf_content)
        mock_storage.download.assert_called_once_with(
            "articles", "project-123/article-456/paper.pdf"
        )

    @pytest.mark.asyncio
    async def test_prepare_pdf_no_source(self, service):
        """Testa erro quando nenhuma fonte fornecida."""
        with pytest.raises(ValueError, match="No PDF source"):
            await service._prepare_pdf_file(
                pdf_file_id=None,
                pdf_base64=None,
                pdf_filename=None,
                storage_key=None,
            )


class TestAIAssessmentServiceAPI:
    """Testes de chamadas à API OpenAI."""

    @pytest.mark.asyncio
    async def test_call_direct_success(self, service):
        """Testa chamada direta bem-sucedida."""
        input_file_node = {
            "type": "input_file",
            "file_data": "data:application/pdf;base64,xxx",
            "filename": "test.pdf",
        }

        mock_response_data = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(
                                {
                                    "selected_level": "High",
                                    "confidence_score": 0.9,
                                    "justification": "Clear methodology",
                                    "evidence_passages": [{"text": "We used...", "page_number": 3}],
                                }
                            ),
                        }
                    ],
                }
            ],
            "usage": {"input_tokens": 1000, "output_tokens": 200},
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.is_success = True
            mock_response.json.return_value = mock_response_data

            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await service._call_direct(
                input_file_node=input_file_node,
                system_prompt="You are an expert...",
                user_prompt="Assess this article...",
                response_format={"type": "json_schema", "json_schema": {}},
                model="gpt-4o-mini",
            )

        assert result["output_text"] is not None
        output = json.loads(result["output_text"])
        assert output["selected_level"] == "High"
        assert result["input_tokens"] == 1000
        assert result["output_tokens"] == 200

    @pytest.mark.asyncio
    async def test_call_direct_uses_byok(self, service):
        """Testa que BYOK é usado na chamada."""
        input_file_node = {"type": "input_file", "file_id": "xxx"}

        mock_response_data = {
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "{}"}]}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.is_success = True
            mock_response.json.return_value = mock_response_data

            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await service._call_direct(
                input_file_node=input_file_node,
                system_prompt="Test",
                user_prompt="Test",
                response_format={},
                model="gpt-4o-mini",
            )

            # Verify BYOK key is in Authorization header
            call_kwargs = mock_post.call_args[1]
            assert "headers" in call_kwargs
            assert call_kwargs["headers"]["Authorization"] == "Bearer test-api-key"

    @pytest.mark.asyncio
    async def test_call_direct_api_error(self, service):
        """Testa erro na API OpenAI."""
        input_file_node = {"type": "input_file", "file_id": "xxx"}

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.is_success = False
            mock_response.status_code = 429
            mock_response.text = "Rate limit exceeded"

            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            with pytest.raises(ValueError, match="OpenAI error: 429"):
                await service._call_direct(
                    input_file_node=input_file_node,
                    system_prompt="Test",
                    user_prompt="Test",
                    response_format={},
                    model="gpt-4o-mini",
                )


class TestAIAssessmentServiceAssess:
    """Testes do método assess() refatorado (Phase 2)."""

    @pytest.mark.asyncio
    async def test_assess_creates_run_lifecycle(self, service):
        """Testa que assess() cria e gerencia run lifecycle."""
        project_id = uuid4()
        article_id = uuid4()
        item_id = uuid4()
        instrument_id = uuid4()
        run_id = uuid4()
        suggestion_id = uuid4()

        # Mock run
        mock_run = MagicMock()
        mock_run.id = run_id
        service._runs.create_run = AsyncMock(return_value=mock_run)
        service._runs.start_run = AsyncMock()
        service._runs.complete_run = AsyncMock()

        # Mock assessment_item
        mock_item = MagicMock()
        mock_item.id = item_id
        mock_item.question = "Test question?"
        mock_item.allowed_levels = ["Yes", "No"]
        service._assessment_items.get_by_id = AsyncMock(return_value=mock_item)

        # Mock article
        mock_article = MagicMock()
        mock_article.id = article_id
        service._articles.get_by_id = AsyncMock(return_value=mock_article)

        # Mock project summary
        project_summary = {"review_title": "Test Review"}
        service._projects.get_summary = AsyncMock(return_value=project_summary)

        # Mock article file
        mock_file = MagicMock()
        mock_file.storage_key = "test/paper.pdf"
        service._article_files.get_latest_pdf = AsyncMock(return_value=mock_file)

        # Mock suggestion creation
        mock_suggestion = MagicMock()
        mock_suggestion.id = suggestion_id
        service._suggestions.create = AsyncMock(return_value=mock_suggestion)

        # PDF em base64
        pdf_content = b"%PDF-1.4 test"
        pdf_base64 = base64.b64encode(pdf_content).decode()

        ai_response = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(
                                {
                                    "selected_level": "Yes",
                                    "confidence_score": 0.85,
                                    "justification": "Clearly stated",
                                    "evidence_passages": [],
                                }
                            ),
                        }
                    ],
                }
            ],
            "usage": {"input_tokens": 500, "output_tokens": 100},
        }

        with (
            patch("httpx.AsyncClient") as mock_client,
            patch("app.services.ai_assessment_service.AISuggestion") as mock_suggestion_class,
        ):
            mock_response = MagicMock()
            mock_response.is_success = True
            mock_response.json.return_value = ai_response

            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            mock_suggestion_instance = MagicMock()
            mock_suggestion_class.return_value = mock_suggestion_instance

            result = await service.assess(
                project_id=project_id,
                article_id=article_id,
                assessment_item_id=item_id,
                instrument_id=instrument_id,
                pdf_base64=pdf_base64,
                pdf_filename="test.pdf",
            )

        # Verify run lifecycle
        service._runs.create_run.assert_called_once()
        service._runs.start_run.assert_called_once_with(run_id)
        service._runs.complete_run.assert_called_once()

        # Verify suggestion created (not final assessment)
        service._suggestions.create.assert_called_once()

        # Verify result contains suggestion_id
        assert result.assessment_id == str(suggestion_id)

    @pytest.mark.asyncio
    async def test_assess_fails_run_on_error(self, service):
        """Testa que assess() marca run como failed em caso de erro."""
        project_id = uuid4()
        article_id = uuid4()
        item_id = uuid4()
        instrument_id = uuid4()
        run_id = uuid4()

        # Mock run
        mock_run = MagicMock()
        mock_run.id = run_id
        service._runs.create_run = AsyncMock(return_value=mock_run)
        service._runs.start_run = AsyncMock()
        service._runs.fail_run = AsyncMock()

        # Mock article NOT FOUND to trigger error
        service._assessment_items.get_by_id = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="Assessment item not found"):
            await service.assess(
                project_id=project_id,
                article_id=article_id,
                assessment_item_id=item_id,
                instrument_id=instrument_id,
                pdf_base64="xxx",
            )

        # Verify run was failed
        service._runs.fail_run.assert_called_once_with(
            run_id, "Assessment item not found: " + str(item_id)
        )

    @pytest.mark.asyncio
    async def test_assess_with_extraction_instance_id(self, service):
        """Testa assess() com extraction_instance_id para PROBAST por modelo."""
        project_id = uuid4()
        article_id = uuid4()
        item_id = uuid4()
        instrument_id = uuid4()
        extraction_instance_id = uuid4()
        run_id = uuid4()

        # Mock run
        mock_run = MagicMock()
        mock_run.id = run_id
        service._runs.create_run = AsyncMock(return_value=mock_run)
        service._runs.start_run = AsyncMock()
        service._runs.complete_run = AsyncMock()

        # Setup mocks...
        mock_item = MagicMock()
        mock_item.question = "Test"
        mock_item.allowed_levels = []
        service._assessment_items.get_by_id = AsyncMock(return_value=mock_item)

        mock_article = MagicMock()
        service._articles.get_by_id = AsyncMock(return_value=mock_article)

        service._projects.get_summary = AsyncMock(return_value={})

        mock_file = MagicMock()
        mock_file.storage_key = "test.pdf"
        service._article_files.get_latest_pdf = AsyncMock(return_value=mock_file)

        mock_suggestion = MagicMock()
        mock_suggestion.id = uuid4()
        service._suggestions.create = AsyncMock(return_value=mock_suggestion)

        ai_response = {
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "{}"}]}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }

        with (
            patch("httpx.AsyncClient") as mock_client,
            patch("app.services.ai_assessment_service.AISuggestion"),
        ):
            mock_response = MagicMock()
            mock_response.is_success = True
            mock_response.json.return_value = ai_response
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            await service.assess(
                project_id=project_id,
                article_id=article_id,
                assessment_item_id=item_id,
                instrument_id=instrument_id,
                extraction_instance_id=extraction_instance_id,
                pdf_base64="xxx",
            )

        # Verify extraction_instance_id passed to create_run
        call_kwargs = service._runs.create_run.call_args[1]
        assert call_kwargs["extraction_instance_id"] == extraction_instance_id


class TestAIAssessmentServiceAssessBatch:
    """Testes do método assess_batch() refatorado (Phase 2)."""

    @pytest.mark.asyncio
    async def test_assess_batch_downloads_pdf_once(self, service, mock_storage):
        """Testa que assess_batch() baixa PDF uma única vez."""
        project_id = uuid4()
        article_id = uuid4()
        instrument_id = uuid4()
        item_ids = [uuid4(), uuid4(), uuid4()]
        run_id = uuid4()

        # Mock run
        mock_run = MagicMock()
        mock_run.id = run_id
        service._runs.create_run = AsyncMock(return_value=mock_run)
        service._runs.start_run = AsyncMock()
        service._runs.complete_run = AsyncMock()

        # Mock article
        mock_article = MagicMock()
        service._articles.get_by_id = AsyncMock(return_value=mock_article)

        # Mock article file
        mock_file = MagicMock()
        mock_file.storage_key = "test/paper.pdf"
        service._article_files.get_main_file = AsyncMock(return_value=mock_file)

        # Mock PDF download
        pdf_content = b"%PDF-1.4 test content"
        mock_storage.download = AsyncMock(return_value=pdf_content)

        # Mock items
        for item_id in item_ids:
            mock_item = MagicMock()
            mock_item.question = "Test"
            mock_item.allowed_levels = []
            mock_item.item_code = f"D{item_ids.index(item_id) + 1}.1"
            service._assessment_items.get_by_id = AsyncMock(return_value=mock_item)

        # Mock suggestions
        service._suggestions.create = AsyncMock(
            side_effect=[MagicMock(id=uuid4()) for _ in item_ids]
        )

        ai_response = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": '{"selected_level": "Yes", "confidence_score": 0.8, "justification": "Test", "evidence_passages": []}',
                        }
                    ],
                }
            ],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }

        with (
            patch("httpx.AsyncClient") as mock_client,
            patch("app.services.ai_assessment_service.AISuggestion"),
        ):
            mock_response = MagicMock()
            mock_response.is_success = True
            mock_response.json.return_value = ai_response
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            results = await service.assess_batch(
                project_id=project_id,
                article_id=article_id,
                item_ids=item_ids,
                instrument_id=instrument_id,
            )

        # PDF should be downloaded exactly once
        assert mock_storage.download.call_count == 1
        mock_storage.download.assert_called_with("articles", "test/paper.pdf")

        # All items should be processed
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_assess_batch_builds_memory_context(self, service, mock_storage):
        """Testa que assess_batch() constrói contexto de memória."""
        project_id = uuid4()
        article_id = uuid4()
        instrument_id = uuid4()
        item_ids = [uuid4(), uuid4()]

        # Setup mocks
        mock_run = MagicMock()
        mock_run.id = uuid4()
        service._runs.create_run = AsyncMock(return_value=mock_run)
        service._runs.start_run = AsyncMock()
        service._runs.complete_run = AsyncMock()

        mock_article = MagicMock()
        service._articles.get_by_id = AsyncMock(return_value=mock_article)

        mock_file = MagicMock()
        mock_file.storage_key = "test.pdf"
        service._article_files.get_main_file = AsyncMock(return_value=mock_file)

        mock_storage.download = AsyncMock(return_value=b"%PDF-1.4 test")

        # Mock items with different codes
        items_data = [
            {"id": item_ids[0], "code": "D1.1", "question": "Q1"},
            {"id": item_ids[1], "code": "D1.2", "question": "Q2"},
        ]

        async def get_item_by_id(item_id):
            for item_data in items_data:
                if item_data["id"] == item_id:
                    mock_item = MagicMock()
                    mock_item.id = item_data["id"]
                    mock_item.item_code = item_data["code"]
                    mock_item.question = item_data["question"]
                    mock_item.allowed_levels = []
                    return mock_item
            return None

        service._assessment_items.get_by_id = get_item_by_id

        service._suggestions.create = AsyncMock(
            side_effect=[MagicMock(id=uuid4()) for _ in item_ids]
        )

        user_prompts_called = []

        # Capture user prompts to verify memory context
        original_build_user_prompt = service._build_user_prompt

        def capture_user_prompt(item, project, levels, memory_context=None):
            user_prompts_called.append(
                {
                    "item_code": item.item_code,
                    "memory_context": memory_context,
                }
            )
            return original_build_user_prompt(item, project, levels, memory_context)

        service._build_user_prompt = capture_user_prompt

        ai_response = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": '{"selected_level": "Yes", "confidence_score": 0.8, "justification": "Test justification", "evidence_passages": []}',
                        }
                    ],
                }
            ],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }

        with (
            patch("httpx.AsyncClient") as mock_client,
            patch("app.services.ai_assessment_service.AISuggestion"),
        ):
            mock_response = MagicMock()
            mock_response.is_success = True
            mock_response.json.return_value = ai_response
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            await service.assess_batch(
                project_id=project_id,
                article_id=article_id,
                item_ids=item_ids,
                instrument_id=instrument_id,
            )

        # First item should have NO memory context
        assert user_prompts_called[0]["memory_context"] == []

        # Second item should have memory context from first item
        assert len(user_prompts_called[1]["memory_context"]) == 1
        assert user_prompts_called[1]["memory_context"][0]["item_code"] == "D1.1"


class TestAIAssessmentServiceEdgeCases:
    """Testes de casos de borda."""

    def test_parse_allowed_levels_as_string(self, service):
        """Testa quando allowed_levels vem como string JSON."""
        result = service._parse_allowed_levels('["Yes", "No", "NA"]')
        assert result == ["Yes", "No", "NA"]

    def test_parse_allowed_levels_as_list(self, service):
        """Testa quando allowed_levels já é lista."""
        result = service._parse_allowed_levels(["Yes", "No"])
        assert result == ["Yes", "No"]

    def test_parse_allowed_levels_empty(self, service):
        """Testa quando allowed_levels é vazio."""
        result = service._parse_allowed_levels(None)
        assert result == []

    def test_byok_initialization(self, mock_db, mock_storage):
        """Testa inicialização com BYOK."""
        custom_key = "sk-custom-key-123"

        with (
            patch("app.services.ai_assessment_service.ArticleRepository"),
            patch("app.services.ai_assessment_service.ArticleFileRepository"),
            patch("app.services.ai_assessment_service.ProjectRepository"),
            patch("app.services.ai_assessment_service.AssessmentItemRepository"),
            patch("app.services.ai_assessment_service.AIAssessmentRunRepository"),
            patch("app.services.ai_assessment_service.AIAssessmentConfigRepository"),
            patch("app.services.ai_assessment_service.AIAssessmentPromptRepository"),
            patch("app.services.ai_assessment_service.AISuggestionRepository"),
        ):
            service = AIAssessmentService(
                db=mock_db,
                user_id="test-user",
                storage=mock_storage,
                trace_id="trace-123",
                openai_api_key=custom_key,
            )

            assert service.openai_api_key == custom_key

    def test_byok_defaults_to_settings(self, mock_db, mock_storage):
        """Testa que BYOK usa settings quando não fornecido."""
        with (
            patch("app.services.ai_assessment_service.settings") as mock_settings,
            patch("app.services.ai_assessment_service.ArticleRepository"),
            patch("app.services.ai_assessment_service.ArticleFileRepository"),
            patch("app.services.ai_assessment_service.ProjectRepository"),
            patch("app.services.ai_assessment_service.AssessmentItemRepository"),
            patch("app.services.ai_assessment_service.AIAssessmentRunRepository"),
            patch("app.services.ai_assessment_service.AIAssessmentConfigRepository"),
            patch("app.services.ai_assessment_service.AIAssessmentPromptRepository"),
            patch("app.services.ai_assessment_service.AISuggestionRepository"),
        ):
            mock_settings.OPENAI_API_KEY = "sk-default-key"

            service = AIAssessmentService(
                db=mock_db,
                user_id="test-user",
                storage=mock_storage,
                trace_id="trace-123",
                openai_api_key=None,
            )

            assert service.openai_api_key == "sk-default-key"
