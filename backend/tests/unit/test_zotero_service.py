"""
Unit tests for ZoteroService.

Testa funcionalidades de integração com Zotero:
- Criptografia de credenciais
- Comunicação com API Zotero
- Download de attachments
"""

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.zotero_service import ZoteroService


@pytest.fixture
def mock_db():
    """Mock da sessão de banco."""
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def mock_repo():
    """Mock do ZoteroIntegrationRepository."""
    mock = MagicMock()
    return mock


@pytest.fixture
def zotero_service(mock_db, mock_repo):
    """Fixture do ZoteroService com mocks."""
    with patch("app.services.zotero_service.ZoteroIntegrationRepository") as mock_repo_class:
        mock_repo_class.return_value = mock_repo
        service = ZoteroService(
            db=mock_db,
            user_id="test-user-id-123",
        )
        service._repo = mock_repo
        return service


class TestZoteroServiceEncryption:
    """Testes de criptografia de credenciais."""

    def test_encrypt_decrypt_roundtrip(self, zotero_service):
        """Testa que encrypt/decrypt funciona corretamente."""
        original_text = "my-secret-api-key"

        encrypted = zotero_service._encrypt(original_text)
        decrypted = zotero_service._decrypt(encrypted)

        assert decrypted == original_text
        assert encrypted != original_text

    def test_fernet_is_cached(self, zotero_service):
        """Testa que o Fernet é cacheado."""
        fernet1 = zotero_service.fernet
        fernet2 = zotero_service.fernet

        assert fernet1 is fernet2

    def test_different_users_get_different_keys(self, mock_db, mock_repo):
        """Testa que usuários diferentes têm chaves diferentes."""
        with patch("app.services.zotero_service.ZoteroIntegrationRepository"):
            service1 = ZoteroService(db=mock_db, user_id="user-1")
            service2 = ZoteroService(db=mock_db, user_id="user-2")

        text = "same-text"
        encrypted1 = service1._encrypt(text)
        encrypted2 = service2._encrypt(text)

        assert encrypted1 != encrypted2


class TestZoteroServiceCredentials:
    """Testes de gerenciamento de credenciais."""

    @pytest.mark.asyncio
    async def test_save_credentials_success(self, zotero_service, mock_repo):
        """Testa salvamento de credenciais."""
        # Configurar mock para retornar dados do upsert
        mock_integration = MagicMock()
        mock_integration.id = "integration-uuid"
        mock_repo.upsert = AsyncMock(return_value=mock_integration)

        result = await zotero_service.save_credentials(
            zotero_user_id="12345",
            api_key="zotero-api-key",
            library_type="user",
        )

        assert result["integration_id"] == "integration-uuid"
        mock_repo.upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_credentials_invalid_library_type(self, zotero_service):
        """Testa erro com library_type inválido."""
        with pytest.raises(ValueError, match="library_type must be"):
            await zotero_service.save_credentials(
                zotero_user_id="12345",
                api_key="key",
                library_type="invalid",
            )

    @pytest.mark.asyncio
    async def test_get_credentials_success(self, zotero_service, mock_repo):
        """Testa busca de credenciais."""
        encrypted_key = zotero_service._encrypt("my-api-key")

        mock_integration = MagicMock()
        mock_integration.zotero_user_id = "12345"
        mock_integration.encrypted_api_key = encrypted_key
        mock_integration.library_type = "user"

        mock_repo.get_by_user = AsyncMock(return_value=mock_integration)

        result = await zotero_service._get_credentials()

        assert result["zotero_user_id"] == "12345"
        assert result["api_key"] == "my-api-key"
        assert result["library_type"] == "user"

    @pytest.mark.asyncio
    async def test_get_credentials_not_found(self, zotero_service, mock_repo):
        """Testa erro quando credenciais não encontradas."""
        mock_repo.get_by_user = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="Credenciais não encontradas"):
            await zotero_service._get_credentials()


