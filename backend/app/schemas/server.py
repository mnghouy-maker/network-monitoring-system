"""Server health monitoring schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.server import ServerHealthStatus, ServerMonitorMethod


class ServerBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    hostname: str = Field(min_length=1, max_length=255)
    description: str | None = None
    monitor_method: ServerMonitorMethod = ServerMonitorMethod.LOCAL
    ssh_port: int = Field(default=22, ge=1, le=65535)
    ssh_username: str | None = Field(default=None, max_length=255)
    is_active: bool = True


class ServerCreate(ServerBase):
    ssh_password: str | None = None


class ServerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    hostname: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    monitor_method: ServerMonitorMethod | None = None
    ssh_port: int | None = Field(default=None, ge=1, le=65535)
    ssh_username: str | None = Field(default=None, max_length=255)
    ssh_password: str | None = None
    is_active: bool | None = None


class ServerOut(ServerBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    has_ssh_password: bool
    created_at: datetime
    updated_at: datetime


class ServerHealthOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    server_id: uuid.UUID
    collected_at: datetime
    reachable: bool
    status: ServerHealthStatus
    cpu_percent: float | None
    memory_percent: float | None
    disk_percent: float | None
    load1: float | None
    load5: float | None
    load15: float | None
    uptime_seconds: int | None
    error: str | None
