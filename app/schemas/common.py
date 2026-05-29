from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    code: str
    message: str | None = None
    details: list[dict[str, object]] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
    request_id: str | None = None


class Pagination(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
