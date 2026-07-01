"""Telegram message formatting (HTML) for alerts and recoveries."""

from html import escape
from typing import Any

from app.models.alert import AlertHistory, AlertSeverity, AlertType
from app.models.device import Device

_SEVERITY_ICON = {
    AlertSeverity.INFO: "ℹ️",
    AlertSeverity.WARNING: "⚠️",
    AlertSeverity.CRITICAL: "🚨",
}

_TYPE_LABEL = {
    AlertType.DEVICE_OFFLINE: "Device Offline",
    AlertType.DEVICE_ONLINE: "Device Online",
    AlertType.HIGH_CPU: "High CPU",
    AlertType.HIGH_MEMORY: "High Memory",
    AlertType.HIGH_DISK: "High Disk",
    AlertType.HIGH_INTERFACE_UTIL: "High Interface Utilization",
    AlertType.PACKET_LOSS: "Packet Loss",
}


def alert_type_label(alert_type: AlertType) -> str:
    return _TYPE_LABEL.get(alert_type, alert_type.value)


def severity_icon(severity: AlertSeverity) -> str:
    return _SEVERITY_ICON.get(severity, "❗")


def ack_keyboard(alert_id: object) -> dict[str, Any]:
    """Inline keyboard with a single Acknowledge button."""
    return {
        "inline_keyboard": [
            [{"text": "✅ Acknowledge", "callback_data": f"ack:{alert_id}"}]
        ]
    }


def format_alert(alert: AlertHistory, device: Device) -> str:
    """Render a firing alert as an HTML message."""
    icon = _SEVERITY_ICON.get(alert.severity, "❗")
    lines = [
        f"{icon} <b>{escape(alert.severity.value.upper())}: "
        f"{escape(alert_type_label(alert.alert_type))}</b>",
        f"<b>Device:</b> {escape(device.name)} "
        f"(<code>{escape(device.hostname)}</code>)",
    ]
    if device.location:
        lines.append(f"<b>Location:</b> {escape(device.location)}")
    if alert.value is not None:
        threshold = (
            f" (threshold {alert.threshold:g})"
            if alert.threshold is not None
            else ""
        )
        lines.append(f"<b>Value:</b> {alert.value:g}{threshold}")
    lines.append(f"\n{escape(alert.message)}")
    return "\n".join(lines)


def format_recovery(alert: AlertHistory, device: Device) -> str:
    """Render a recovery (resolved) notification as an HTML message."""
    label = (
        "Device Online"
        if alert.alert_type is AlertType.DEVICE_OFFLINE
        else f"{alert_type_label(alert.alert_type)} recovered"
    )
    return (
        f"✅ <b>RESOLVED: {escape(label)}</b>\n"
        f"<b>Device:</b> {escape(device.name)} "
        f"(<code>{escape(device.hostname)}</code>)"
    )
