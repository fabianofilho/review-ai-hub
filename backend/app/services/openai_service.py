"""
OpenAI Service.

Wrapper completo para chamadas à API da OpenAI com suporte a:
- Chat completions com JSON mode
- Structured outputs (json_schema)
- Responses API para PDFs
- Embeddings
- Retry com backoff exponencial
- Token tracking
"""

import base64
import json
import time
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import settings
from app.core.logging import LoggerMixin

T = TypeVar("T", bound=BaseModel)


class OpenAIUsage(BaseModel):
    """Uso de tokens da API."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class OpenAIResponse(BaseModel):
    """Response estruturada da OpenAI."""

    content: str
    usage: OpenAIUsage
    model: str
    finish_reason: str = "stop"
    duration_ms: float = 0


class OpenAIService(LoggerMixin):
    """
    Service para interação com OpenAI API.

    Inclui retry automático, structured outputs e logging estruturado.
    Suporta API key dinâmica (BYOK) com fallback para key global.
    """

    def __init__(
        self,
        trace_id: str | None = None,
        api_key: str | None = None,
    ):
        """
        Inicializa o service.

        Args:
            trace_id: ID de rastreamento para logs.
            api_key: API key customizada (BYOK). Se None, usa key global.
        """
        self.trace_id = trace_id
        self.base_url = "https://api.openai.com/v1"
        self._api_key = api_key
        self._client: httpx.AsyncClient | None = None
        self._using_user_key = api_key is not None

    @property
    def api_key(self) -> str | None:
        """Retorna API key (customizada ou global)."""
        if self._api_key:
            return self._api_key
        return settings.OPENAI_API_KEY

    @property
    def is_using_user_key(self) -> bool:
        """Indica se está usando key do usuário (BYOK)."""
        return self._using_user_key

    def set_api_key(self, api_key: str | None) -> None:
        """
        Define API key dinâmica.

        Invalida o cliente HTTP para usar a nova key.

        Args:
            api_key: Nova API key ou None para usar global.
        """
        self._api_key = api_key
        self._using_user_key = api_key is not None
        # Invalidar cliente para usar nova key
        if self._client and not self._client.is_closed:
            # Não fechar aqui para evitar problemas com async
            # O cliente será recriado na próxima chamada
            self._client = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Retorna cliente HTTP reutilizável."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(120.0, connect=10.0),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def close(self) -> None:
        """Fecha cliente HTTP."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
    )
    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str = "gpt-4o-mini",
        response_format: dict[str, Any] | None = None,
        temperature: float = 0.1,
        max_tokens: int | None = None,
    ) -> str:
        """
        Executa chat completion.

        Args:
            messages: Lista de mensagens.
            model: Modelo a usar.
            response_format: Formato de resposta (json_object ou json_schema).
            temperature: Temperatura para geração.
            max_tokens: Limite de tokens.

        Returns:
            Texto da resposta.
        """
        response = await self.chat_completion_full(
            messages=messages,
            model=model,
            response_format=response_format,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.content

    async def chat_completion_full(
        self,
        messages: list[dict[str, Any]],
        model: str = "gpt-4o-mini",
        response_format: dict[str, Any] | None = None,
        temperature: float = 0.1,
        max_tokens: int | None = None,
    ) -> OpenAIResponse:
        """
        Executa chat completion com resposta completa.

        Retorna objeto com content, usage e metadata.
        """
        start_time = time.time()

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }

        if response_format:
            payload["response_format"] = response_format

        if max_tokens:
            payload["max_tokens"] = max_tokens

        client = await self._get_client()
        response = await client.post(
            f"{self.base_url}/chat/completions",
            json=payload,
        )

        duration = (time.time() - start_time) * 1000

        if not response.is_success:
            error_text = response.text[:500]
            self.logger.error(
                "openai_error",
                trace_id=self.trace_id,
                status=response.status_code,
                error=error_text,
            )
            raise ValueError(f"OpenAI error: {response.status_code} - {error_text}")

        result = response.json()
        usage_data = result.get("usage", {})

        usage = OpenAIUsage(
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            completion_tokens=usage_data.get("completion_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0),
        )

        self.logger.info(
            "openai_completion",
            trace_id=self.trace_id,
            model=model,
            duration_ms=duration,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
        )

        choice = result["choices"][0]
        return OpenAIResponse(
            content=choice["message"]["content"],
            usage=usage,
            model=result.get("model", model),
            finish_reason=choice.get("finish_reason", "stop"),
            duration_ms=duration,
        )

    async def chat_completion_structured(
        self,
        messages: list[dict[str, Any]],
        response_model: type[T],
        model: str = "gpt-4o-mini",
        temperature: float = 0.1,
        max_tokens: int | None = None,
    ) -> T:
        """
        Executa chat completion com resposta estruturada Pydantic.

        Usa json_schema para garantir formato correto.

        Args:
            messages: Lista de mensagens.
            response_model: Modelo Pydantic para validar resposta.
            model: Modelo OpenAI.
            temperature: Temperatura.
            max_tokens: Limite de tokens.

        Returns:
            Instância do modelo Pydantic.
        """
        # Gerar JSON schema do modelo Pydantic
        schema = response_model.model_json_schema()

        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": response_model.__name__,
                "strict": True,
                "schema": schema,
            },
        }

        content = await self.chat_completion(
            messages=messages,
            model=model,
            response_format=response_format,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        # Parse e validar com Pydantic
        data = json.loads(content)
        return response_model.model_validate(data)

    async def responses_api_with_pdf(
        self,
        pdf_data: bytes | str,
        system_prompt: str,
        user_prompt: str,
        response_format: dict[str, Any] | None = None,
        model: str = "gpt-4o-mini",
        filename: str = "document.pdf",
    ) -> dict[str, Any]:
        """
        Usa Responses API para analisar PDF diretamente.

        Args:
            pdf_data: Bytes do PDF ou base64 string.
            system_prompt: Prompt do sistema.
            user_prompt: Prompt do usuário.
            response_format: Formato de resposta estruturada.
            model: Modelo a usar.
            filename: Nome do arquivo.

        Returns:
            Dict com output_text, input_tokens e output_tokens.
        """
        start_time = time.time()

        # Converter para base64 se necessário
        if isinstance(pdf_data, bytes):
            pdf_base64 = base64.b64encode(pdf_data).decode()
        else:
            pdf_base64 = pdf_data

        data_url = f"data:application/pdf;base64,{pdf_base64}"

        payload: dict[str, Any] = {
            "model": model,
            "input": [
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": system_prompt}],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_file",
                            "file_data": data_url,
                            "filename": filename,
                        },
                        {"type": "input_text", "text": user_prompt},
                    ],
                },
            ],
        }

        if response_format:
            payload["text"] = {"format": response_format}

        client = await self._get_client()
        response = await client.post(
            f"{self.base_url}/responses",
            json=payload,
        )

        duration = (time.time() - start_time) * 1000

        if not response.is_success:
            error_text = response.text[:500]
            self.logger.error(
                "openai_responses_error",
                trace_id=self.trace_id,
                status=response.status_code,
                error=error_text,
            )
            raise ValueError(f"OpenAI Responses API error: {response.status_code}")

        result = response.json()

        # Extrair output_text
        output_text = None
        for item in result.get("output", []):
            if item.get("type") == "message":
                for content in item.get("content", []):
                    if content.get("type") == "output_text":
                        output_text = content.get("text")
                        break

        usage = result.get("usage", {})

        self.logger.info(
            "openai_responses_completion",
            trace_id=self.trace_id,
            model=model,
            duration_ms=duration,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
        )

        return {
            "output_text": output_text,
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "duration_ms": duration,
        }

    async def embeddings(
        self,
        texts: list[str],
        model: str = "text-embedding-3-small",
    ) -> list[list[float]]:
        """
        Gera embeddings para textos.

        Args:
            texts: Lista de textos.
            model: Modelo de embedding.

        Returns:
            Lista de vetores de embedding.
        """
        client = await self._get_client()
        response = await client.post(
            f"{self.base_url}/embeddings",
            json={
                "model": model,
                "input": texts,
            },
        )

        if not response.is_success:
            raise ValueError(f"OpenAI embeddings error: {response.status_code}")

        result = response.json()

        return [item["embedding"] for item in result["data"]]

    def build_json_schema_format(
        self,
        schema: dict[str, Any],
        name: str = "response",
        strict: bool = True,
    ) -> dict[str, Any]:
        """
        Constrói formato json_schema para response_format.

        Args:
            schema: JSON schema das propriedades.
            name: Nome do schema.
            strict: Se deve usar modo strict.

        Returns:
            Dict para usar em response_format.
        """
        return {
            "type": "json_schema",
            "json_schema": {
                "name": name,
                "strict": strict,
                "schema": schema,
            },
        }
