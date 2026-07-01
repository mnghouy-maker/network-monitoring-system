"""Unit tests for the SSH health output parser (no network)."""

from app.health.ssh import SshHealthCollector

_OUTPUT = """\
cpu=12.5
mem=8000000000 4000000000
disk=100000000 80000000
load=0.50 0.75 1.00
uptime=123456.78
"""


def test_parse_full_output() -> None:
    sample = SshHealthCollector.parse_output(_OUTPUT)
    assert sample.reachable is True
    assert sample.cpu_percent == 12.5
    assert sample.memory_percent == 50.0  # 4e9 / 8e9
    assert sample.disk_percent == 80.0  # 8e7 / 1e8
    assert (sample.load1, sample.load5, sample.load15) == (0.5, 0.75, 1.0)
    assert sample.uptime_seconds == 123456


def test_parse_partial_output_is_tolerant() -> None:
    sample = SshHealthCollector.parse_output("cpu=5.0\nmem=bad data here")
    assert sample.cpu_percent == 5.0
    assert sample.memory_percent is None
    assert sample.disk_percent is None


def test_parse_empty_output() -> None:
    sample = SshHealthCollector.parse_output("")
    assert sample.reachable is True
    assert sample.cpu_percent is None
