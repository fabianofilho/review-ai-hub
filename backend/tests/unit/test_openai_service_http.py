"""
HTTP level unit tests for app.services.openai_service.

Complements test_openai_service.py. Requests go through an httpx.MockTransport
injected as the service client, so the real request building and response
handling run without any network access.
"""

import base64
import json
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import httpx
import pytest
import pytest_asyncio
from pydantic import BaseModel, ValidationError
from tenacity import RetryError

from app.services.openai_service import OpenAIService

Handler = Callable[[httpx.Request], httpx.Response]

BASE_URL = "https://api.openai.com/v1"


class StructuredAnswer(BaseModel):
    answer: str
    confidence: float


def _chat_body(content: str = "hello", **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": "gpt-4o-mini-2024",
        "choices": [{"index": 0, "message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
    }
    body.update(extra)
    return body


class RecordingHandler:
    """MockTransport handler that records requests and replays queued outcomes."""

    def __init__(self, *outcomes: httpx.Response | Exception) -> None:
        self.outcomes = list(outcomes)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def body(self, index: int = -1) -> Any:
        return json.loads(self.requests[index].content)


@pytest_asyncio.fixture
async def make_service() -> AsyncIterator[Callable[[RecordingHandler], OpenAIService]]:
    created: list[OpenAIService] = []

    def factory(handler: RecordingHandler) -> OpenAIService:
        service = OpenAIService(trace_id="trace-1", api_key="sk-test")
        service._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        created.append(service)
        return service

    yield factory

    for service in created:
        await service.close()


@pytest.fixture
def no_retry_sleep() -> Iterator[AsyncMock]:
    """Replace tenacity's sleep on chat_completion so retries run instantly."""
    with patch.object(OpenAIService.chat_completion.retry, "sleep", new=AsyncMock()) as sleep:
        yield sleep


class TestApiKeyAndClient:
    def test_defaults(self) -> None:
        service = OpenAIService()

        assert service.trace_id is None
        assert service.base_url == BASE_URL
        assert service._client is None

    def test_user_key_takes_precedence(self) -> None:
        with patch("app.services.openai_service.settings") as mock_settings:
            mock_settings.OPENAI_API_KEY = "sk-global"
            service = OpenAIService(api_key="sk-user")

            assert service.api_key == "sk-user"
            assert service.is_using_user_key is True

    def test_falls_back_to_global_key(self) -> None:
        with patch("app.services.openai_service.settings") as mock_settings:
            mock_settings.OPENAI_API_KEY = "sk-global"
            service = OpenAIService()

            assert service.api_key == "sk-global"
            assert service.is_using_user_key is False

    def test_set_api_key_drops_open_client(self) -> None:
        service = OpenAIService()
        open_client = MagicMock(is_closed=False)
        service._client = open_client

        service.set_api_key("sk-new")

        assert service._client is None
        assert service.api_key == "sk-new"
        assert service.is_using_user_key is True

    def test_set_api_key_none_returns_to_global_key(self) -> None:
        with patch("app.services.openai_service.settings") as mock_settings:
            mock_settings.OPENAI_API_KEY = "sk-global"
            service = OpenAIService(api_key="sk-user")

            service.set_api_key(None)

            assert service.api_key == "sk-global"
            assert service.is_using_user_key is False

    def test_set_api_key_leaves_closed_client_for_lazy_recreation(self) -> None:
        service = OpenAIService()
        closed_client = MagicMock(is_closed=True)
        service._client = closed_client

        service.set_api_key("sk-new")

        assert service._client is closed_client

    async def test_get_client_builds_authorized_client_and_reuses_it(self) -> None:
        service = OpenAIService(api_key="sk-abc")

        client = await service._get_client()
        try:
            assert isinstance(client, httpx.AsyncClient)
            assert client.headers["Authorization"] == "Bearer sk-abc"
            assert client.headers["Content-Type"] == "application/json"
            assert client.timeout.read == 120.0
            assert client.timeout.connect == 10.0
            assert await service._get_client() is client
        finally:
            await service.close()

        assert client.is_closed
        assert service._client is None

    async def test_get_client_recreates_after_close(self) -> None:
        service = OpenAIService(api_key="sk-abc")
        first = await service._get_client()
        await service.close()

        second = await service._get_client()
        try:
            assert second is not first
            assert not second.is_closed
        finally:
            await service.close()

    async def test_get_client_uses_new_key_after_set_api_key(self) -> None:
        service = OpenAIService(api_key="sk-old")
        old_client = await service._get_client()

        service.set_api_key("sk-new")
        new_client = await service._get_client()
        try:
            assert new_client is not old_client
            assert new_client.headers["Authorization"] == "Bearer sk-new"
        finally:
            await old_client.aclose()
            await service.close()

    async def test_close_without_client_is_noop(self) -> None:
        service = OpenAIService()

        await service.close()

        assert service._client is None


class TestChatCompletionFull:
    async def test_sends_payload_and_parses_response(
        self, make_service: Callable[[RecordingHandler], OpenAIService]
    ) -> None:
        handler = RecordingHandler(
            httpx.Response(
                200,
                json=_chat_body(
                    "the answer",
                    choices=[{"message": {"content": "the answer"}, "finish_reason": "length"}],
                ),
            )
        )
        service = make_service(handler)
        messages = [{"role": "user", "content": "question"}]

        result = await service.chat_completion_full(
            messages=messages,
            model="gpt-4o",
            response_format={"type": "json_object"},
            temperature=0.5,
            max_tokens=256,
        )

        assert len(handler.requests) == 1
        request = handler.requests[0]
        assert request.method == "POST"
        assert str(request.url) == f"{BASE_URL}/chat/completions"
        assert handler.body() == {
            "model": "gpt-4o",
            "messages": messages,
            "temperature": 0.5,
            "response_format": {"type": "json_object"},
            "max_tokens": 256,
        }
        assert result.content == "the answer"
        assert result.model == "gpt-4o-mini-2024"
        assert result.finish_reason == "length"
        assert result.usage.prompt_tokens == 11
        assert result.usage.completion_tokens == 7
        assert result.usage.total_tokens == 18
        assert result.duration_ms >= 0

    async def test_omits_optional_fields_and_applies_fallbacks(
        self, make_service: Callable[[RecordingHandler], OpenAIService]
    ) -> None:
        handler = RecordingHandler(
            httpx.Response(200, json={"choices": [{"message": {"content": "plain"}}]})
        )
        service = make_service(handler)

        result = await service.chat_completion_full(messages=[{"role": "user", "content": "q"}])

        assert handler.body() == {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "q"}],
            "temperature": 0.1,
        }
        assert result.content == "plain"
        assert result.model == "gpt-4o-mini"
        assert result.finish_reason == "stop"
        assert result.usage.prompt_tokens == 0
        assert result.usage.completion_tokens == 0
        assert result.usage.total_tokens == 0

    async def test_http_error_raises_with_truncated_body_and_logs(
        self, make_service: Callable[[RecordingHandler], OpenAIService]
    ) -> None:
        error_text = "E" * 600
        service = make_service(RecordingHandler(httpx.Response(429, text=error_text)))

        with patch.object(OpenAIService, "logger", new_callable=PropertyMock) as logger_prop:
            with pytest.raises(ValueError) as exc_info:
                await service.chat_completion_full(messages=[{"role": "user", "content": "q"}])

            logger_prop.return_value.error.assert_called_once_with(
                "openai_error",
                trace_id="trace-1",
                status=429,
                error=error_text[:500],
            )

        assert str(exc_info.value) == f"OpenAI error: 429 - {error_text[:500]}"


