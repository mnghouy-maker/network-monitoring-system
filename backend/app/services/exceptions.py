"""Domain-level exceptions.

These are raised by the service layer and translated into HTTP responses by
exception handlers / endpoints. Keeping them framework-agnostic means the
business logic does not import FastAPI.
"""


class ServiceError(Exception):
    """Base class for all service-layer errors."""


class EntityAlreadyExistsError(ServiceError):
    """Raised when a uniqueness constraint would be violated."""


class EntityNotFoundError(ServiceError):
    """Raised when a requested entity does not exist."""


class InvalidCredentialsError(ServiceError):
    """Raised when authentication fails."""


class InactiveUserError(ServiceError):
    """Raised when an inactive user attempts to authenticate."""


class MonitoringError(ServiceError):
    """Raised when a monitoring poll cannot be performed as requested."""


class AlertError(ServiceError):
    """Raised when an alert operation (e.g. acknowledgement) is invalid."""


class BackupError(ServiceError):
    """Raised when a configuration backup cannot be performed as requested."""


class AIError(ServiceError):
    """Raised when the AI troubleshooting assistant cannot answer a request."""
