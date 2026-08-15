# tests/test_storage_service.py
"""
Тесты для src/services/storage_service.py (R2StorageService).

Этот backend сейчас не активен (active_storage.py использует local storage),
но именно поэтому важно покрыть его тестами ДО переключения в проде —
иначе первый деплой с R2 будет "слепым": ни одна из этих функций реально
не выполнялась под тестами.

aioboto3 здесь полностью мокается — реальных сетевых вызовов к R2 нет.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.storage_service import R2NotConfiguredError, R2StorageService


def make_mock_s3_client(**method_overrides):
    """Создаёт мок s3-клиента, который ведёт себя как async context manager."""
    client = MagicMock()
    client.put_object = AsyncMock(return_value={})
    client.generate_presigned_url = AsyncMock(return_value="https://r2.example.com/presigned-url")
    client.delete_object = AsyncMock(return_value={})
    for name, value in method_overrides.items():
        setattr(client, name, value)

    @asynccontextmanager
    async def _client_cm(*args, **kwargs):
        yield client

    return client, _client_cm


@pytest.fixture
def configured_storage():
    """R2StorageService с валидными переменными окружения (все замоканы)."""
    with (
        patch("src.services.storage_service.R2_ACCOUNT_ID", "test-account"),
        patch("src.services.storage_service.R2_ACCESS_KEY_ID", "test-key-id"),
        patch("src.services.storage_service.R2_SECRET_ACCESS_KEY", "test-secret"),
        patch("src.services.storage_service.R2_BUCKET_NAME", "test-bucket"),
        patch("src.services.storage_service.R2_PUBLIC_BASE_URL", "https://cdn.example.com"),
    ):
        yield R2StorageService()


@pytest.fixture
def unconfigured_storage():
    """R2StorageService без переменных окружения — как на текущем проде."""
    with (
        patch("src.services.storage_service.R2_ACCOUNT_ID", ""),
        patch("src.services.storage_service.R2_ACCESS_KEY_ID", ""),
        patch("src.services.storage_service.R2_SECRET_ACCESS_KEY", ""),
        patch("src.services.storage_service.R2_BUCKET_NAME", ""),
        patch("src.services.storage_service.R2_PUBLIC_BASE_URL", ""),
    ):
        yield R2StorageService()


class TestIsConfigured:
    def test_true_when_all_vars_set(self, configured_storage):
        assert configured_storage.is_configured is True

    def test_false_when_vars_missing(self, unconfigured_storage):
        assert unconfigured_storage.is_configured is False

    def test_false_when_partially_configured(self):
        with (
            patch("src.services.storage_service.R2_ACCOUNT_ID", "acc"),
            patch("src.services.storage_service.R2_ACCESS_KEY_ID", ""),
            patch("src.services.storage_service.R2_SECRET_ACCESS_KEY", "secret"),
        ):
            storage = R2StorageService()
            assert storage.is_configured is False


class TestBuildKey:
    def test_builds_expected_path(self, configured_storage):
        key = configured_storage.build_key(42, "photo.jpg")
        assert key.startswith("attachments/42/")
        assert key.endswith("-photo.jpg")

    def test_sanitizes_path_separators_in_filename(self, configured_storage):
        key = configured_storage.build_key(1, "../../etc/passwd")
        # Не должно содержать необработанных слэшей из имени файла —
        # иначе можно было бы вылезти за пределы attachments/<task_id>/
        assert "/etc/passwd" not in key
        assert "passwd" in key

    def test_empty_filename_falls_back_to_file(self, configured_storage):
        key = configured_storage.build_key(1, "")
        assert key.endswith("-file")

    def test_keys_are_unique_for_same_filename(self, configured_storage):
        key1 = configured_storage.build_key(1, "same.txt")
        key2 = configured_storage.build_key(1, "same.txt")
        assert key1 != key2


class TestGetPublicUrl:
    def test_builds_url_when_public_base_set(self, configured_storage):
        url = configured_storage.get_public_url("attachments/1/a-file.txt")
        assert url == "https://cdn.example.com/attachments/1/a-file.txt"

    def test_empty_when_no_public_base(self, unconfigured_storage):
        assert unconfigured_storage.get_public_url("attachments/1/a-file.txt") == ""


class TestClient:
    def test_raises_when_not_configured(self, unconfigured_storage):
        with pytest.raises(R2NotConfiguredError):
            unconfigured_storage._client()

    @pytest.mark.filterwarnings("ignore:coroutine .* was never awaited:RuntimeWarning")
    def test_does_not_raise_when_configured(self, configured_storage):
        # Не должно бросать — просто создаёт клиента (без реального соединения).
        # _client() возвращает async context manager, который мы не открываем —
        # это осознанно: сама конструкция объекта не должна требовать сети/креды сверх проверки is_configured.
        # aiobotocore при этом создаёт корутину для клиента, которую мы не awaitим —
        # это ожидаемо и безопасно (сборщик мусора её просто отбросит), поэтому глушим предупреждение точечно.
        configured_storage._client()


class TestUpload:
    @pytest.mark.asyncio
    async def test_uploads_and_returns_public_url(self, configured_storage):
        client, client_cm = make_mock_s3_client()
        with patch.object(configured_storage._session, "client", side_effect=client_cm):
            url = await configured_storage.upload(
                key="attachments/1/file.pdf",
                data=b"hello world",
                content_type="application/pdf",
            )

        client.put_object.assert_called_once()
        call_kwargs = client.put_object.call_args.kwargs
        assert call_kwargs["Bucket"] == "test-bucket"
        assert call_kwargs["Key"] == "attachments/1/file.pdf"
        assert call_kwargs["Body"] == b"hello world"
        assert call_kwargs["ContentType"] == "application/pdf"
        assert url == "https://cdn.example.com/attachments/1/file.pdf"

    @pytest.mark.asyncio
    async def test_upload_without_content_type(self, configured_storage):
        client, client_cm = make_mock_s3_client()
        with patch.object(configured_storage._session, "client", side_effect=client_cm):
            await configured_storage.upload(key="attachments/1/file.pdf", data=b"data")

        call_kwargs = client.put_object.call_args.kwargs
        assert "ContentType" not in call_kwargs

    @pytest.mark.asyncio
    async def test_raises_when_not_configured(self, unconfigured_storage):
        with pytest.raises(R2NotConfiguredError):
            await unconfigured_storage.upload(key="x", data=b"y")


class TestGetPresignedUrl:
    @pytest.mark.asyncio
    async def test_returns_presigned_url(self, configured_storage):
        client, client_cm = make_mock_s3_client()
        with patch.object(configured_storage._session, "client", side_effect=client_cm):
            url = await configured_storage.get_presigned_url("attachments/1/file.pdf", expires_in=1800)

        client.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "test-bucket", "Key": "attachments/1/file.pdf"},
            ExpiresIn=1800,
        )
        assert url == "https://r2.example.com/presigned-url"

    @pytest.mark.asyncio
    async def test_default_expiry_is_one_hour(self, configured_storage):
        client, client_cm = make_mock_s3_client()
        with patch.object(configured_storage._session, "client", side_effect=client_cm):
            await configured_storage.get_presigned_url("k")

        assert client.generate_presigned_url.call_args.kwargs["ExpiresIn"] == 3600


class TestDelete:
    @pytest.mark.asyncio
    async def test_deletes_object(self, configured_storage):
        client, client_cm = make_mock_s3_client()
        with patch.object(configured_storage._session, "client", side_effect=client_cm):
            await configured_storage.delete("attachments/1/file.pdf")

        client.delete_object.assert_called_once_with(Bucket="test-bucket", Key="attachments/1/file.pdf")
