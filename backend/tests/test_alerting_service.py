"""Unit tests for the alerting service: firing, dedup, recovery, ack, routing."""

from datetime import UTC, datetime

import pytest

from app.models.alert import (
    AlertRule,
    AlertSeverity,
    AlertStatus,
    AlertType,
)
from app.models.device import Device
from app.models.metric import DeviceMetric, MetricSource
from app.models.telegram import TelegramChat
from app.services.alerting import AlertingService
from app.services.exceptions import AlertError
from app.services.notifier import AlertNotifier
from tests.conftest import (
    FakeAlertAckRepository,
    FakeAlertHistoryRepository,
    FakeAlertRuleRepository,
    FakeDeviceRepository,
    FakeMetricRepository,
    FakeTelegramChatRepository,
    FakeTelegramSender,
)

_DEFAULTS = {AlertType.HIGH_CPU: 90.0, AlertType.PACKET_LOSS: 20.0}


async def _setup(cpu: float, *, chat_min=AlertSeverity.INFO):
    devices = FakeDeviceRepository()
    metrics = FakeMetricRepository()
    rules = FakeAlertRuleRepository()
    history = FakeAlertHistoryRepository()
    acks = FakeAlertAckRepository()
    chats = FakeTelegramChatRepository()
    sender = FakeTelegramSender()

    device = await devices.add(Device(name="rtr", hostname="10.0.0.1"))
    await metrics.add(
        DeviceMetric(
            device_id=device.id,
            source=MetricSource.SNMP,
            reachable=True,
            cpu_load_percent=cpu,
            collected_at=datetime.now(UTC),
        )
    )
    await rules.add(
        AlertRule(
            name="cpu",
            alert_type=AlertType.HIGH_CPU,
            severity=AlertSeverity.WARNING,
            threshold=90.0,
            is_enabled=True,
        )
    )
    await chats.add(
        TelegramChat(chat_id=111, is_active=True, min_severity=chat_min)
    )
    service = AlertingService(
        rule_repo=rules,
        history_repo=history,
        ack_repo=acks,
        device_repo=devices,
        metric_repo=metrics,
        notifier=AlertNotifier(sender, chats),
        default_thresholds=_DEFAULTS,
    )
    return service, device, metrics, history, acks, sender


@pytest.mark.asyncio
async def test_fires_and_notifies() -> None:
    service, device, *_rest, sender = await _setup(cpu=95.0)
    changed = await service.evaluate_device(device)
    assert len(changed) == 1
    assert changed[0].status is AlertStatus.FIRING
    # Routed to the active chat with an Acknowledge keyboard.
    assert len(sender.messages) == 1
    assert sender.messages[0][2] is not None  # reply_markup present


@pytest.mark.asyncio
async def test_dedup_no_duplicate_alert() -> None:
    service, device, _metrics, history, _acks, sender = await _setup(cpu=95.0)
    await service.evaluate_device(device)
    # Re-evaluating the same breaching metric must not create a second alert.
    changed = await service.evaluate_device(device)
    assert changed == []
    assert len(sender.messages) == 1


@pytest.mark.asyncio
async def test_recovery_resolves_and_notifies() -> None:
    service, device, metrics, history, _acks, sender = await _setup(cpu=95.0)
    await service.evaluate_device(device)
    # A healthy metric becomes the latest snapshot -> condition clears.
    await metrics.add(
        DeviceMetric(
            device_id=device.id,
            source=MetricSource.SNMP,
            reachable=True,
            cpu_load_percent=10.0,
            collected_at=datetime.now(UTC),
        )
    )
    changed = await service.evaluate_device(device)
    assert len(changed) == 1
    assert changed[0].status is AlertStatus.RESOLVED
    assert changed[0].resolved_at is not None
    assert len(sender.messages) == 2  # alert + recovery


@pytest.mark.asyncio
async def test_acknowledge_sets_status_and_records() -> None:
    service, device, _metrics, history, acks, _sender = await _setup(cpu=95.0)
    alert = (await service.evaluate_device(device))[0]
    acked = await service.acknowledge(alert.id, note="looking")
    assert acked.status is AlertStatus.ACKNOWLEDGED
    assert len(acks.items) == 1


@pytest.mark.asyncio
async def test_cannot_acknowledge_resolved_alert() -> None:
    service, device, metrics, *_ = await _setup(cpu=95.0)
    alert = (await service.evaluate_device(device))[0]
    alert.status = AlertStatus.RESOLVED
    with pytest.raises(AlertError):
        await service.acknowledge(alert.id)


@pytest.mark.asyncio
async def test_severity_routing_skips_higher_min_chats() -> None:
    # Chat only wants CRITICAL; a WARNING alert must not be delivered there.
    service, device, *_rest, sender = await _setup(
        cpu=95.0, chat_min=AlertSeverity.CRITICAL
    )
    await service.evaluate_device(device)
    assert sender.messages == []
