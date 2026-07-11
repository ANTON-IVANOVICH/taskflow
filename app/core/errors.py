class DomainError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class TaskNotFound(DomainError):
    def __init__(self, task_id: int) -> None:
        super().__init__(
            code="task_not_found",
            message=f"Task {task_id} not found",
            status_code=404,
        )


class TeamNotFound(DomainError):
    def __init__(self, team_id: int) -> None:
        super().__init__(
            code="team_not_found",
            message=f"Team {team_id} not found",
            status_code=404,
        )


class TaskAttachmentNotFound(DomainError):
    def __init__(self, task_id: int, attachment_id: int) -> None:
        super().__init__(
            code="task_attachment_not_found",
            message=f"Attachment {attachment_id} not found for task {task_id}",
            status_code=404,
        )


class UserAlreadyExists(DomainError):
    def __init__(self, email: str) -> None:
        super().__init__(
            code="user_already_exists",
            message=f"User with email {email} already exists",
            status_code=409,
        )


class JobNotFound(DomainError):
    def __init__(self, job_id: str) -> None:
        super().__init__(
            code="job_not_found",
            message=f"Job {job_id} not found",
            status_code=404,
        )


class InvalidSignature(DomainError):
    def __init__(self, message: str = "Invalid signature") -> None:
        super().__init__(code="invalid_signature", message=message, status_code=400)


class FileTooLarge(DomainError):
    def __init__(self, limit: int) -> None:
        super().__init__(
            code="file_too_large",
            message=f"File exceeds the maximum allowed size of {limit} bytes",
            status_code=413,
        )


class UnsupportedMediaType(DomainError):
    def __init__(self, content_type: str | None) -> None:
        super().__init__(
            code="unsupported_media_type",
            message=f"Content type '{content_type}' is not allowed",
            status_code=415,
        )


class UploadNotFound(DomainError):
    def __init__(self, key: str) -> None:
        super().__init__(
            code="upload_not_found",
            message=f"Upload '{key}' not found",
            status_code=404,
        )


class StorageError(DomainError):
    def __init__(self, message: str = "Storage backend error") -> None:
        super().__init__(code="storage_error", message=message, status_code=502)


class UpstreamError(DomainError):
    def __init__(self, message: str = "Upstream service error") -> None:
        super().__init__(code="upstream_error", message=message, status_code=502)


class IntegrationNotConfigured(DomainError):
    def __init__(self, provider: str) -> None:
        super().__init__(
            code="integration_not_configured",
            message=f"Integration '{provider}' is not configured",
            status_code=503,
        )


class PaymentNotFound(DomainError):
    def __init__(self, payment_id: int) -> None:
        super().__init__(
            code="payment_not_found",
            message=f"Payment {payment_id} not found",
            status_code=404,
        )


class UnauthorizedError(DomainError):
    def __init__(self, message: str = "Unauthorized") -> None:
        super().__init__(code="unauthorized", message=message, status_code=401)


class PermissionDenied(DomainError):
    def __init__(self, message: str = "Forbidden") -> None:
        super().__init__(code="forbidden", message=message, status_code=403)
