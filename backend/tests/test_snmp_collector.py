"""Unit tests for the SNMP collector mapping, version handling and timeouts.

A fake puresnmp-style client is injected via ``client_factory`` so the logic is
exercised without a live agent or the ``puresnmp`` dependency.
"""

import asyncio

import pytest

from app.models.device import Device, SNMPVersion
from app.monitoring.exceptions import CollectorConfigurationError
from app.monitoring.snmp import (
    _OID_HR_PROCESSOR_LOAD,
    _OID_IF_DESCR,
    _OID_IF_HC_IN_OCTETS,
    _OID_IF_HIGH_SPEED,
    _OID_IF_OPER_STATUS,
    _OID_SYS_UPTIME,
    _OID_UCD_MEM_AVAIL,
    _OID_UCD_MEM_TOTAL,
    SnmpMetricCollector,
)


class _VarBind:
    def __init__(self, oid: str, value: object) -> None:
        self.oid = oid
        self.value = value


class FakeSnmpClient:
    """Minimal stand-in for a ``puresnmp`` ``PyWrapper`` client."""

    def __init__(
        self,
        scalars: dict[str, object],
        tables: dict[str, dict[int, object]],
        delay: float = 0.0,
    ) -> None:
        self._scalars = scalars
        self._tables = tables
        self._delay = delay
        self.get_calls = 0

    async def get(self, oid: str) -> object:
        self.get_calls += 1
        if self._delay:
            await asyncio.sleep(self._delay)
        if oid in self._scalars:
            return self._scalars[oid]
        raise ValueError(f"no such oid {oid}")

    async def walk(self, base_oid: str):
        if self._delay:
            await asyncio.sleep(self._delay)
        for index, value in self._tables.get(base_oid, {}).items():
            yield _VarBind(f"{base_oid}.{index}", value)


def _device(version: SNMPVersion = SNMPVersion.V2C) -> Device:
    return Device(name="d", hostname="10.0.0.1", snmp_version=version)


def _healthy_client(delay: float = 0.0) -> FakeSnmpClient:
    return FakeSnmpClient(
        scalars={
            _OID_UCD_MEM_TOTAL: 1000,
            _OID_UCD_MEM_AVAIL: 250,
            _OID_SYS_UPTIME: 12345,  # ticks (1/100 s) -> 123 s
        },
        tables={
            _OID_HR_PROCESSOR_LOAD: {1: 10, 2: 20},
            _OID_IF_DESCR: {1: b"eth0", 2: b"eth1"},
            _OID_IF_OPER_STATUS: {1: 1, 2: 2},
            _OID_IF_HIGH_SPEED: {1: 1000, 2: 100},
            _OID_IF_HC_IN_OCTETS: {1: 5000},
        },
        delay=delay,
    )


@pytest.mark.asyncio
async def test_collect_maps_all_metrics() -> None:
    client = _healthy_client()
    collector = SnmpMetricCollector(client_factory=lambda d: client)

    sample = await collector.collect(_device())

    assert sample.cpu_load_percent == 15.0  # mean(10, 20)
    assert sample.memory_used_percent == 75.0  # (1000-250)/1000
    assert sample.uptime_seconds == 123  # 12345 // 100
    by_name = {i.name: i for i in sample.interfaces}
    assert by_name["eth0"].oper_status == "up"
    assert by_name["eth0"].speed_bps == 1000 * 1_000_000
    assert by_name["eth0"].in_octets == 5000
    assert by_name["eth1"].oper_status == "down"


@pytest.mark.asyncio
async def test_snmp_v1_is_allowed() -> None:
    client = _healthy_client()
    collector = SnmpMetricCollector(client_factory=lambda d: client)
    sample = await collector.collect(_device(SNMPVersion.V1))
    assert sample.uptime_seconds == 123


@pytest.mark.asyncio
async def test_snmp_v3_raises_configuration_error() -> None:
    # v3 is rejected before any client is built (no factory call needed).
    collector = SnmpMetricCollector(
        client_factory=lambda d: pytest.fail("client must not be built")
    )
    with pytest.raises(CollectorConfigurationError):
        await collector.collect(_device(SNMPVersion.V3))


@pytest.mark.asyncio
async def test_timeout_bounds_each_op_and_retries() -> None:
    # Client always sleeps longer than the timeout -> every read times out,
    # the collector degrades to nulls instead of hanging, and retries fire.
    client = _healthy_client(delay=0.2)
    collector = SnmpMetricCollector(
        timeout_seconds=0.01,
        retries=1,
        client_factory=lambda d: client,
    )

    sample = await asyncio.wait_for(collector.collect(_device()), timeout=2.0)

    assert sample.cpu_load_percent is None
    assert sample.memory_used_percent is None
    assert sample.uptime_seconds is None
    assert sample.interfaces == []
    # uptime alone retries (retries + 1) = 2 attempts; memory adds more.
    assert client.get_calls >= 2
