"""
OpenAI Service Unit Tests.

Usa mocks para não fazer chamadas reais à API.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from app.services.openai_service import OpenAIResponse, OpenAIService, OpenAIUsage


class MockResponseModel(BaseModel):
    """Modelo de resposta para testes."""

    answer: str
    confidence: float


@pytest.fixture
def openai_service() -> OpenAIService:
    """Fixture para instância do OpenAIService."""
    return OpenAIService(trace_id="test-trace-id")


@pytest.fixture
def mock_successful_response() -> dict:
    """Mock de resposta bem-sucedida da OpenAI."""
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": "gpt-4o-mini",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": '{"answer": "Test answer", "confidence": 0.95}',
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        },
    }


class TestOpenAIService:
    """Testes para OpenAIService."""

    @pytest.mark.asyncio
    async def test_chat_completion_returns_string(
        self,
        openai_service: OpenAIService,
        mock_successful_response: dict,
    ) -> None:
        """Test que chat_completion retorna string."""
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = mock_successful_response

        with patch.object(openai_service, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_get_client.return_value = mock_client

            result = await openai_service.chat_completion(
                messages=[{"role": "user", "content": "Hello"}],
                model="gpt-4o-mini",
            )

            assert isinstance(result, str)
            assert "answer" in result

    @pytest.mark.asyncio
    async def test_chat_completion_full_returns_response_object(
        self,
        openai_service: OpenAIService,
        mock_successful_response: dict,
    ) -> None:
        """Test que chat_completion_full retorna OpenAIResponse."""
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = mock_successful_response

        with patch.object(openai_service, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_get_client.return_value = mock_client

            result = await openai_service.chat_completion_full(
                messages=[{"role": "user", "content": "Hello"}],
            )

            assert isinstance(result, OpenAIResponse)
            assert result.content is not None
            assert isinstance(result.usage, OpenAIUsage)
            assert result.usage.prompt_tokens == 100
            assert result.usage.completion_tokens == 50

    @pytest.mark.asyncio
    async def test_chat_completion_handles_error(
        self,
        openai_service: OpenAIService,
    ) -> None:
        """Test que erro da API é tratado corretamente."""
        mock_response = MagicMock()
        mock_response.is_success = False
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch.object(openai_service, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_get_client.return_value = mock_client

            with pytest.raises(ValueError, match="OpenAI error"):
                await openai_service.chat_completion(
                    messages=[{"role": "user", "content": "Hello"}],
                )

    def test_build_json_schema_format(
        self,
        openai_service: OpenAIService,
    ) -> None:
        """Test construção de json_schema format."""
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
            },
            "required": ["name"],
        }

        result = openai_service.build_json_schema_format(schema, name="test")

        assert result["type"] == "json_schema"
        assert result["json_schema"]["name"] == "test"
        assert result["json_schema"]["strict"] is True
        assert result["json_schema"]["schema"] == schema


class TestOpenAIUsage:
    """Testes para OpenAIUsage."""

    def test_usage_defaults(self) -> None:
        """Test valores padrão de usage."""
        usage = OpenAIUsage()

        assert usage.prompt_tokens == 0
        assert usage.completion_tokens == 0
        assert usage.total_tokens == 0

    def test_usage_with_values(self) -> None:
        """Test usage com valores."""
        usage = OpenAIUsage(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
        )

        assert usage.prompt_tokens == 100
        assert usage.completion_tokens == 50
        assert usage.total_tokens == 150


class TestOpenAIResponse:
    """Testes para OpenAIResponse."""

    def test_response_creation(self) -> None:
        """Test criação de response."""
        response = OpenAIResponse(
            content="Hello world",
            usage=OpenAIUsage(),
            model="gpt-4o-mini",
        )

        assert response.content == "Hello world"
        assert response.model == "gpt-4o-mini"
        assert response.finish_reason == "stop"
        assert response.duration_ms == 0