class TestChatCompletionRetry:
    async def test_returns_message_content(
        self, make_service: Callable[[RecordingHandler], OpenAIService]
    ) -> None:
        service = make_service(RecordingHandler(httpx.Response(200, json=_chat_body("hi"))))

        assert await service.chat_completion(messages=[{"role": "user", "content": "q"}]) == "hi"

    async def test_retries_timeout_then_succeeds(
        self,
        make_service: Callable[[RecordingHandler], OpenAIService],
        no_retry_sleep: AsyncMock,
    ) -> None:
        handler = RecordingHandler(
            httpx.ConnectTimeout("connect timed out"),
            httpx.Response(200, json=_chat_body("recovered")),
        )
        service = make_service(handler)

        result = await service.chat_completion(messages=[{"role": "user", "content": "q"}])

        assert result == "recovered"
        assert len(handler.requests) == 2
        no_retry_sleep.assert_awaited_once()
        (wait_seconds,) = no_retry_sleep.await_args.args
        assert 2 <= wait_seconds <= 10

    async def test_network_error_gives_up_after_three_attempts(
        self,
        make_service: Callable[[RecordingHandler], OpenAIService],
        no_retry_sleep: AsyncMock,
    ) -> None:
        handler = RecordingHandler(httpx.ConnectError("connection refused"))
        service = make_service(handler)

        with pytest.raises(RetryError) as exc_info:
            await service.chat_completion(messages=[{"role": "user", "content": "q"}])

        assert len(handler.requests) == 3
        assert no_retry_sleep.await_count == 2
        assert isinstance(exc_info.value.last_attempt.exception(), httpx.ConnectError)

    async def test_http_error_is_not_retried(
        self,
        make_service: Callable[[RecordingHandler], OpenAIService],
        no_retry_sleep: AsyncMock,
    ) -> None:
        handler = RecordingHandler(httpx.Response(500, text="server error"))
        service = make_service(handler)

        with pytest.raises(ValueError, match="OpenAI error: 500 - server error"):
            await service.chat_completion(messages=[{"role": "user", "content": "q"}])

        assert len(handler.requests) == 1
        no_retry_sleep.assert_not_awaited()


