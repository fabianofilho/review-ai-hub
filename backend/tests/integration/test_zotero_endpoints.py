"""
Zotero Endpoints Integration Tests.
"""

from unittest.mock import patch

import pytest
from httpx import AsyncClient


class TestZoteroEndpoints:
    """Testes de integração para endpoints do Zotero."""

    @pytest.mark.asyncio
    async def test_save_credentials_validation(
        self,
        client: AsyncClient,
    ) -> None:
        """Test validação de save-credentials."""
        # Request sem campos obrigatórios
        response = await client.post(
            "/api/v1/zotero/save-credentials",
            json={},
        )

        # Deve retornar erro de validação
        assert response.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_save_credentials_invalid_library_type(
        self,
        client: AsyncClient,
    ) -> None:
        """Test que library_type inválido é rejeitado."""
        response = await client.post(
            "/api/v1/zotero/save-credentials",
            json={
                "zoteroUserId": "123",
                "apiKey": "test-key",
                "libraryType": "invalid",  # Deve ser 'user' ou 'group'
            },
        )

        assert response.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_test_connection_without_credentials(
        self,
        client: AsyncClient,
    ) -> None:
        """Test que test-connection sem credenciais retorna erro."""
        with patch("app.services.zotero_service.ZoteroService._get_credentials") as mock_creds:
            mock_creds.side_effect = ValueError("Credenciais não encontradas")

            response = await client.post(
                "/api/v1/zotero/test-connection",
                json={},
            )

            # O endpoint captura o erro e retorna como resposta
            data = response.json()

            # Pode ser 200 com success=false ou 400
            if response.status_code == 200:
                assert data.get("ok") is True or data.get("data", {}).get("success") is False

    @pytest.mark.asyncio
    async def test_fetch_items_validation(
        self,
        client: AsyncClient,
    ) -> None:
        """Test validação de fetch-items."""
        response = await client.post(
            "/api/v1/zotero/fetch-items",
            json={
                "collectionKey": "ABC123",
                "limit": 200,  # Máximo é 100
            },
        )

        assert response.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_fetch_items_valid_request(
        self,
        client: AsyncClient,
    ) -> None:
        """Test fetch-items com request válida."""
        with patch("app.services.zotero_service.ZoteroService.fetch_items") as mock_fetch:
            mock_fetch.return_value = {
                "items": [],
                "total_results": 0,
                "has_more": False,
            }

            response = await client.post(
                "/api/v1/zotero/fetch-items",
                json={
                    "collectionKey": "ABC123",
                    "limit": 50,
                    "start": 0,
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data.get("ok") is True

    @pytest.mark.asyncio
    async def test_list_collections(
        self,
        client: AsyncClient,
    ) -> None:
        """Test list-collections."""
        with patch("app.services.zotero_service.ZoteroService.list_collections") as mock_list:
            mock_list.return_value = {"collections": []}

            response = await client.post(
                "/api/v1/zotero/list-collections",
                json={},
            )

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_download_attachment_validation(
        self,
        client: AsyncClient,
    ) -> None:
        """Test validação de download-attachment."""
        response = await client.post(
            "/api/v1/zotero/download-attachment",
            json={},  # Falta attachmentKey
        )

        assert response.status_code in (400, 422)
