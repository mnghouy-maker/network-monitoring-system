"""Unit tests for the monitoring service orchestration."""

import uuid

import pytest

from app.models.device import Device
from app.models.metric import MetricSource
from app.monitoring.exceptions import CollectorConfigurationError
from app.monitoring.types import InterfaceSample, MetricSample, PingResult
from app.services.exceptions import EntityNotFoundError, MonitoringError
from app.services.monitoring import MonitoringService
from tests.conftest import (
    FakeDeviceRepository,
    FakeMetricCollector,
    FakeMetricRepository,
    FakePingCollector,
)


async def _make_device(repo: FakeDeviceRepository) -> Device:
    return await repo.add(Device(name="rtr-1", hostname="10.0.0.1"))


def _reachable() -> PingResult:
    return PingResult(reachable=True, latency_ms=1.5, packet_loss_percent=0.0)


@pytest.mark.asyncio
async def test_poll_device_persists_snapshot(
    fake_device_repo: FakeDeviceRepository,
    fake_metric_repo: FakeMetricRepository,
) -> None:
    device = await _make_device(fake_device_repo)
    sample = MetricSample(
        cpu_load_percent=12.5,
        memory_used_percent=40.0,
        uptime_seconds=3600,
        interfaces=[
            InterfaceSample(name="Gi0/1", if_index=1, oper_status="up"),
        ],
    )
    service = MonitoringService(
        fake_device_repo,  # type: ignore[arg-type]
        fake_metric_repo,  # type: ignore[arg-type]
        FakePingCollector(_reachable()),
        FakeMetricCollector(sample=sample),
    )

    metric = await service.poll_device(device)

    assert metric.source is MetricSource.SNMP
    assert metric.reachable is True
    assert metric.latency_ms == 1.5
    assert metric.cpu_load_percent == 12.5
    assert metric.memory_used_percent == 40.0
    assert metric.uptime_seconds == 3600
    assert len(metric.interfaces) == 1
    assert metric.interfaces[0].name == "Gi0/1"
    # Persisted and retrievable as the latest snapshot.
    latest = await service.get_latest(device.id)
    assert latest is metric


@pytest.mark.asyncio
async def test_poll_uses_zabbix_when_requested(
    fake_device_repo: FakeDeviceRepository,
    fake_metric_repo: FakeMetricRepository,
) -> None:
    device = await _make_device(fake_device_repo)
    snmp = FakeMetricCollector(sample=MetricSample(cpu_load_percent=1.0))
    zabbix = FakeMetricCollector(sample=MetricSample(cpu_load_percent=99.0))
    service = MonitoringService(
        fake_device_repo,  # type: ignore[arg-type]
        fake_metric_repo,  # type: ignore[arg-type]
        FakePingCollector(_reachable()),
        snmp,
        zabbix_collector=zabbix,
    )

    metric = await service.poll_device(device, source=MetricSource.ZABBIX)

    assert metric.source is MetricSource.ZABBIX
    assert metric.cpu_load_percent == 99.0
    assert zabbix.calls and not snmp.calls


@pytest.mark.asyncio
async def test_zabbix_requested_but_unconfigured_raises(
    fake_device_repo: FakeDeviceRepository,
    fake_metric_repo: FakeMetricRepository,
) -> None:
    device = await _make_device(fake_device_repo)
    service = MonitoringService(
        fake_device_repo,  # type: ignore[arg-type]
        fake_metric_repo,  # type: ignore[arg-type]
        FakePingCollector(_reachable()),
        FakeMetricCollector(),
        zabbix_collector=None,
    )
    with pytest.raises(MonitoringError):
        await service.poll_device(device, source=MetricSource.ZABBIX)


@pytest.mark.asyncio
async def test_collector_failure_degrades_gracefully(
    fake_device_repo: FakeDeviceRepository,
    fake_metric_repo: FakeMetricRepository,
) -> None:
    device = await _make_device(fake_device_repo)
    service = MonitoringService(
        fake_device_repo,  # type: ignore[arg-type]
        fake_metric_repo,  # type: ignore[arg-type]
        FakePingCollector(PingResult(reachable=False, packet_loss_percent=100.0)),
        FakeMetricCollector(error=RuntimeError("snmp timeout")),
    )

    metric = await service.poll_device(device)

    # Ping result is recorded; gauges are null because collection failed.
    assert metric.reachable is False
    assert metric.packet_loss_percent == 100.0
    assert metric.cpu_load_percent is None
    assert metric.interfaces == []


@pytest.mark.asyncio
async def test_collector_configuration_error_becomes_monitoring_error(
    fake_device_repo: FakeDeviceRepository,
    fake_metric_repo: FakeMetricRepository,
) -> None:
    # A configuration error (e.g. missing zabbix_host_id / SNMPv3) must surface
    # as MonitoringError (-> HTTP 400), not be silently degraded to a snapshot.
    device = await _make_device(fake_device_repo)
    zabbix = FakeMetricCollector(
        error=CollectorConfigurationError("no zabbix_host_id")
    )
    service = MonitoringService(
        fake_device_repo,  # type: ignore[arg-type]
        fake_metric_repo,  # type: ignore[arg-type]
        FakePingCollector(_reachable()),
        FakeMetricCollector(),
        zabbix_collector=zabbix,
    )
    with pytest.raises(MonitoringError):
        await service.poll_device(device, source=MetricSource.ZABBIX)


@pytest.mark.asyncio
async def test_get_latest_unknown_device_raises(
    fake_device_repo: FakeDeviceRepository,
    fake_metric_repo: FakeMetricRepository,
) -> None:
    service = MonitoringService(
        fake_device_repo,  # type: ignore[arg-type]
        fake_metric_repo,  # type: ignore[arg-type]
        FakePingCollector(_reachable()),
        FakeMetricCollector(),
    )
    with pytest.raises(EntityNotFoundError):
        await service.get_latest(uuid.uuid4())
    with pytest.raises(EntityNotFoundError):
        await service.get_history(uuid.uuid4())


@pytest.mark.asyncio
async def test_poll_by_id_missing_device_raises(
    fake_device_repo: FakeDeviceRepository,
    fake_metric_repo: FakeMetricRepository,
) -> None:
    service = MonitoringService(
        fake_device_repo,  # type: ignore[arg-type]
        fake_metric_repo,  # type: ignore[arg-type]
        FakePingCollector(_reachable()),
        FakeMetricCollector(),
    )
    with pytest.raises(EntityNotFoundError):
        await service.poll_device_by_id(uuid.uuid4())


@pytest.mark.asyncio
async def test_poll_all_active_skips_failures(
    fake_device_repo: FakeDeviceRepository,
    fake_metric_repo: FakeMetricRepository,
) -> None:
    await fake_device_repo.add(Device(name="a", hostname="10.0.0.1"))
    await fake_device_repo.add(Device(name="b", hostname="10.0.0.2"))
    service = MonitoringService(
        fake_device_repo,  # type: ignore[arg-type]
        fake_metric_repo,  # type: ignore[arg-type]
        FakePingCollector(_reachable()),
        FakeMetricCollector(),
    )
    results = await service.poll_all_active()
    assert len(results) == 2
