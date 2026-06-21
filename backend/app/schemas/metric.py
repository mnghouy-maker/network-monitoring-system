"""Monitoring metric schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.metric import MetricSource


class InterfaceStatOut(BaseModel):
    """Per-interface statistics returned to clients."""

    model_config = ConfigDict(from_attributes=True)

    if_index: int | None = None
    name: str
    oper_status: str | None = None
    speed_bps: int | None = None
    in_octets: int | None = None
    out_octets: int | None = None
    in_errors: int | None = None
    out_errors: int | None = None


class DeviceMetricOut(BaseModel):
    """A monitoring snapshot returned to clients."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    device_id: uuid.UUID
    collected_at: datetime
    source: MetricSource
    reachable: bool
    latency_ms: float | None = None
    packet_loss_percent: float | None = None
    cpu_load_percent: float | None = None
    memory_used_percent: float | None = None
    uptime_seconds: int | None = None
    interfaces: list[InterfaceStatOut] = []
