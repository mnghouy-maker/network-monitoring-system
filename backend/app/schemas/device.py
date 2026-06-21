"""Device inventory schemas (request/response contracts)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.device import DeviceCategory, SNMPVersion


class DeviceBase(BaseModel):
    """Fields shared across create/update/read schemas."""

    name: str = Field(min_length=1, max_length=255)
    hostname: str = Field(
        min_length=1, max_length=255, description="IP address or DNS name"
    )
    category: DeviceCategory = DeviceCategory.OTHER
    vendor: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=100)
    location: str | None = Field(default=None, max_length=255)
    description: str | None = None

    snmp_community: str = Field(default="public", max_length=255)
    snmp_version: SNMPVersion = SNMPVersion.V2C
    snmp_port: int = Field(default=161, ge=1, le=65535)
    zabbix_host_id: str | None = Field(default=None, max_length=64)
    is_active: bool = True


class DeviceCreate(DeviceBase):
    """Payload for registering a new device."""


class DeviceUpdate(BaseModel):
    """Partial update payload. All fields optional."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    hostname: str | None = Field(default=None, min_length=1, max_length=255)
    category: DeviceCategory | None = None
    vendor: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=100)
    location: str | None = Field(default=None, max_length=255)
    description: str | None = None
    snmp_community: str | None = Field(default=None, max_length=255)
    snmp_version: SNMPVersion | None = None
    snmp_port: int | None = Field(default=None, ge=1, le=65535)
    zabbix_host_id: str | None = Field(default=None, max_length=64)
    is_active: bool | None = None


class DeviceOut(DeviceBase):
    """Device representation returned to clients.

    ``snmp_community`` is intentionally excluded so a read-only secret is not
    leaked in listings.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    # Hide the SNMP community string from responses.
    snmp_community: str = Field(default="public", exclude=True)
