from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PresignUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=255)
    size: int = Field(ge=0)


class PresignUploadResponse(BaseModel):
    key: str
    upload_url: str
    method: str = "PUT"
    headers: dict[str, str] = Field(default_factory=dict)
    expires_in: int


class UploadResult(BaseModel):
    key: str
    size: int = Field(ge=0)
    content_type: str


class ConfirmUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=500)


class ConfirmUploadResponse(BaseModel):
    key: str
    uploaded: bool
