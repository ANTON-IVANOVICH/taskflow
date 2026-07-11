"""S3 / MinIO storage via aioboto3 (optional dependency).

Imports are guarded so the app runs without aioboto3 installed — only actually using the S3
backend (``STORAGE_BACKEND=s3``) requires it. In production, prefer presigned URLs so clients
upload/download directly against S3 instead of streaming bytes through the app.
"""

from __future__ import annotations

from typing import Any

from app.core.errors import StorageError, UploadNotFound
from app.storage.base import FileStorage, PresignedUpload, StoredObject


class S3Storage(FileStorage):
    backend = "s3"

    def __init__(self, *, bucket: str, region: str, endpoint_url: str | None = None) -> None:
        try:
            import aioboto3
        except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency
            raise StorageError("aioboto3 is required for the S3 storage backend") from exc
        self._bucket = bucket
        self._region = region
        self._endpoint_url = endpoint_url
        self._session = aioboto3.Session()

    def _client(self) -> Any:
        return self._session.client(
            "s3",
            region_name=self._region,
            endpoint_url=self._endpoint_url,
        )

    async def upload(self, *, key: str, content: bytes, content_type: str) -> StoredObject:
        async with self._client() as s3:
            await s3.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=content,
                ContentType=content_type,
            )
        return StoredObject(key=key, content_type=content_type, size=len(content))

    async def download(self, key: str) -> tuple[bytes, str]:
        async with self._client() as s3:
            try:
                response = await s3.get_object(Bucket=self._bucket, Key=key)
            except Exception as exc:  # noqa: BLE001 - normalize backend errors
                raise UploadNotFound(key) from exc
            body = await response["Body"].read()
            content_type = response.get("ContentType", "application/octet-stream")
        return body, content_type

    async def exists(self, key: str) -> bool:
        async with self._client() as s3:
            try:
                await s3.head_object(Bucket=self._bucket, Key=key)
            except Exception:  # noqa: BLE001 - missing object -> False
                return False
        return True

    async def delete(self, key: str) -> None:
        async with self._client() as s3:
            await s3.delete_object(Bucket=self._bucket, Key=key)

    async def presigned_upload(
        self,
        *,
        key: str,
        content_type: str,
        content_length: int,
        expires_in: int,
    ) -> PresignedUpload:
        del content_length
        async with self._client() as s3:
            url: str = await s3.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": self._bucket,
                    "Key": key,
                    "ContentType": content_type,
                },
                ExpiresIn=expires_in,
            )
        return PresignedUpload(
            url=url,
            method="PUT",
            headers={"Content-Type": content_type},
        )

    async def presigned_get_url(self, key: str, *, expires_in: int) -> str | None:
        async with self._client() as s3:
            url: str = await s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=expires_in,
            )
        return url
