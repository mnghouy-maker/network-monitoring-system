"""Unit tests for server health classification and polling."""

import uuid

import pytest

from app.health.protocols import HealthSample
from app.models.server import (
    Server,
    ServerHealthStatus,
    ServerMonitorMethod,
)
from app.services.server_health import (
    HealthThresholds,
    ServerHealthService,
    classify_health,
)
from tests.conftest import (
    FakeHealthCollector,
    FakeServerHealthRepository,
    FakeServerRepository,
)

_TH = HealthThresholds(
    cpu_warn=80,
    cpu_crit=95,
    memory_warn=80,
    memory_crit=95,
    disk_warn=80,
    disk_crit=95,
)


def test_classify_healthy() -> None:
    sample = HealthSample(cpu_percent=10, memory_percent=20, disk_percent=30)
    assert classify_health(sample, _TH) is ServerHealthStatus.HEALTHY


def test_classify_warning() -> None:
    sample = HealthSample(cpu_percent=85, memory_percent=20, disk_percent=30)
    assert classify_health(sample, _TH) is ServerHealthStatus.WARNING


def test_classify_critical_takes_precedence() -> None:
    sample = HealthSample(cpu_percent=85, memory_percent=99, disk_percent=30)
    assert classify_health(sample, _TH) is ServerHealthStatus.CRITICAL


def test_classify_unreachable() -> None:
    assert (
        classify_health(HealthSample(reachable=False), _TH)
        is ServerHealthStatus.UNREACHABLE
    )


def test_missing_gauges_are_ignored() -> None:
    sample = HealthSample(cpu_percent=None, memory_percent=None, disk_percent=None)
    assert classify_health(sample, _TH) is ServerHealthStatus.HEALTHY


async def _service(collector: FakeHealthCollector):
    servers = FakeServerRepository()
    health = FakeServerHealthRepository()
    server = await servers.add(
        Server(
            name="app-1",
            hostname="10.0.0.5",
            monitor_method=ServerMonitorMethod.LOCAL,
        )
    )
    service = ServerHealthService(
        server_repo=servers,
        health_repo=health,
        local_collector=collector,
        ssh_collector=collector,
        thresholds=_TH,
    )
    return service, server, health


@pytest.mark.asyncio
async def test_poll_stores_snapshot_with_status() -> None:
    service, server, health = await _service(
        FakeHealthCollector(
            HealthSample(cpu_percent=96, memory_percent=10, disk_percent=10)
        )
    )
    check = await service.poll_server(server)
    assert check.status is ServerHealthStatus.CRITICAL
    assert check.cpu_percent == 96
    latest = await service.get_latest(server.id)
    assert latest is check


@pytest.mark.asyncio
async def test_poll_collector_error_marks_unreachable() -> None:
    service, server, _health = await _service(
        FakeHealthCollector(error=RuntimeError("ssh refused"))
    )
    check = await service.poll_server(server)
    assert check.reachable is False
    assert check.status is ServerHealthStatus.UNREACHABLE
    assert "ssh refused" in check.error


@pytest.mark.asyncio
async def test_history_unknown_server_raises() -> None:
    service, _server, _health = await _service(FakeHealthCollector())
    from app.services.exceptions import EntityNotFoundError

    with pytest.raises(EntityNotFoundError):
        await service.get_history(uuid.uuid4())
