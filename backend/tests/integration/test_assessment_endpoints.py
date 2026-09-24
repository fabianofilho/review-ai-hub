"""
Assessment Endpoints Integration Tests.
"""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import AsyncClient


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
            "/api/v1/assessment/ai",
            json={},
        )

        assert response.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_ai_assessment_valid_request(
        self,
        client: AsyncClient,
    ) -> None:
        """Test AI assessment with valid request."""
        from app.services.ai_assessment_service import AssessmentResult

        with patch("app.api.v1.endpoints.ai_assessment.AIAssessmentService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.assess = AsyncMock(
                return_value=AssessmentResult(
                    assessment_id=str(uuid4()),
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
                "/api/v1/assessment/ai",
                json={
                    "projectId": str(uuid4()),
                    "articleId": str(uuid4()),
                    "assessmentItemId": str(uuid4()),
                    "instrumentId": str(uuid4()),
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data.get("ok") is True

    @pytest.mark.asyncio
    async def test_ai_assessment_with_pdf_source(
        self,
        client: AsyncClient,
    ) -> None:
        """Test AI assessment specifying PDF source."""
        from app.services.ai_assessment_service import AssessmentResult

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
                "/api/v1/assessment/ai",
                json={
                    "projectId": str(uuid4()),
                    "articleId": str(uuid4()),
                    "assessmentItemId": str(uuid4()),
                    "instrumentId": str(uuid4()),
                    "pdfStorageKey": "articles/project-id/article-id/main.pdf",
                },
            )

            assert response.status_code == 200

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
                "/api/v1/assessment/ai",
                json={
                    "projectId": str(uuid4()),
                    "articleId": str(uuid4()),
                    "assessmentItemId": str(uuid4()),
                    "instrumentId": str(uuid4()),
                    "forceFileSearch": True,
                },
            )

            assert response.status_code == 200


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
