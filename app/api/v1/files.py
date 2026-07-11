from __future__ import annotations

import time
from os.path import basename
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Body, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from app.core.config import get_settings
from app.core.deps import TasksReader, TasksWriter
from app.core.errors import (
    FileTooLarge,
    InvalidSignature,
    PermissionDenied,
    UnsupportedMediaType,
    UploadNotFound,
)
from app.schemas.files import (
    ConfirmUploadRequest,
    ConfirmUploadResponse,
    PresignUploadRequest,
    PresignUploadResponse,
    UploadResult,
)
from app.storage.factory import get_storage
from app.storage.presign import sign_upload_token, verify_upload_token

router = APIRouter(prefix="/files", tags=["files"])


@router.post(
    "/presigned-upload",
    response_model=PresignUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Request a presigned upload token",
)
async def create_presigned_upload(
    payload: Annotated[PresignUploadRequest, Body()],
    current_user: TasksWriter,
    request: Request,
) -> PresignUploadResponse:
    settings = get_settings()
    if payload.size > settings.storage_max_upload_bytes:
        raise FileTooLarge(settings.storage_max_upload_bytes)
    allowed = {item.strip() for item in settings.storage_allowed_types.split(",") if item.strip()}
    if payload.content_type not in allowed:
        raise UnsupportedMediaType(payload.content_type)

    safe_name = basename(payload.filename) or "upload.bin"
    key = f"uploads/{current_user.id}/{uuid4().hex}/{safe_name}"
    storage = get_storage(request.app)
    direct_upload = await storage.presigned_upload(
        key=key,
        content_type=payload.content_type,
        content_length=payload.size,
        expires_in=settings.storage_presign_ttl_seconds,
    )
    if direct_upload is not None:
        return PresignUploadResponse(
            key=key,
            upload_url=direct_upload.url,
            method=direct_upload.method,
            headers=direct_upload.headers,
            expires_in=settings.storage_presign_ttl_seconds,
        )

    expires_at = int(time.time()) + settings.storage_presign_ttl_seconds
    token = sign_upload_token(
        secret=settings.storage_url_secret,
        key=key,
        content_type=payload.content_type,
        max_size=payload.size,
        expires_at=expires_at,
    )
    # Local stand-in for an S3 presigned PUT: the signed token authorizes a direct PUT to our
    # receiver. S3 uses a real provider-signed URL above.
    upload_url = f"{settings.api_v1_prefix}/files/upload/{token}"
    return PresignUploadResponse(
        key=key,
        upload_url=upload_url,
        method="PUT",
        headers={"Content-Type": payload.content_type},
        expires_in=settings.storage_presign_ttl_seconds,
    )


@router.put(
    "/upload/{token}",
    response_model=UploadResult,
    summary="Upload bytes with a presigned token (no auth — the token is the credential)",
)
async def upload_with_token(
    token: str,
    request: Request,
) -> UploadResult:
    settings = get_settings()
    claims = verify_upload_token(secret=settings.storage_url_secret, token=token)
    key = str(claims["key"])
    content_type = str(claims["content_type"])
    raw_max_size = claims.get("max_size")
    if not isinstance(raw_max_size, int):
        raise InvalidSignature("Upload token has no valid size limit")
    max_size = raw_max_size

    raw_content_length = request.headers.get("content-length")
    if raw_content_length is not None:
        try:
            if int(raw_content_length) > max_size:
                raise FileTooLarge(max_size)
        except ValueError:
            pass

    request_content_type = request.headers.get("content-type", "").split(";", 1)[0].strip()
    if request_content_type != content_type:
        raise UnsupportedMediaType(request_content_type or None)

    content = await request.body()
    if len(content) > max_size:
        raise FileTooLarge(max_size)

    storage = get_storage(request.app)
    stored = await storage.upload(key=key, content=content, content_type=content_type)
    return UploadResult(key=stored.key, size=stored.size, content_type=stored.content_type)


@router.post(
    "/confirm",
    response_model=ConfirmUploadResponse,
    summary="Confirm an upload actually landed in storage",
)
async def confirm_upload(
    payload: Annotated[ConfirmUploadRequest, Body()],
    current_user: TasksReader,
    request: Request,
) -> ConfirmUploadResponse:
    _assert_file_owner(payload.key, current_user.id, current_user.is_admin)
    storage = get_storage(request.app)
    if not await storage.exists(payload.key):
        raise UploadNotFound(payload.key)
    return ConfirmUploadResponse(key=payload.key, uploaded=True)


@router.get(
    "/download",
    response_class=Response,
    summary="Download a stored file (S3 backend redirects to a presigned URL)",
)
async def download_file(
    key: Annotated[str, Query(min_length=1, max_length=500, description="Storage object key")],
    current_user: TasksReader,
    request: Request,
) -> Response:
    _assert_file_owner(key, current_user.id, current_user.is_admin)
    settings = get_settings()
    storage = get_storage(request.app)
    presigned = await storage.presigned_get_url(
        key,
        expires_in=settings.storage_presign_ttl_seconds,
    )
    if presigned is not None:
        return RedirectResponse(presigned)
    content, content_type = await storage.download(key)
    headers = {"Content-Disposition": f'attachment; filename="{basename(key)}"'}
    return Response(content=content, media_type=content_type, headers=headers)


def _assert_file_owner(key: str, user_id: int, is_admin: bool) -> None:
    if is_admin:
        return
    if not key.startswith(f"uploads/{user_id}/"):
        raise PermissionDenied("You do not have access to this file")
