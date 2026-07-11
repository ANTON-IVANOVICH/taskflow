from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class StoredObject:
    key: str
    content_type: str
    size: int


@dataclass
class PresignedUpload:
    url: str
    method: str = "PUT"
    headers: dict[str, str] = field(default_factory=dict)


class FileStorage(ABC):
    """Backend-agnostic blob storage. Local (dev/test) and S3/MinIO (prod) implement it."""

    backend: str

    @abstractmethod
    async def upload(self, *, key: str, content: bytes, content_type: str) -> StoredObject: ...

    @abstractmethod
    async def download(self, key: str) -> tuple[bytes, str]: ...

    @abstractmethod
    async def exists(self, key: str) -> bool: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...

    @abstractmethod
    async def presigned_upload(
        self,
        *,
        key: str,
        content_type: str,
        content_length: int,
        expires_in: int,
    ) -> PresignedUpload | None:
        """Return a direct upload URL when the backend supports it."""

    @abstractmethod
    async def presigned_get_url(self, key: str, *, expires_in: int) -> str | None:
        """Return a direct-download URL when the backend supports it (S3), else None (local)."""
