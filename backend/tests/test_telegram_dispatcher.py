"""Unit tests for the Telegram update dispatcher (webhook/poll entry point)."""

import uuid

import pytest

from app.models.alert import AlertHistory, AlertSeverity, AlertStatus, AlertType
from app.models.telegram import TelegramUser
from app.services.alerting import AlertingService
from app.services.notifier import AlertNotifier
from app.services.telegram_bot import (
    TelegramCommandService,
    TelegramUpdateDispatcher,
)
from tests.conftest import (
    FakeAlertAckRepository,
    FakeAlertHistoryRepository,
    FakeAlertRuleRepository,
    FakeDeviceRepository,
    FakeMetricRepository,
    FakeTelegramChatRepository,
    FakeTelegramSender,
    FakeTelegramUserRepository,
)


async def _build():
    devices = FakeDeviceRepository()
    metrics = FakeMetricRepository()
    history = FakeAlertHistoryRepository()
    acks = FakeAlertAckRepository()
    users = FakeTelegramUserRepository()
    sender = FakeTelegramSender()

    alerting = AlertingService(
        rule_repo=FakeAlertRuleRepository(),
        history_repo=history,
        ack_repo=acks,
        device_repo=devices,
        metric_repo=metrics,
        notifier=AlertNotifier(sender, FakeTelegramChatRepository()),
        default_thresholds={},
    )
    commands = TelegramCommandService(devices, metrics, history)
    dispatcher = TelegramUpdateDispatcher(sender, commands, alerting, users)
    return dispatcher, sender, users, history, acks


def _message(text: str, from_id: int) -> dict:
    return {
        "message": {
            "text": text,
            "chat": {"id": 999},
            "from": {"id": from_id, "username": "tester"},
        }
    }


@pytest.mark.asyncio
async def test_unknown_user_is_auto_registered_inactive() -> None:
    dispatcher, sender, users, *_ = await _build()
    await dispatcher.dispatch(_message("/help", from_id=5))
    registered = await users.get_by_telegram_id(5)
    assert registered is not None
    assert registered.is_active is False
    assert len(sender.messages) == 1


@pytest.mark.asyncio
async def test_inactive_then_enabled_user_flow() -> None:
    dispatcher, sender, users, *_ = await _build()
    await dispatcher.dispatch(_message("/status", from_id=7))
    assert "not authorized" in sender.messages[-1][1].lower()

    user = await users.get_by_telegram_id(7)
    user.is_active = True
    await users.update(user)

    await dispatcher.dispatch(_message("/status", from_id=7))
    assert "Devices:" in sender.messages[-1][1]


@pytest.mark.asyncio
async def test_callback_ack_by_active_user() -> None:
    dispatcher, sender, users, history, acks = await _build()
    await users.add(TelegramUser(telegram_user_id=1, is_active=True))
    alert = await history.add(
        AlertHistory(
            device_id=uuid.uuid4(),
            alert_type=AlertType.HIGH_CPU,
            severity=AlertSeverity.WARNING,
            status=AlertStatus.FIRING,
            message="x",
        )
    )
    await dispatcher.dispatch(
        {
            "callback_query": {
                "id": "cq1",
                "data": f"ack:{alert.id}",
                "from": {"id": 1},
            }
        }
    )
    assert alert.status is AlertStatus.ACKNOWLEDGED
    assert len(acks.items) == 1
    assert sender.callbacks[-1] == ("cq1", "Acknowledged ✅")


@pytest.mark.asyncio
async def test_callback_ack_rejected_for_inactive_user() -> None:
    dispatcher, sender, users, history, acks = await _build()
    alert = await history.add(
        AlertHistory(
            device_id=uuid.uuid4(),
            alert_type=AlertType.HIGH_CPU,
            severity=AlertSeverity.WARNING,
            status=AlertStatus.FIRING,
            message="x",
        )
    )
    await dispatcher.dispatch(
        {
            "callback_query": {
                "id": "cq2",
                "data": f"ack:{alert.id}",
                "from": {"id": 42},  # unknown -> auto-registered inactive
            }
        }
    )
    assert alert.status is AlertStatus.FIRING
    assert acks.items == []
    assert sender.callbacks[-1] == ("cq2", "Not authorized")
