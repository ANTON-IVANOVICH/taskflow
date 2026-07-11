"""Filesystem-backed storage for local dev and tests.

Blobs live under a base directory; content type is kept in a small ``.meta`` sidecar so downloads
can set the right ``Content-Type``. Keys are confined to the base dir to prevent path traversal.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.core.errors import StorageError, UploadNotFound
from app.storage.base import FileStorage, PresignedUpload, StoredObject


class LocalFileStorage(FileStorage):
    backend = "local"

    def __init__(self, base_dir: str) -> None:
        self._base = Path(base_dir).resolve()

    def _resolve(self, key: str) -> Path:
        target = (self._base / key).resolve()
        if self._base not in target.parents and target != self._base:
            raise StorageError("Resolved path escapes the storage root")
        return target

    async def upload(self, *, key: str, content: bytes, content_type: str) -> StoredObject:
        path = self._resolve(key)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            path.with_suffix(path.suffix + ".meta").write_text(
                json.dumps({"content_type": content_type, "size": len(content)})
            )

        await asyncio.to_thread(_write)
        return StoredObject(key=key, content_type=content_type, size=len(content))

    async def download(self, key: str) -> tuple[bytes, str]:
        path = self._resolve(key)

        def _read() -> tuple[bytes, str]:
            if not path.exists():
                raise UploadNotFound(key)
            content = path.read_bytes()
            meta_path = path.with_suffix(path.suffix + ".meta")
            content_type = "application/octet-stream"
            if meta_path.exists():
                content_type = json.loads(meta_path.read_text()).get(
                    "content_type", content_type
                )
            return content, content_type

        return await asyncio.to_thread(_read)

    async def exists(self, key: str) -> bool:
        path = self._resolve(key)
        return await asyncio.to_thread(path.exists)

    async def delete(self, key: str) -> None:
        path = self._resolve(key)

        def _delete() -> None:
            path.unlink(missing_ok=True)
            path.with_suffix(path.suffix + ".meta").unlink(missing_ok=True)

        await asyncio.to_thread(_delete)

    async def presigned_upload(
        self,
        *,
        key: str,
        content_type: str,
        content_length: int,
        expires_in: int,
    ) -> PresignedUpload | None:
        del key, content_type, content_length, expires_in
        return None

    async def presigned_get_url(self, key: str, *, expires_in: int) -> str | None:
        return None  # local backend is served through the app, not a direct URL
