"""Configuration backup schemas (request/response contracts)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.backup import (
    BackupStatus,
    ConfigType,
    ConnectionMethod,
)


class ConnectionProfileUpsert(BaseModel):
    """Create/replace a device's SSH connection profile."""

    method: ConnectionMethod = ConnectionMethod.NAPALM
    platform: str = Field(
        min_length=1,
        max_length=64,
        description="NAPALM driver (ios/eos/junos/...) or Netmiko device_type",
    )
    ssh_port: int = Field(default=22, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1)
    enable_secret: str | None = None
    is_active: bool = True


class ConnectionProfileOut(BaseModel):
    """Connection profile without any secret material."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    device_id: uuid.UUID
    method: ConnectionMethod
    platform: str
    ssh_port: int
    username: str
    has_enable_secret: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ConfigBackupOut(BaseModel):
    """Backup metadata (no config body)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    device_id: uuid.UUID
    config_type: ConfigType
    method: ConnectionMethod
    status: BackupStatus
    content_hash: str | None
    size_bytes: int | None
    error: str | None
    created_at: datetime


class ConfigBackupContentOut(ConfigBackupOut):
    """Backup including the full configuration text."""

    content: str | None


class ConfigDiffOut(BaseModel):
    """Unified diff between two backups."""

    from_backup_id: uuid.UUID
    to_backup_id: uuid.UUID
    changed: bool
    diff: str
