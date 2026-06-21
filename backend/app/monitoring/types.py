"""Plain data-transfer objects exchanged between collectors and services.

These are deliberately framework-agnostic dataclasses (not Pydantic models or
ORM rows) so collectors stay decoupled from persistence and HTTP concerns.
"""

from dataclasses import dataclass, field


@dataclass(slots=True)
class PingResult:
    """Outcome of an ICMP reachability check."""

    reachable: bool
    latency_ms: float | None = None
    packet_loss_percent: float | None = None


@dataclass(slots=True)
class InterfaceSample:
    """A single network interface's counters at poll time."""

    name: str
    if_index: int | None = None
    oper_status: str | None = None
    speed_bps: int | None = None
    in_octets: int | None = None
    out_octets: int | None = None
    in_errors: int | None = None
    out_errors: int | None = None


@dataclass(slots=True)
class MetricSample:
    """Health gauges plus interface statistics from a single collection.

    Any field may be ``None`` if the device did not expose it or the poll
    partially failed; the caller decides how to persist/interpret gaps.
    """

    cpu_load_percent: float | None = None
    memory_used_percent: float | None = None
    uptime_seconds: int | None = None
    interfaces: list[InterfaceSample] = field(default_factory=list)
