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


class UnauthorizedError(DomainError):
    def __init__(self, message: str = "Unauthorized") -> None:
        super().__init__(code="unauthorized", message=message, status_code=401)


class PermissionDenied(DomainError):
    def __init__(self, message: str = "Forbidden") -> None:
        super().__init__(code="forbidden", message=message, status_code=403)
