"""
Assessment Endpoints Integration Tests.
"""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import AsyncClient

# The AI assessment router is mounted under the "/ai-assessment" prefix
# (see app/api/v1/router.py), which is the path the frontend service calls.
AI_ASSESSMENT_URL = "/api/v1/ai-assessment/ai"


class TestAIAssessmentEndpoints:
    """Integration tests for AI assessment endpoints."""

    @pytest.mark.asyncio
    async def test_ai_assessment_validation(
        self,
        client: AsyncClient,
    ) -> None:
        """Test AI assessment validation."""
        # No required fields
        response = await client.post(
            AI_ASSESSMENT_URL,
            json={},
        )

        assert response.status_code in (400, 422)
        missing_fields = {error["loc"][-1] for error in response.json()["detail"]}
        assert {"projectId", "articleId", "assessmentItemId", "instrumentId"} <= missing_fields

    @pytest.mark.asyncio
    async def test_ai_assessment_valid_request(
        self,
        client: AsyncClient,
    ) -> None:
        """Test AI assessment with valid request."""
        from app.services.ai_assessment_service import AssessmentResult

        assessment_id = str(uuid4())
        project_id = uuid4()
        article_id = uuid4()
        assessment_item_id = uuid4()
        instrument_id = uuid4()

        with patch("app.api.v1.endpoints.ai_assessment.AIAssessmentService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.assess = AsyncMock(
                return_value=AssessmentResult(
                    assessment_id=assessment_id,
                    selected_level="low",
                    confidence_score=0.85,
                    justification="Based on the evidence...",
                    evidence_passages=[],
                    tokens_prompt=500,
                    tokens_completion=100,
                    processing_time_ms=1500,
                    method_used="direct",
                )
            )

            response = await client.post(
                AI_ASSESSMENT_URL,
                json={
                    "projectId": str(project_id),
                    "articleId": str(article_id),
                    "assessmentItemId": str(assessment_item_id),
                    "instrumentId": str(instrument_id),
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data.get("ok") is True
            assert data["data"]["id"] == assessment_id
            assert data["data"]["selectedLevel"] == "low"
            assert data["data"]["metadata"]["methodUsed"] == "direct"

            mock_service.assess.assert_awaited_once()
            call_kwargs = mock_service.assess.await_args.kwargs
            assert call_kwargs["project_id"] == project_id
            assert call_kwargs["article_id"] == article_id
            assert call_kwargs["assessment_item_id"] == assessment_item_id
            assert call_kwargs["instrument_id"] == instrument_id
            assert call_kwargs["force_file_search"] is False

    @pytest.mark.asyncio
    async def test_ai_assessment_with_pdf_source(
        self,
        client: AsyncClient,
    ) -> None:
        """Test AI assessment specifying PDF source."""
        from app.services.ai_assessment_service import AssessmentResult

        pdf_storage_key = "articles/project-id/article-id/main.pdf"

        with patch("app.api.v1.endpoints.ai_assessment.AIAssessmentService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.assess = AsyncMock(
                return_value=AssessmentResult(
                    assessment_id=str(uuid4()),
                    selected_level="high",
                    confidence_score=0.9,
                    justification="Clear evidence found.",
                    evidence_passages=[{"text": "Sample evidence", "page_number": 5}],
                    tokens_prompt=500,
                    tokens_completion=100,
                    processing_time_ms=1500,
                    method_used="direct",
                )
            )

            response = await client.post(
                AI_ASSESSMENT_URL,
                json={
                    "projectId": str(uuid4()),
                    "articleId": str(uuid4()),
                    "assessmentItemId": str(uuid4()),
                    "instrumentId": str(uuid4()),
                    "pdfStorageKey": pdf_storage_key,
                },
            )

            assert response.status_code == 200
            assert response.json()["data"]["evidencePassages"] == [
                {"text": "Sample evidence", "page_number": 5}
            ]
            mock_service.assess.assert_awaited_once()
            assert mock_service.assess.await_args.kwargs["pdf_storage_key"] == pdf_storage_key

    @pytest.mark.asyncio
    async def test_ai_assessment_force_file_search(
        self,
        client: AsyncClient,
    ) -> None:
        """Test AI assessment with force_file_search."""
        from app.services.ai_assessment_service import AssessmentResult

        with patch("app.api.v1.endpoints.ai_assessment.AIAssessmentService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.assess = AsyncMock(
                return_value=AssessmentResult(
                    assessment_id=str(uuid4()),
                    selected_level="unclear",
                    confidence_score=0.6,
                    justification="Insufficient information.",
                    evidence_passages=[],
                    tokens_prompt=500,
                    tokens_completion=100,
                    processing_time_ms=1500,
                    method_used="file_search",
                )
            )

            response = await client.post(
                AI_ASSESSMENT_URL,
                json={
                    "projectId": str(uuid4()),
                    "articleId": str(uuid4()),
                    "assessmentItemId": str(uuid4()),
                    "instrumentId": str(uuid4()),
                    "forceFileSearch": True,
                },
            )

            assert response.status_code == 200
            assert response.json()["data"]["metadata"]["methodUsed"] == "file_search"
            mock_service.assess.assert_awaited_once()
            assert mock_service.assess.await_args.kwargs["force_file_search"] is True


class TestResponseHeaders:
    """Tests for response headers."""

    @pytest.mark.asyncio
    async def test_trace_id_header(
        self,
        client: AsyncClient,
    ) -> None:
        """Test that X-Trace-Id is present in responses."""
        response = await client.get("/health")

        assert response.status_code == 200
        assert "x-trace-id" in response.headers

    @pytest.mark.asyncio
    async def test_response_time_header(
        self,
        client: AsyncClient,
    ) -> None:
        """Test that X-Response-Time is present in responses."""
        response = await client.get("/health")

        assert response.status_code == 200
        assert "x-response-time" in response.headers

        # Should be a numeric value in ms
        time_str = response.headers["x-response-time"]
        assert "ms" in time_str
