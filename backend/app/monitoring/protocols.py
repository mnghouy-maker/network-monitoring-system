"""Collector protocols (interfaces) used by the monitoring service."""

from typing import Protocol, runtime_checkable

from app.models.device import Device
from app.monitoring.types import MetricSample, PingResult


@runtime_checkable
class PingCollector(Protocol):
    """Checks ICMP reachability of a host."""

    async def ping(self, host: str) -> PingResult: ...


@runtime_checkable
class MetricCollector(Protocol):
    """Collects health gauges and interface statistics for a device.

    Implemented by both the SNMP and Zabbix collectors so the monitoring
    service can treat them interchangeably.
    """

    async def collect(self, device: Device) -> MetricSample: ...