class TestChatCompletionStructured:
    async def test_sends_json_schema_and_validates_response(
        self, make_service: Callable[[RecordingHandler], OpenAIService]
    ) -> None:
        handler = RecordingHandler(
            httpx.Response(200, json=_chat_body('{"answer": "yes", "confidence": 0.9}'))
        )
        service = make_service(handler)

        result = await service.chat_completion_structured(
            messages=[{"role": "user", "content": "q"}],
            response_model=StructuredAnswer,
            model="gpt-4o",
            temperature=0.2,
            max_tokens=100,
        )

        assert result == StructuredAnswer(answer="yes", confidence=0.9)
        body = handler.body()
        assert body["model"] == "gpt-4o"
        assert body["temperature"] == 0.2
        assert body["max_tokens"] == 100
        assert body["response_format"] == {
            "type": "json_schema",
            "json_schema": {
                "name": "StructuredAnswer",
                "strict": True,
                "schema": StructuredAnswer.model_json_schema(),
            },
        }

    async def test_invalid_json_content_raises(
        self, make_service: Callable[[RecordingHandler], OpenAIService]
    ) -> None:
        service = make_service(RecordingHandler(httpx.Response(200, json=_chat_body("not json"))))

        with pytest.raises(json.JSONDecodeError):
            await service.chat_completion_structured(
                messages=[{"role": "user", "content": "q"}],
                response_model=StructuredAnswer,
            )

    async def test_schema_mismatch_raises_validation_error(
        self, make_service: Callable[[RecordingHandler], OpenAIService]
    ) -> None:
        service = make_service(
            RecordingHandler(httpx.Response(200, json=_chat_body('{"answer": "yes"}')))
        )

        with pytest.raises(ValidationError):
            await service.chat_completion_structured(
                messages=[{"role": "user", "content": "q"}],
                response_model=StructuredAnswer,
            )


