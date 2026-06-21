"""Monitoring infrastructure: pluggable collectors for ping, SNMP and Zabbix.

Collectors are defined as Protocols so the service layer depends on behaviour,
not concrete libraries. The heavy third-party clients (pysnmp, httpx) are
imported lazily inside the concrete implementations, keeping module import
cheap and the unit tests independent of those libraries.
"""

from app.monitoring.protocols import MetricCollector, PingCollector
from app.monitoring.types import InterfaceSample, MetricSample, PingResult

__all__ = [
    "MetricCollector",
    "PingCollector",
    "InterfaceSample",
    "MetricSample",
    "PingResult",
]
