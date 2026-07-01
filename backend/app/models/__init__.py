"""SQLAlchemy models.

Importing the models here ensures they are registered on ``Base.metadata``
when this package is imported (e.g. by Alembic's ``env.py``).
"""

from app.models.alert import (
    AlertAcknowledgement,
    AlertHistory,
    AlertRule,
    AlertSeverity,
    AlertStatus,
    AlertType,
)
from app.models.backup import (
    BackupStatus,
    ConfigBackup,
    ConfigType,
    ConnectionMethod,
    DeviceConnectionProfile,
)
from app.models.device import Device, DeviceCategory, SNMPVersion
from app.models.metric import DeviceMetric, InterfaceStat, MetricSource
from app.models.server import (
    Server,
    ServerHealthCheck,
    ServerHealthStatus,
    ServerMonitorMethod,
)
from app.models.telegram import ChatType, TelegramChat, TelegramUser
from app.models.user import User, UserRole

__all__ = [
    "User",
    "UserRole",
    "Device",
    "DeviceCategory",
    "SNMPVersion",
    "DeviceMetric",
    "InterfaceStat",
    "MetricSource",
    "AlertRule",
    "AlertHistory",
    "AlertAcknowledgement",
    "AlertType",
    "AlertSeverity",
    "AlertStatus",
    "TelegramUser",
    "TelegramChat",
    "ChatType",
    "DeviceConnectionProfile",
    "ConfigBackup",
    "ConnectionMethod",
    "ConfigType",
    "BackupStatus",
    "Server",
    "ServerHealthCheck",
    "ServerMonitorMethod",
    "ServerHealthStatus",
]
