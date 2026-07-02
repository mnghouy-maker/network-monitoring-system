"""Pydantic schemas (request/response contracts)."""

from app.schemas.ai import (
    AIChatRequest,
    AIDiagnoseRequest,
    AIMessageOut,
    AISessionCreate,
    AISessionDetailOut,
    AISessionOut,
)
from app.schemas.device import DeviceCreate, DeviceOut, DeviceUpdate
from app.schemas.metric import DeviceMetricOut, InterfaceStatOut
from app.schemas.token import Token, TokenPayload, TokenRefreshRequest
from app.schemas.user import (
    UserCreate,
    UserOut,
    UserUpdate,
)

__all__ = [
    "Token",
    "TokenPayload",
    "TokenRefreshRequest",
    "UserCreate",
    "UserOut",
    "UserUpdate",
    "DeviceCreate",
    "DeviceOut",
    "DeviceUpdate",
    "DeviceMetricOut",
    "InterfaceStatOut",
    "AISessionCreate",
    "AISessionOut",
    "AISessionDetailOut",
    "AIMessageOut",
    "AIChatRequest",
    "AIDiagnoseRequest",
]
