"""Repository layer: encapsulates all database access."""

from app.repositories.alert import (
    AlertAcknowledgementRepository,
    AlertHistoryRepository,
    AlertRuleRepository,
)
from app.repositories.backup import (
    ConfigBackupRepository,
    ConnectionProfileRepository,
)
from app.repositories.device import DeviceRepository
from app.repositories.metric import MetricRepository
from app.repositories.server import ServerHealthRepository, ServerRepository
from app.repositories.telegram import (
    TelegramChatRepository,
    TelegramUserRepository,
)
from app.repositories.user import UserRepository

__all__ = [
    "UserRepository",
    "DeviceRepository",
    "MetricRepository",
    "AlertRuleRepository",
    "AlertHistoryRepository",
    "AlertAcknowledgementRepository",
    "TelegramUserRepository",
    "TelegramChatRepository",
    "ConnectionProfileRepository",
    "ConfigBackupRepository",
    "ServerRepository",
    "ServerHealthRepository",
]
