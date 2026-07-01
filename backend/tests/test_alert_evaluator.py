"""Unit tests for the pure alert evaluation logic."""

from datetime import UTC, datetime, timedelta

from app.models.alert import AlertRule, AlertType
from app.models.device import Device
from app.models.metric import DeviceMetric, InterfaceStat
from app.services.alerting import AlertEvaluator

_DEFAULTS = {
    AlertType.HIGH_CPU: 90.0,
    AlertType.HIGH_MEMORY: 90.0,
    AlertType.HIGH_DISK: 90.0,
    AlertType.HIGH_INTERFACE_UTIL: 90.0,
    AlertType.PACKET_LOSS: 20.0,
}

_DEVICE = Device(name="rtr-1", hostname="10.0.0.1")


def _evaluator() -> AlertEvaluator:
    return AlertEvaluator(_DEFAULTS)


def _rule(alert_type: AlertType, threshold: float | None = None) -> AlertRule:
    return AlertRule(
        name="r", alert_type=alert_type, threshold=threshold, is_enabled=True
    )


def _metric(**kwargs: object) -> DeviceMetric:
    base: dict[str, object] = {"reachable": True, "collected_at": datetime.now(UTC)}
    base.update(kwargs)
    return DeviceMetric(**base)  # type: ignore[arg-type]


def test_device_offline_triggers_on_unreachable() -> None:
    ev = _evaluator()
    cond = ev.evaluate(
        _rule(AlertType.DEVICE_OFFLINE), _DEVICE, _metric(reachable=False)
    )
    assert cond.triggered is True
    assert "not responding" in cond.message


def test_device_offline_not_triggered_when_reachable() -> None:
    ev = _evaluator()
    cond = ev.evaluate(
        _rule(AlertType.DEVICE_OFFLINE), _DEVICE, _metric(reachable=True)
    )
    assert cond.triggered is False


def test_offline_with_no_metric_is_not_triggered() -> None:
    ev = _evaluator()
    cond = ev.evaluate(_rule(AlertType.DEVICE_OFFLINE), _DEVICE, None)
    assert cond.triggered is False


def test_high_cpu_uses_rule_threshold() -> None:
    ev = _evaluator()
    cond = ev.evaluate(
        _rule(AlertType.HIGH_CPU, threshold=80.0),
        _DEVICE,
        _metric(cpu_load_percent=85.0),
    )
    assert cond.triggered is True
    assert cond.value == 85.0
    assert cond.threshold == 80.0


def test_high_cpu_falls_back_to_default_threshold() -> None:
    ev = _evaluator()
    # No rule threshold -> default 90; 95 > 90 fires.
    fires = ev.evaluate(
        _rule(AlertType.HIGH_CPU), _DEVICE, _metric(cpu_load_percent=95.0)
    )
    clears = ev.evaluate(
        _rule(AlertType.HIGH_CPU), _DEVICE, _metric(cpu_load_percent=50.0)
    )
    assert fires.triggered is True
    assert clears.triggered is False


def test_packet_loss_default_threshold() -> None:
    ev = _evaluator()
    cond = ev.evaluate(
        _rule(AlertType.PACKET_LOSS), _DEVICE, _metric(packet_loss_percent=30.0)
    )
    assert cond.triggered is True


def test_missing_gauge_value_does_not_fire() -> None:
    ev = _evaluator()
    cond = ev.evaluate(
        _rule(AlertType.HIGH_MEMORY), _DEVICE, _metric(memory_used_percent=None)
    )
    assert cond.triggered is False


def test_high_disk_is_inert_without_data() -> None:
    ev = _evaluator()
    cond = ev.evaluate(
        _rule(AlertType.HIGH_DISK, threshold=10.0), _DEVICE, _metric()
    )
    assert cond.triggered is False
    assert cond.value is None


def test_interface_utilization_from_two_snapshots() -> None:
    ev = _evaluator()
    t0 = datetime.now(UTC)
    t1 = t0 + timedelta(seconds=10)
    # 1 Mbps link; 1,200,000 bytes over 10s => 960 kbps => 96% utilization.
    previous = _metric(
        collected_at=t0,
        interfaces=[
            InterfaceStat(
                name="eth0", if_index=1, in_octets=0, speed_bps=1_000_000
            )
        ],
    )
    current = _metric(
        collected_at=t1,
        interfaces=[
            InterfaceStat(
                name="eth0", if_index=1, in_octets=1_200_000, speed_bps=1_000_000
            )
        ],
    )
    cond = ev.evaluate(
        _rule(AlertType.HIGH_INTERFACE_UTIL, threshold=90.0),
        _DEVICE,
        current,
        previous,
    )
    assert cond.triggered is True
    assert cond.value is not None and 95.0 <= cond.value <= 97.0


def test_interface_utilization_needs_previous_snapshot() -> None:
    ev = _evaluator()
    current = _metric(
        interfaces=[
            InterfaceStat(
                name="eth0", if_index=1, in_octets=10, speed_bps=1_000_000
            )
        ]
    )
    cond = ev.evaluate(
        _rule(AlertType.HIGH_INTERFACE_UTIL, threshold=90.0), _DEVICE, current, None
    )
    assert cond.triggered is False
