"""
Tests for health check and basic endpoints.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient) -> None:
    """Test health check endpoint returns healthy status."""
    response = await client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data


@pytest.mark.asyncio
async def test_root_endpoint(client: AsyncClient) -> None:
    """Test root endpoint returns API info."""
    response = await client.get("/")

    assert response.status_code == 200
    data = response.json()
    assert "name" in data
    assert "version" in data
    assert "docs" in data


@pytest.mark.asyncio
async def test_openapi_schema_available(client: AsyncClient) -> None:
    """Test OpenAPI schema is accessible."""
    response = await client.get("/api/v1/openapi.json")

    assert response.status_code == 200
    data = response.json()
    assert "openapi" in data
    assert "paths" in data


@pytest.mark.asyncio
async def test_trace_id_header_present(client: AsyncClient) -> None:
    """Test that X-Trace-Id header is present in responses."""
    response = await client.get("/health")

    assert response.status_code == 200
    assert "x-trace-id" in response.headers


@pytest.mark.asyncio
async def test_response_time_header_present(client: AsyncClient) -> None:
    """Test that X-Response-Time header is present in responses."""
    response = await client.get("/health")

    assert response.status_code == 200
    assert "x-response-time" in response.headers

    # Deve ser um valor com "ms"
    time_str = response.headers["x-response-time"]
    assert "ms" in time_str
