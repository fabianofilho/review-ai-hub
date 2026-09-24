"""
Unit tests for the StorageAdapter interface and StorageError.
"""

from typing import Any

import pytest

from app.infrastructure.storage.base import StorageAdapter, StorageError


class DelegatingAdapter(StorageAdapter):
    """Concrete adapter that forwards every call to the abstract base bodies."""

    async def download(self, bucket: str, path: str) -> bytes:
        return await super().download(bucket, path)

    async def upload(
        self,
        bucket: str,
        path: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        return await super().upload(bucket, path, data, content_type)

    async def delete(self, bucket: str, path: str) -> bool:
        return await super().delete(bucket, path)

    async def exists(self, bucket: str, path: str) -> bool:
        return await super().exists(bucket, path)

    async def get_public_url(self, bucket: str, path: str) -> str:
        return await super().get_public_url(bucket, path)

    async def list_files(
        self,
        bucket: str,
        prefix: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return await super().list_files(bucket, prefix, limit)

    async def get_signed_url(self, bucket: str, path: str, expires_in: int = 3600) -> str:
        return await super().get_signed_url(bucket, path, expires_in)

    async def move(self, bucket: str, from_path: str, to_path: str) -> bool:
        return await super().move(bucket, from_path, to_path)


class TestStorageAdapterInterface:
    def test_cannot_instantiate_abstract_base(self):
        with pytest.raises(TypeError, match="abstract"):
            StorageAdapter()

    def test_subclass_missing_a_method_cannot_be_instantiated(self):
        class PartialAdapter(StorageAdapter):
            async def download(self, bucket: str, path: str) -> bytes:
                return b""

        with pytest.raises(TypeError) as exc_info:
            PartialAdapter()

        message = str(exc_info.value)
        for name in (
            "upload",
            "delete",
            "exists",
            "get_public_url",
            "list_files",
            "get_signed_url",
            "move",
        ):
            assert name in message
        assert "download" not in message

    def test_declares_expected_abstract_methods(self):
        assert StorageAdapter.__abstractmethods__ == frozenset(
            {
                "download",
                "upload",
                "delete",
                "exists",
                "get_public_url",
                "list_files",
                "get_signed_url",
                "move",
            }
        )

    async def test_base_method_bodies_provide_no_implementation(self):
        adapter = DelegatingAdapter()

        assert await adapter.download("b", "p") is None
        assert await adapter.upload("b", "p", b"data") is None
        assert await adapter.delete("b", "p") is None
        assert await adapter.exists("b", "p") is None
        assert await adapter.get_public_url("b", "p") is None
        assert await adapter.list_files("b") is None
        assert await adapter.get_signed_url("b", "p") is None
        assert await adapter.move("b", "p", "q") is None


class TestStorageError:
    def test_message_includes_bucket_and_path(self):
        err = StorageError("Download failed", "articles", "p/a.pdf")

        assert err.bucket == "articles"
        assert err.path == "p/a.pdf"
        assert str(err) == "Download failed (bucket=articles, path=p/a.pdf)"
        assert err.args == ("Download failed (bucket=articles, path=p/a.pdf)",)

    def test_bucket_and_path_default_to_empty(self):
        err = StorageError("boom")

        assert (err.bucket, err.path) == ("", "")
        assert str(err) == "boom (bucket=, path=)"

    def test_is_an_exception(self):
        with pytest.raises(Exception, match="boom"):
            raise StorageError("boom", "b", "p")
