"""Unit tests for Telegram message formatting."""

import uuid

from app.models.alert import AlertHistory, AlertSeverity, AlertType
from app.models.device import Device
from app.telegram.formatting import (
    ack_keyboard,
    format_alert,
    format_recovery,
)


def _alert(alert_type: AlertType, severity: AlertSeverity) -> AlertHistory:
    return AlertHistory(
        id=uuid.uuid4(),
        device_id=uuid.uuid4(),
        alert_type=alert_type,
        severity=severity,
        message="CPU load on rtr: 95.0% (threshold 90%)",
        value=95.0,
        threshold=90.0,
    )


def test_ack_keyboard_has_callback() -> None:
    alert_id = uuid.uuid4()
    kb = ack_keyboard(alert_id)
    button = kb["inline_keyboard"][0][0]
    assert button["callback_data"] == f"ack:{alert_id}"


def test_format_alert_contains_device_and_value() -> None:
    device = Device(name="rtr-1", hostname="10.0.0.1", location="DC-A")
    text = format_alert(_alert(AlertType.HIGH_CPU, AlertSeverity.CRITICAL), device)
    assert "rtr-1" in text
    assert "10.0.0.1" in text
    assert "CRITICAL" in text
    assert "95" in text


def test_format_alert_escapes_html() -> None:
    device = Device(name="<b>evil</b>", hostname="10.0.0.1")
    text = format_alert(_alert(AlertType.HIGH_CPU, AlertSeverity.WARNING), device)
    assert "<b>evil</b>" not in text
    assert "&lt;b&gt;evil&lt;/b&gt;" in text


def test_format_recovery_for_offline_says_online() -> None:
    device = Device(name="rtr-1", hostname="10.0.0.1")
    text = format_recovery(
        _alert(AlertType.DEVICE_OFFLINE, AlertSeverity.CRITICAL), device
    )
    assert "Device Online" in text
    assert "RESOLVED" in text