class TestResponsesApiWithPdf:
    async def test_encodes_bytes_and_extracts_output_text(
        self, make_service: Callable[[RecordingHandler], OpenAIService]
    ) -> None:
        handler = RecordingHandler(
            httpx.Response(
                200,
                json={
                    "output": [
                        {"type": "reasoning", "content": [{"type": "output_text", "text": "x"}]},
                        {
                            "type": "message",
                            "content": [
                                {"type": "refusal", "text": "ignored"},
                                {"type": "output_text", "text": '{"title": "Paper"}'},
                                {"type": "output_text", "text": "second"},
                            ],
                        },
                    ],
                    "usage": {"input_tokens": 1200, "output_tokens": 80},
                },
            )
        )
        service = make_service(handler)
        pdf_bytes = b"%PDF-1.4 fake content"
        response_format = {"type": "json_schema", "name": "meta", "schema": {}}

        result = await service.responses_api_with_pdf(
            pdf_data=pdf_bytes,
            system_prompt="You extract metadata.",
            user_prompt="Extract the title.",
            response_format=response_format,
            model="gpt-4o",
            filename="paper.pdf",
        )

        assert str(handler.requests[0].url) == f"{BASE_URL}/responses"
        expected_data_url = "data:application/pdf;base64," + base64.b64encode(pdf_bytes).decode()
        assert handler.body() == {
            "model": "gpt-4o",
            "input": [
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": "You extract metadata."}],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_file",
                            "file_data": expected_data_url,
                            "filename": "paper.pdf",
                        },
                        {"type": "input_text", "text": "Extract the title."},
                    ],
                },
            ],
            "text": {"format": response_format},
        }
        assert result["output_text"] == '{"title": "Paper"}'
        assert result["input_tokens"] == 1200
        assert result["output_tokens"] == 80
        assert result["duration_ms"] >= 0

    async def test_base64_string_is_passed_through_without_format(
        self, make_service: Callable[[RecordingHandler], OpenAIService]
    ) -> None:
        handler = RecordingHandler(httpx.Response(200, json={}))
        service = make_service(handler)

        result = await service.responses_api_with_pdf(
            pdf_data="QUJD",
            system_prompt="sys",
            user_prompt="usr",
        )

        body = handler.body()
        assert "text" not in body
        assert body["model"] == "gpt-4o-mini"
        file_part = body["input"][1]["content"][0]
        assert file_part["file_data"] == "data:application/pdf;base64,QUJD"
        assert file_part["filename"] == "document.pdf"
        assert result["output_text"] is None
        assert result["input_tokens"] is None
        assert result["output_tokens"] is None

    async def test_http_error_raises_and_logs(
        self, make_service: Callable[[RecordingHandler], OpenAIService]
    ) -> None:
        service = make_service(RecordingHandler(httpx.Response(400, text="bad file")))

        with patch.object(OpenAIService, "logger", new_callable=PropertyMock) as logger_prop:
            with pytest.raises(ValueError) as exc_info:
                await service.responses_api_with_pdf(
                    pdf_data=b"%PDF", system_prompt="s", user_prompt="u"
                )

            logger_prop.return_value.error.assert_called_once_with(
                "openai_responses_error",
                trace_id="trace-1",
                status=400,
                error="bad file",
            )

        assert str(exc_info.value) == "OpenAI Responses API error: 400"


class TestEmbeddings:
    async def test_returns_vectors_in_order(
        self, make_service: Callable[[RecordingHandler], OpenAIService]
    ) -> None:
        handler = RecordingHandler(
            httpx.Response(
                200,
                json={
                    "data": [
                        {"index": 0, "embedding": [0.1, 0.2]},
                        {"index": 1, "embedding": [0.3, 0.4]},
                    ]
                },
            )
        )
        service = make_service(handler)

        vectors = await service.embeddings(["first", "second"])

        assert vectors == [[0.1, 0.2], [0.3, 0.4]]
        assert str(handler.requests[0].url) == f"{BASE_URL}/embeddings"
        assert handler.body() == {
            "model": "text-embedding-3-small",
            "input": ["first", "second"],
        }

    async def test_uses_requested_model(
        self, make_service: Callable[[RecordingHandler], OpenAIService]
    ) -> None:
        handler = RecordingHandler(httpx.Response(200, json={"data": []}))
        service = make_service(handler)

        assert await service.embeddings(["x"], model="text-embedding-3-large") == []
        assert handler.body()["model"] == "text-embedding-3-large"

    async def test_http_error_raises(
        self, make_service: Callable[[RecordingHandler], OpenAIService]
    ) -> None:
        service = make_service(RecordingHandler(httpx.Response(401, text="bad key")))

        with pytest.raises(ValueError, match="OpenAI embeddings error: 401"):
            await service.embeddings(["x"])


class TestBuildJsonSchemaFormat:
    def test_default_name_and_non_strict(self) -> None:
        schema = {"type": "object", "properties": {}}

        result = OpenAIService().build_json_schema_format(schema, strict=False)

        assert result == {
            "type": "json_schema",
            "json_schema": {"name": "response", "strict": False, "schema": schema},
        }
