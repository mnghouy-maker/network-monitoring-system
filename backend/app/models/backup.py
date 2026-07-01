"""Configuration backup models: device connection profiles and config backups."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, pg_enum


class ConnectionMethod(enum.StrEnum):
    """Automation library used to reach a device over SSH."""

    NAPALM = "napalm"
    NETMIKO = "netmiko"


class ConfigType(enum.StrEnum):
    """Which configuration to retrieve."""

    RUNNING = "running"
    STARTUP = "startup"


class BackupStatus(enum.StrEnum):
    """Outcome of a backup attempt."""

    SUCCESS = "success"
    FAILED = "failed"


class DeviceConnectionProfile(Base, TimestampMixin):
    """SSH connection settings and (encrypted) credentials for a device.

    Kept separate from :class:`~app.models.device.Device` so Phase 2 stays
    untouched and secrets live in one place. Passwords are stored encrypted at
    rest and never serialized back to clients.
    """

    __tablename__ = "device_connection_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("devices.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    method: Mapped[ConnectionMethod] = mapped_column(
        pg_enum(ConnectionMethod, "connection_method"),
        default=ConnectionMethod.NAPALM,
        nullable=False,
    )
    # NAPALM driver (e.g. "ios", "eos", "junos") or Netmiko device_type
    # (e.g. "cisco_ios") — depends on ``method``.
    platform: Mapped[str] = mapped_column(String(64), nullable=False)
    ssh_port: Mapped[int] = mapped_column(Integer, default=22, nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    password_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    enable_secret_encrypted: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )

    @property
    def has_enable_secret(self) -> bool:
        return self.enable_secret_encrypted is not None

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<DeviceConnectionProfile device_id={self.device_id} "
            f"method={self.method} platform={self.platform!r}>"
        )


class ConfigBackup(Base):
    """A stored configuration snapshot (or a failed attempt) for a device."""

    __tablename__ = "config_backups"
    __table_args__ = (
        Index("ix_config_backups_device_type", "device_id", "config_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    config_type: Mapped[ConfigType] = mapped_column(
        pg_enum(ConfigType, "config_type"),
        default=ConfigType.RUNNING,
        nullable=False,
    )
    method: Mapped[ConnectionMethod] = mapped_column(
        pg_enum(ConnectionMethod, "connection_method"), nullable=False
    )
    status: Mapped[BackupStatus] = mapped_column(
        pg_enum(BackupStatus, "backup_status"), nullable=False
    )
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    device: Mapped["object"] = relationship(  # type: ignore[assignment]
        "Device", viewonly=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<ConfigBackup device_id={self.device_id} "
            f"type={self.config_type} status={self.status}>"
        )