class TestZoteroServiceAPI:
    """Testes de comunicação com API Zotero."""

    @pytest.mark.asyncio
    async def test_test_connection_success(self, zotero_service, mock_repo):
        """Testa conexão bem-sucedida."""
        encrypted_key = zotero_service._encrypt("valid-api-key")

        # Mock _get_credentials
        mock_integration = MagicMock()
        mock_integration.zotero_user_id = "12345"
        mock_integration.encrypted_api_key = encrypted_key
        mock_integration.library_type = "user"
        mock_repo.get_by_user = AsyncMock(return_value=mock_integration)

        # Mock update
        mock_repo.update_last_sync = AsyncMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.is_success = True
            mock_response.json.return_value = {
                "userID": 12345,
                "username": "testuser",
                "access": {"user": {"library": True}},
            }

            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await zotero_service.test_connection()

        assert result["success"] is True
        assert result["user_name"] == "testuser"

    @pytest.mark.asyncio
    async def test_test_connection_invalid_key(self, zotero_service, mock_repo):
        """Testa conexão com API key inválida."""
        encrypted_key = zotero_service._encrypt("invalid-key")

        mock_integration = MagicMock()
        mock_integration.zotero_user_id = "12345"
        mock_integration.encrypted_api_key = encrypted_key
        mock_integration.library_type = "user"
        mock_repo.get_by_user = AsyncMock(return_value=mock_integration)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 403
            mock_response.is_success = False

            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await zotero_service.test_connection()

        assert result["success"] is False
        assert "inválida" in result["error"]

    @pytest.mark.asyncio
    async def test_list_collections(self, zotero_service, mock_repo):
        """Testa listagem de collections."""
        encrypted_key = zotero_service._encrypt("api-key")

        mock_integration = MagicMock()
        mock_integration.zotero_user_id = "12345"
        mock_integration.encrypted_api_key = encrypted_key
        mock_integration.library_type = "user"
        mock_repo.get_by_user = AsyncMock(return_value=mock_integration)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.is_success = True
            mock_response.json.return_value = [
                {"key": "ABC123", "data": {"name": "My Collection"}},
            ]
            mock_response.headers = {"Total-Results": "1", "Link": ""}

            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await zotero_service.list_collections()

        assert len(result["collections"]) == 1
        assert result["collections"][0]["key"] == "ABC123"

    @pytest.mark.asyncio
    async def test_fetch_items(self, zotero_service, mock_repo):
        """Testa busca de items."""
        encrypted_key = zotero_service._encrypt("api-key")

        mock_integration = MagicMock()
        mock_integration.zotero_user_id = "12345"
        mock_integration.encrypted_api_key = encrypted_key
        mock_integration.library_type = "user"
        mock_repo.get_by_user = AsyncMock(return_value=mock_integration)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.is_success = True
            mock_response.json.return_value = [
                {"key": "ITEM1", "data": {"title": "Paper 1"}},
                {"key": "ITEM2", "data": {"title": "Paper 2"}},
            ]
            mock_response.headers = {
                "Total-Results": "100",
                "Link": '<url>; rel="next"',
            }

            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await zotero_service.fetch_items(
                collection_key="COL123",
                limit=50,
                start=0,
            )

        assert len(result["items"]) == 2
        assert result["total_results"] == 100
        assert result["has_more"] is True


class TestZoteroServiceDownload:
    """Testes de download de attachments."""

    @pytest.mark.asyncio
    async def test_download_attachment_success(self, zotero_service, mock_repo):
        """Testa download bem-sucedido."""
        encrypted_key = zotero_service._encrypt("api-key")

        mock_integration = MagicMock()
        mock_integration.zotero_user_id = "12345"
        mock_integration.encrypted_api_key = encrypted_key
        mock_integration.library_type = "user"
        mock_repo.get_by_user = AsyncMock(return_value=mock_integration)

        pdf_content = b"%PDF-1.4 fake pdf content"

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.is_success = True
            mock_response.content = pdf_content
            mock_response.headers = {
                "Content-Type": "application/pdf",
                "Content-Disposition": 'attachment; filename="paper.pdf"',
            }

            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await zotero_service.download_attachment("ATT123")

        assert result["filename"] == "paper.pdf"
        assert result["content_type"] == "application/pdf"
        assert result["size"] == len(pdf_content)

        # Verificar que o base64 decodifica corretamente
        decoded = base64.b64decode(result["base64"])
        assert decoded == pdf_content

    @pytest.mark.asyncio
    async def test_download_attachment_too_large(self, zotero_service, mock_repo):
        """Testa erro com arquivo muito grande."""
        encrypted_key = zotero_service._encrypt("api-key")

        mock_integration = MagicMock()
        mock_integration.zotero_user_id = "12345"
        mock_integration.encrypted_api_key = encrypted_key
        mock_integration.library_type = "user"
        mock_repo.get_by_user = AsyncMock(return_value=mock_integration)

        # Criar conteúdo maior que 50MB
        large_content = b"x" * (51 * 1024 * 1024)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.is_success = True
            mock_response.content = large_content
            mock_response.headers = {"Content-Type": "application/pdf"}

            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            with pytest.raises(ValueError, match="muito grande"):
                await zotero_service.download_attachment("ATT123")
