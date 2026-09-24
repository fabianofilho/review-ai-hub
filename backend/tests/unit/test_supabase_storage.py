"""
Unit tests for SupabaseStorageAdapter.

The Supabase client is a MagicMock; every test asserts the calls made to the
bucket API and how results and errors are translated by the adapter.
"""

from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from app.infrastructure.storage import StorageAdapter, SupabaseStorageAdapter
from app.infrastructure.storage.base import StorageError


@pytest.fixture
def client() -> MagicMock:
    """Mock Supabase client."""
    return MagicMock()


@pytest.fixture
def bucket_api(client: MagicMock) -> MagicMock:
    """Mock returned by client.storage.from_(bucket)."""
    return client.storage.from_.return_value


@pytest.fixture
def logger() -> MagicMock:
    """Logger mock injected through the LoggerMixin property."""
    return MagicMock()


@pytest.fixture
def adapter(client: MagicMock, logger: MagicMock):
    """Adapter under test with a patched logger."""
    with patch.object(
        SupabaseStorageAdapter, "logger", new_callable=PropertyMock, return_value=logger
    ):
        yield SupabaseStorageAdapter(client)


def test_is_a_storage_adapter(client):
    adapter = SupabaseStorageAdapter(client)

    assert isinstance(adapter, StorageAdapter)
    assert adapter.client is client


class TestDownload:
    async def test_returns_bytes_from_bucket(self, adapter, client, bucket_api):
        bucket_api.download.return_value = b"%PDF-1.4 content"

        result = await adapter.download("articles", "project-1/article.pdf")

        assert result == b"%PDF-1.4 content"
        client.storage.from_.assert_called_once_with("articles")
        bucket_api.download.assert_called_once_with("project-1/article.pdf")

    async def test_converts_bytearray_to_bytes(self, adapter, bucket_api):
        bucket_api.download.return_value = bytearray(b"abc")

        result = await adapter.download("articles", "a.pdf")

        assert result == b"abc"
        assert type(result) is bytes

    @pytest.mark.parametrize("empty", [b"", None])
    async def test_empty_response_raises_file_not_found(self, adapter, bucket_api, logger, empty):
        bucket_api.download.return_value = empty

        with pytest.raises(FileNotFoundError, match="File not found: articles/missing.pdf"):
            await adapter.download("articles", "missing.pdf")

        logger.error.assert_not_called()

    async def test_client_error_raises_storage_error(self, adapter, bucket_api, logger):
        bucket_api.download.side_effect = RuntimeError("connection reset")

        with pytest.raises(StorageError) as exc_info:
            await adapter.download("articles", "p/a.pdf")

        err = exc_info.value
        assert err.bucket == "articles"
        assert err.path == "p/a.pdf"
        assert str(err) == "Download failed: connection reset (bucket=articles, path=p/a.pdf)"
        logger.error.assert_called_once_with(
            "storage_download_error",
            bucket="articles",
            path="p/a.pdf",
            error="connection reset",
        )


class TestUpload:
    async def test_uploads_with_content_type_and_returns_path(
        self, adapter, client, bucket_api, logger
    ):
        result = await adapter.upload(
            "articles", "exports/u/job.zip", b"PK\x03\x04", "application/zip"
        )

        assert result == "exports/u/job.zip"
        client.storage.from_.assert_called_once_with("articles")
        bucket_api.upload.assert_called_once_with(
            "exports/u/job.zip",
            b"PK\x03\x04",
            file_options={"content-type": "application/zip"},
        )
        logger.info.assert_called_once_with(
            "storage_upload_success",
            bucket="articles",
            path="exports/u/job.zip",
            size=4,
        )

    async def test_default_content_type_is_octet_stream(self, adapter, bucket_api):
        await adapter.upload("articles", "raw.bin", b"x")

        assert bucket_api.upload.call_args.kwargs == {
            "file_options": {"content-type": "application/octet-stream"}
        }

    async def test_client_error_raises_storage_error(self, adapter, bucket_api, logger):
        bucket_api.upload.side_effect = RuntimeError("Duplicate")

        with pytest.raises(StorageError, match="Upload failed: Duplicate") as exc_info:
            await adapter.upload("articles", "a.pdf", b"data")

        assert (exc_info.value.bucket, exc_info.value.path) == ("articles", "a.pdf")
        logger.info.assert_not_called()
        logger.error.assert_called_once_with(
            "storage_upload_error", bucket="articles", path="a.pdf", error="Duplicate"
        )


