"""
Supabase Storage Adapter.

Implements StorageAdapter for Supabase Storage.
Manages PDFs and other article files.
"""

from typing import Any

from supabase import Client

from app.core.logging import LoggerMixin
from app.infrastructure.storage.base import StorageAdapter, StorageError


class SupabaseStorageAdapter(StorageAdapter, LoggerMixin):
    """
    Adapter for Supabase Storage.

    Encapsulates all Supabase storage operations.

    Usage:
        adapter = SupabaseStorageAdapter(supabase_client)
        pdf_bytes = await adapter.download("articles", "project-1/article.pdf")
    """

    def __init__(self, client: Client):
        """
        Initialize adapter with Supabase client.

        Args:
            client: Authenticated Supabase client.
        """
        self.client = client

    async def download(self, bucket: str, path: str) -> bytes:
        """
        Download a file from Supabase Storage.

        Args:
            bucket: Bucket name (e.g. "articles").
            path: File path.

        Returns:
            Content in bytes.

        Raises:
            FileNotFoundError: If file does not exist.
            StorageError: On connection error.
        """
        try:
            response = self.client.storage.from_(bucket).download(path)

            if not response:
                raise FileNotFoundError(f"File not found: {bucket}/{path}")

            # Supabase returns bytes directly
            return bytes(response)

        except FileNotFoundError:
            raise
        except Exception as e:
            self.logger.error(
                "storage_download_error",
                bucket=bucket,
                path=path,
                error=str(e),
            )
            raise StorageError(f"Download failed: {e}", bucket, path)

    async def upload(
        self,
        bucket: str,
        path: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """
        Upload a file to Supabase Storage.

        Args:
            bucket: Bucket name.
            path: Destination path.
            data: File content.
            content_type: MIME type.

        Returns:
            Path of created file.

        Raises:
            StorageError: On upload error.
        """
        try:
            response = self.client.storage.from_(bucket).upload(
                path,
                data,
                file_options={"content-type": content_type},
            )

            self.logger.info(
                "storage_upload_success",
                bucket=bucket,
                path=path,
                size=len(data),
            )

            return path

        except Exception as e:
            self.logger.error(
                "storage_upload_error",
                bucket=bucket,
                path=path,
                error=str(e),
            )
            raise StorageError(f"Upload failed: {e}", bucket, path)

    async def delete(self, bucket: str, path: str) -> bool:
        """
        Remove a file from Supabase Storage.

        Args:
            bucket: Bucket name.
            path: File path.

        Returns:
            True if removed.
        """
        try:
            self.client.storage.from_(bucket).remove([path])

            self.logger.info(
                "storage_delete_success",
                bucket=bucket,
                path=path,
            )

            return True

        except Exception as e:
            self.logger.warning(
                "storage_delete_error",
                bucket=bucket,
                path=path,
                error=str(e),
            )
            return False

    async def exists(self, bucket: str, path: str) -> bool:
        """
        Check if file exists in Supabase Storage.

        Args:
            bucket: Bucket name.
            path: File path.

        Returns:
            True if exists.
        """
        try:
            # Try to list the specific file
            folder = "/".join(path.split("/")[:-1]) or ""
            filename = path.split("/")[-1]

            response = self.client.storage.from_(bucket).list(folder)

            if response:
                return any(f.get("name") == filename for f in response)

            return False

        except Exception:
            return False

    async def get_public_url(self, bucket: str, path: str) -> str:
        """
        Get public URL of a file.

        Args:
            bucket: Bucket name.
            path: File path.

        Returns:
            Public URL.
        """
        try:
            response = self.client.storage.from_(bucket).get_public_url(path)
            return response
        except Exception as e:
            raise StorageError(f"Failed to get public URL: {e}", bucket, path)

    async def get_signed_url(
        self,
        bucket: str,
        path: str,
        expires_in: int = 3600,
    ) -> str:
        """
        Get signed URL with expiration.

        Args:
            bucket: Bucket name.
            path: File path.
            expires_in: Expiration time in seconds.

        Returns:
            Signed URL.
        """
        try:
            response = self.client.storage.from_(bucket).create_signed_url(path, expires_in)
            return response.get("signedURL", "")
        except Exception as e:
            raise StorageError(f"Failed to get signed URL: {e}", bucket, path)

    async def list_files(
        self,
        bucket: str,
        prefix: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        List files in a bucket/path.

        Args:
            bucket: Bucket name.
            prefix: Prefix/folder to filter.
            limit: Maximum results.

        Returns:
            List of file metadata.
        """
        try:
            response = self.client.storage.from_(bucket).list(
                prefix,
                {"limit": limit},
            )

            return response or []

        except Exception as e:
            self.logger.error(
                "storage_list_error",
                bucket=bucket,
                prefix=prefix,
                error=str(e),
            )
            return []

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
            True if moved successfully.
        """
        try:
            self.client.storage.from_(bucket).move(from_path, to_path)

            self.logger.info(
                "storage_move_success",
                bucket=bucket,
                from_path=from_path,
                to_path=to_path,
            )

            return True

        except Exception as e:
            self.logger.error(
                "storage_move_error",
                bucket=bucket,
                from_path=from_path,
                to_path=to_path,
                error=str(e),
            )
            return False

    async def copy(
        self,
        bucket: str,
        from_path: str,
        to_path: str,
    ) -> bool:
        """
        Copy a file within the bucket.

        Args:
            bucket: Bucket name.
            from_path: Source path.
            to_path: Destination path.

        Returns:
            True if copied successfully.
        """
        try:
            self.client.storage.from_(bucket).copy(from_path, to_path)

            self.logger.info(
                "storage_copy_success",
                bucket=bucket,
                from_path=from_path,
                to_path=to_path,
            )

            return True

        except Exception as e:
            self.logger.error(
                "storage_copy_error",
                bucket=bucket,
                from_path=from_path,
                to_path=to_path,
                error=str(e),
            )
            return False
