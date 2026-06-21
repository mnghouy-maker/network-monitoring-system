"""Unit tests for the ping output parser (no network access)."""

from app.monitoring.ping import SubprocessPingCollector

_SUCCESS_OUTPUT = """\
PING 10.0.0.1 (10.0.0.1) 56(84) bytes of data.
64 bytes from 10.0.0.1: icmp_seq=1 ttl=64 time=0.512 ms
64 bytes from 10.0.0.1: icmp_seq=2 ttl=64 time=0.488 ms
64 bytes from 10.0.0.1: icmp_seq=3 ttl=64 time=0.600 ms

--- 10.0.0.1 ping statistics ---
3 packets transmitted, 3 received, 0% packet loss, time 2003ms
rtt min/avg/max/mdev = 0.488/0.533/0.600/0.048 ms
"""

_FAILURE_OUTPUT = """\
PING 10.0.0.9 (10.0.0.9) 56(84) bytes of data.

--- 10.0.0.9 ping statistics ---
3 packets transmitted, 0 received, 100% packet loss, time 2048ms
"""


def test_parse_loss_success() -> None:
    assert SubprocessPingCollector._parse_loss(_SUCCESS_OUTPUT) == 0.0


def test_parse_loss_failure() -> None:
    assert SubprocessPingCollector._parse_loss(_FAILURE_OUTPUT) == 100.0


def test_parse_avg_latency_success() -> None:
    avg = SubprocessPingCollector._parse_avg_latency(_SUCCESS_OUTPUT)
    assert avg is not None
    assert 0.5 <= avg <= 0.6


def test_parse_avg_latency_none_when_absent() -> None:
    assert SubprocessPingCollector._parse_avg_latency(_FAILURE_OUTPUT) is None
