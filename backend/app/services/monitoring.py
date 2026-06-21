"""Monitoring service: orchestrate collectors and persist snapshots.

The service is collector-agnostic: it receives a ping collector plus SNMP and
Zabbix metric collectors (all behind protocols) and decides, per poll, which to
use. Reachability is always probed; health/interface gauges come from the
requested source. A collector failure degrades gracefully to a snapshot with
null gauges rather than aborting the poll.
"""

import logging
import uuid

from app.models.device import Device
from app.models.metric import DeviceMetric, InterfaceStat, MetricSource
from app.monitoring.protocols import MetricCollector, PingCollector
from app.monitoring.types import MetricSample
from app.repositories.device import DeviceRepository
from app.repositories.metric import MetricRepository
from app.services.exceptions import EntityNotFoundError, MonitoringError

logger = logging.getLogger(__name__)


class MonitoringService:
    """Polls devices and stores the resulting metric snapshots."""

    def __init__(
        self,
        device_repo: DeviceRepository,
        metric_repo: MetricRepository,
        ping_collector: PingCollector,
        snmp_collector: MetricCollector,
        zabbix_collector: MetricCollector | None = None,
    ) -> None:
        self._devices = device_repo
        self._metrics = metric_repo
        self._ping = ping_collector
        self._snmp = snmp_collector
        self._zabbix = zabbix_collector

    def _collector_for(self, source: MetricSource) -> MetricCollector:
        if source is MetricSource.ZABBIX:
            if self._zabbix is None:
                raise MonitoringError("Zabbix collector is not configured")
            return self._zabbix
        return self._snmp

    async def poll_device(
        self, device: Device, source: MetricSource = MetricSource.SNMP
    ) -> DeviceMetric:
        """Probe ``device`` and persist a new metric snapshot."""
        ping_result = await self._ping.ping(device.hostname)

        sample = MetricSample()
        collector = self._collector_for(source)
        try:
            sample = await collector.collect(device)
        except MonitoringError:
            raise
        except Exception as exc:  # noqa: BLE001 - degrade gracefully
            logger.warning(
                "Metric collection (%s) failed for %s: %s",
                source,
                device.name,
                exc,
            )

        metric = DeviceMetric(
            device_id=device.id,
            source=source,
            reachable=ping_result.reachable,
            latency_ms=ping_result.latency_ms,
            packet_loss_percent=ping_result.packet_loss_percent,
            cpu_load_percent=sample.cpu_load_percent,
            memory_used_percent=sample.memory_used_percent,
            uptime_seconds=sample.uptime_seconds,
        )
        metric.interfaces = [
            InterfaceStat(
                if_index=iface.if_index,
                name=iface.name,
                oper_status=iface.oper_status,
                speed_bps=iface.speed_bps,
                in_octets=iface.in_octets,
                out_octets=iface.out_octets,
                in_errors=iface.in_errors,
                out_errors=iface.out_errors,
            )
            for iface in sample.interfaces
        ]
        return await self._metrics.add(metric)

    async def poll_device_by_id(
        self, device_id: uuid.UUID, source: MetricSource = MetricSource.SNMP
    ) -> DeviceMetric:
        device = await self._devices.get(device_id)
        if device is None:
            raise EntityNotFoundError(f"Device {device_id} not found")
        return await self.poll_device(device, source=source)

    async def poll_all_active(
        self, source: MetricSource = MetricSource.SNMP
    ) -> list[DeviceMetric]:
        """Poll every active device. Failures on one device don't stop others."""
        results: list[DeviceMetric] = []
        for device in await self._devices.list_active():
            try:
                results.append(await self.poll_device(device, source=source))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Polling %s failed: %s", device.name, exc)
        return results

    async def get_latest(self, device_id: uuid.UUID) -> DeviceMetric | None:
        return await self._metrics.get_latest(device_id)

    async def get_history(
        self, device_id: uuid.UUID, *, skip: int = 0, limit: int = 100
    ) -> list[DeviceMetric]:
        return await self._metrics.list_history(
            device_id, skip=skip, limit=limit
        )
