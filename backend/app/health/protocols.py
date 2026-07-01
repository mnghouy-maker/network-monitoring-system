"""Health sample DTO and the collector protocol."""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(slots=True)
class HealthSample:
    """System health gauges from one collection. Fields may be ``None``."""

    reachable: bool = True
    cpu_percent: float | None = None
    memory_percent: float | None = None
    disk_percent: float | None = None
    load1: float | None = None
    load5: float | None = None
    load15: float | None = None
    uptime_seconds: int | None = None


@dataclass(slots=True)
class HealthTarget:
    """Resolved connection details for a server health check."""

    hostname: str
    ssh_port: int = 22
    ssh_username: str | None = None
    ssh_password: str | None = None
    timeout: float = 15.0


@runtime_checkable
class HealthCollector(Protocol):
    """Collects system health for a server."""

    async def collect(self, target: HealthTarget) -> HealthSample: ...