class TestDelete:
    async def test_removes_single_path(self, adapter, client, bucket_api, logger):
        assert await adapter.delete("articles", "p/a.pdf") is True

        client.storage.from_.assert_called_once_with("articles")
        bucket_api.remove.assert_called_once_with(["p/a.pdf"])
        logger.info.assert_called_once_with(
            "storage_delete_success", bucket="articles", path="p/a.pdf"
        )

    async def test_error_returns_false_and_warns(self, adapter, bucket_api, logger):
        bucket_api.remove.side_effect = RuntimeError("forbidden")

        assert await adapter.delete("articles", "p/a.pdf") is False

        logger.warning.assert_called_once_with(
            "storage_delete_error", bucket="articles", path="p/a.pdf", error="forbidden"
        )


class TestExists:
    async def test_true_when_file_is_listed_in_parent_folder(self, adapter, bucket_api):
        bucket_api.list.return_value = [{"name": "other.pdf"}, {"name": "article.pdf"}]

        assert await adapter.exists("articles", "project-1/sub/article.pdf") is True

        bucket_api.list.assert_called_once_with("project-1/sub")

    async def test_false_when_file_is_not_listed(self, adapter, bucket_api):
        bucket_api.list.return_value = [{"name": "other.pdf"}, {"id": "no-name"}]

        assert await adapter.exists("articles", "project-1/article.pdf") is False

    async def test_root_level_file_lists_bucket_root(self, adapter, bucket_api):
        bucket_api.list.return_value = [{"name": "top.pdf"}]

        assert await adapter.exists("articles", "top.pdf") is True

        bucket_api.list.assert_called_once_with("")

    @pytest.mark.parametrize("response", [[], None])
    async def test_false_when_folder_is_empty(self, adapter, bucket_api, response):
        bucket_api.list.return_value = response

        assert await adapter.exists("articles", "p/a.pdf") is False

    async def test_false_on_client_error(self, adapter, bucket_api):
        bucket_api.list.side_effect = RuntimeError("boom")

        assert await adapter.exists("articles", "p/a.pdf") is False


class TestPublicUrl:
    async def test_returns_client_url(self, adapter, client, bucket_api):
        bucket_api.get_public_url.return_value = "https://cdn.test/articles/p/a.pdf"

        url = await adapter.get_public_url("articles", "p/a.pdf")

        assert url == "https://cdn.test/articles/p/a.pdf"
        client.storage.from_.assert_called_once_with("articles")
        bucket_api.get_public_url.assert_called_once_with("p/a.pdf")

    async def test_client_error_raises_storage_error(self, adapter, bucket_api):
        bucket_api.get_public_url.side_effect = RuntimeError("no bucket")

        with pytest.raises(StorageError, match="Failed to get public URL: no bucket") as exc_info:
            await adapter.get_public_url("articles", "p/a.pdf")

        assert (exc_info.value.bucket, exc_info.value.path) == ("articles", "p/a.pdf")


