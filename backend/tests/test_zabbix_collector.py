"""Unit tests for the Zabbix collector's item-mapping logic (no network)."""

import pytest

from app.monitoring.zabbix import ZabbixMetricCollector


def _collector() -> ZabbixMetricCollector:
    return ZabbixMetricCollector(
        url="http://zbx.example", user="Admin", password="zabbix"
    )


def test_is_configured() -> None:
    assert _collector().is_configured is True
    assert ZabbixMetricCollector(None, None, None).is_configured is False


def test_map_items_extracts_gauges_and_interfaces() -> None:
    items = [
        {"key_": "system.cpu.util[,idle]", "lastvalue": "12.5"},
        {"key_": "vm.memory.utilization", "lastvalue": "40"},
        {"key_": "system.uptime", "lastvalue": "3600"},
        {"key_": "net.if.in[eth0]", "lastvalue": "1000"},
        {"key_": "net.if.out[eth0]", "lastvalue": "2000"},
        {"key_": "net.if.in[eth1]", "lastvalue": "5"},
        {"key_": "some.other.key", "lastvalue": "999"},
    ]
    sample = _collector()._map_items(items)

    assert sample.cpu_load_percent == 12.5
    assert sample.memory_used_percent == 40.0
    assert sample.uptime_seconds == 3600
    by_name = {i.name: i for i in sample.interfaces}
    assert by_name["eth0"].in_octets == 1000
    assert by_name["eth0"].out_octets == 2000
    assert by_name["eth1"].in_octets == 5
    assert by_name["eth1"].out_octets is None


def test_map_items_ignores_empty_values() -> None:
    sample = _collector()._map_items(
        [{"key_": "system.cpu.util", "lastvalue": ""}]
    )
    assert sample.cpu_load_percent is None


@pytest.mark.parametrize(
    "key,expected",
    [
        ("net.if.in[eth0]", "eth0"),
        ("net.if.out[GigabitEthernet0/1,bytes]", "GigabitEthernet0/1"),
        ("net.if.in", "net.if.in"),
    ],
)
def test_iface_name(key: str, expected: str) -> None:
    assert ZabbixMetricCollector._iface_name(key) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [("3.14", 3.14), ("", None), (None, None), ("abc", None), (10, 10.0)],
)
def test_to_float(raw: object, expected: float | None) -> None:
    assert ZabbixMetricCollector._to_float(raw) == expected
