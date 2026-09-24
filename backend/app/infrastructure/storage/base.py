"""
Base Storage Adapter.

Interface abstrata para adapters de storage.
Permite trocar implementação (Supabase, S3, local) sem afetar services.
"""

from abc import ABC, abstractmethod
from typing import Any


class StorageAdapter(ABC):
    """
    Interface abstrata para storage de arquivos.

    Implementações:
    - SupabaseStorageAdapter: Supabase Storage
    - S3StorageAdapter: AWS S3 (futuro)
    - LocalStorageAdapter: Sistema de arquivos local (dev/testes)
    """

    @abstractmethod
    async def download(self, bucket: str, path: str) -> bytes:
        """
        Faz download de um arquivo.

        Args:
            bucket: Nome do bucket.
            path: Caminho do arquivo no bucket.

        Returns:
            Conteúdo do arquivo em bytes.

        Raises:
            FileNotFoundError: Se arquivo não existir.
            StorageError: Se erro de conexão/permissão.
        """
        pass

    @abstractmethod
    async def upload(
        self,
        bucket: str,
        path: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """
        Faz upload de um arquivo.

        Args:
            bucket: Nome do bucket.
            path: Caminho de destino no bucket.
            data: Conteúdo do arquivo.
            content_type: MIME type do arquivo.

        Returns:
            URL ou path do arquivo criado.

        Raises:
            StorageError: Se erro de upload.
        """
        pass

    @abstractmethod
    async def delete(self, bucket: str, path: str) -> bool:
        """
        Remove um arquivo.

        Args:
            bucket: Nome do bucket.
            path: Caminho do arquivo.

        Returns:
            True se removido, False se não existia.
        """
        pass

    @abstractmethod
    async def exists(self, bucket: str, path: str) -> bool:
        """
        Verifica se arquivo existe.

        Args:
            bucket: Nome do bucket.
            path: Caminho do arquivo.

        Returns:
            True se existe.
        """
        pass

    @abstractmethod
    async def get_public_url(self, bucket: str, path: str) -> str:
        """
        Obtém URL pública do arquivo.

        Args:
            bucket: Nome do bucket.
            path: Caminho do arquivo.

        Returns:
            URL pública para acesso.
        """
        pass

    @abstractmethod
    async def list_files(
        self,
        bucket: str,
        prefix: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Lista arquivos em um bucket/path.

        Args:
            bucket: Nome do bucket.
            prefix: Prefixo para filtrar.
            limit: Máximo de resultados.

        Returns:
            Lista de metadados dos arquivos.
        """
        pass

    @abstractmethod
    async def get_signed_url(
        self,
        bucket: str,
        path: str,
        expires_in: int = 3600,
    ) -> str:
        """
        Get a signed URL that expires after `expires_in` seconds.

        Args:
            bucket: Bucket name.
            path: File path.
            expires_in: Validity of the URL in seconds.

        Returns:
            Signed URL, or an empty string when none was issued.
        """
        pass

    @abstractmethod
    async def move(
        self,
        bucket: str,
        from_path: str,
        to_path: str,
    ) -> bool:
        """
        Move a file within the bucket.

        Args:
            bucket: Bucket name.
            from_path: Source path.
            to_path: Destination path.

        Returns:
            True if the file was moved.
        """
        pass


class StorageError(Exception):
    """Erro genérico de storage."""

    def __init__(self, message: str, bucket: str = "", path: str = ""):
        self.bucket = bucket
        self.path = path
        super().__init__(f"{message} (bucket={bucket}, path={path})")