class TestSignedUrl:
    async def test_returns_signed_url_with_expiration(self, adapter, bucket_api):
        bucket_api.create_signed_url.return_value = {
            "signedURL": "https://storage.test/sign/p/a.pdf?token=t",
            "signedUrl": "https://storage.test/sign/p/a.pdf?token=t",
        }

        url = await adapter.get_signed_url("articles", "p/a.pdf", expires_in=120)

        assert url == "https://storage.test/sign/p/a.pdf?token=t"
        bucket_api.create_signed_url.assert_called_once_with("p/a.pdf", 120)

    async def test_default_expiration_is_one_hour(self, adapter, bucket_api):
        bucket_api.create_signed_url.return_value = {"signedURL": "https://s.test/x"}

        await adapter.get_signed_url("articles", "p/a.pdf")

        bucket_api.create_signed_url.assert_called_once_with("p/a.pdf", 3600)

    async def test_missing_key_returns_empty_string(self, adapter, bucket_api):
        bucket_api.create_signed_url.return_value = {}

        assert await adapter.get_signed_url("articles", "p/a.pdf") == ""

    async def test_client_error_raises_storage_error(self, adapter, bucket_api):
        bucket_api.create_signed_url.side_effect = RuntimeError("Object not found")

        with pytest.raises(StorageError, match="Failed to get signed URL: Object not found"):
            await adapter.get_signed_url("articles", "p/a.pdf")


class TestListFiles:
    async def test_lists_prefix_with_limit(self, adapter, client, bucket_api):
        files = [{"name": "a.pdf"}, {"name": "b.pdf"}]
        bucket_api.list.return_value = files

        result = await adapter.list_files("articles", prefix="project-1", limit=10)

        assert result == files
        client.storage.from_.assert_called_once_with("articles")
        bucket_api.list.assert_called_once_with("project-1", {"limit": 10})

    async def test_defaults(self, adapter, bucket_api):
        bucket_api.list.return_value = []

        await adapter.list_files("articles")

        bucket_api.list.assert_called_once_with("", {"limit": 100})

    async def test_none_response_returns_empty_list(self, adapter, bucket_api):
        bucket_api.list.return_value = None

        assert await adapter.list_files("articles", "p") == []

    async def test_client_error_returns_empty_list_and_logs(self, adapter, bucket_api, logger):
        bucket_api.list.side_effect = RuntimeError("timeout")

        assert await adapter.list_files("articles", "p") == []

        logger.error.assert_called_once_with(
            "storage_list_error", bucket="articles", prefix="p", error="timeout"
        )


class TestMove:
    async def test_moves_within_bucket(self, adapter, client, bucket_api, logger):
        assert await adapter.move("articles", "tmp/a.pdf", "final/a.pdf") is True

        client.storage.from_.assert_called_once_with("articles")
        bucket_api.move.assert_called_once_with("tmp/a.pdf", "final/a.pdf")
        logger.info.assert_called_once_with(
            "storage_move_success",
            bucket="articles",
            from_path="tmp/a.pdf",
            to_path="final/a.pdf",
        )

    async def test_error_returns_false_and_logs(self, adapter, bucket_api, logger):
        bucket_api.move.side_effect = RuntimeError("not found")

        assert await adapter.move("articles", "tmp/a.pdf", "final/a.pdf") is False

        logger.error.assert_called_once_with(
            "storage_move_error",
            bucket="articles",
            from_path="tmp/a.pdf",
            to_path="final/a.pdf",
            error="not found",
        )


class TestCopy:
    async def test_copies_within_bucket(self, adapter, client, bucket_api, logger):
        assert await adapter.copy("articles", "a.pdf", "b.pdf") is True

        client.storage.from_.assert_called_once_with("articles")
        bucket_api.copy.assert_called_once_with("a.pdf", "b.pdf")
        logger.info.assert_called_once_with(
            "storage_copy_success", bucket="articles", from_path="a.pdf", to_path="b.pdf"
        )

    async def test_error_returns_false_and_logs(self, adapter, bucket_api, logger):
        bucket_api.copy.side_effect = RuntimeError("exists")

        assert await adapter.copy("articles", "a.pdf", "b.pdf") is False

        logger.error.assert_called_once_with(
            "storage_copy_error",
            bucket="articles",
            from_path="a.pdf",
            to_path="b.pdf",
            error="exists",
        )
