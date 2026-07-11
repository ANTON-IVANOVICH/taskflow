"""Storage backend selection.

``get_storage`` returns the app-state storage when the lifespan wired it up, otherwise a
module-level default (local, so it works in tests where the lifespan never runs).
"""

from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.storage.base import FileStorage
from app.storage.local import LocalFileStorage


def build_storage() -> FileStorage:
    settings = get_settings()
    if settings.storage_backend == "s3" and settings.s3_bucket:
        from app.storage.s3 import S3Storage

        return S3Storage(
            bucket=settings.s3_bucket,
            region=settings.s3_region,
            endpoint_url=settings.s3_endpoint_url,
        )
    return LocalFileStorage(settings.storage_local_dir)


default_storage: FileStorage = build_storage()


def get_storage(app: Any) -> FileStorage:
    storage = getattr(app.state, "storage", None)
    if isinstance(storage, FileStorage):
        return storage
    return default_storage
