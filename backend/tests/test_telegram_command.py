"""Unit tests for the Telegram command service."""

from datetime import UTC, datetime

import pytest

from app.models.alert import AlertHistory, AlertSeverity, AlertStatus, AlertType
from app.models.device import Device, DeviceCategory
from app.models.metric import DeviceMetric, MetricSource
from app.models.telegram import TelegramUser
from app.services.telegram_bot import TelegramCommandService
from tests.conftest import (
    FakeAlertHistoryRepository,
    FakeDeviceRepository,
    FakeMetricRepository,
)


async def _service():
    devices = FakeDeviceRepository()
    metrics = FakeMetricRepository()
    history = FakeAlertHistoryRepository()
    device = await devices.add(
        Device(name="rtr", hostname="10.0.0.1", category=DeviceCategory.ROUTER)
    )
    await metrics.add(
        DeviceMetric(
            device_id=device.id,
            source=MetricSource.SNMP,
            reachable=True,
            cpu_load_percent=50.0,
            collected_at=datetime.now(UTC),
        )
    )
    await history.add(
        AlertHistory(
            device_id=device.id,
            alert_type=AlertType.HIGH_CPU,
            severity=AlertSeverity.WARNING,
            status=AlertStatus.FIRING,
            message="CPU high",
        )
    )
    return TelegramCommandService(devices, metrics, history), device


_ACTIVE = TelegramUser(telegram_user_id=1, is_active=True)
_INACTIVE = TelegramUser(telegram_user_id=2, is_active=False)


@pytest.mark.asyncio
async def test_help_is_public() -> None:
    service, _ = await _service()
    assert "/status" in await service.handle("/help", None)


@pytest.mark.asyncio
async def test_inactive_user_is_unauthorized() -> None:
    service, _ = await _service()
    reply = await service.handle("/status", _INACTIVE)
    assert "not authorized" in reply.lower()


@pytest.mark.asyncio
async def test_start_shows_telegram_id() -> None:
    service, _ = await _service()
    assert "2" in await service.handle("/start", _INACTIVE)


@pytest.mark.asyncio
async def test_status_summary() -> None:
    service, _ = await _service()
    reply = await service.handle("/status", _ACTIVE)
    assert "Devices:" in reply
    assert "Active alerts:" in reply


@pytest.mark.asyncio
async def test_devices_lists_device() -> None:
    service, _ = await _service()
    assert "rtr" in await service.handle("/devices", _ACTIVE)


@pytest.mark.asyncio
async def test_device_details_by_hostname() -> None:
    service, _ = await _service()
    reply = await service.handle("/device 10.0.0.1", _ACTIVE)
    assert "rtr" in reply
    assert "CPU" in reply


@pytest.mark.asyncio
async def test_device_unknown_hostname() -> None:
    service, _ = await _service()
    assert "No device found" in await service.handle("/device 9.9.9.9", _ACTIVE)


@pytest.mark.asyncio
async def test_alerts_and_critical() -> None:
    service, _ = await _service()
    assert "rtr" in await service.handle("/alerts", _ACTIVE)
    # The only alert is a WARNING, so /critical reports none.
    assert "No active alerts" in await service.handle("/critical", _ACTIVE)


@pytest.mark.asyncio
async def test_command_with_bot_mention_is_handled() -> None:
    service, _ = await _service()
    assert "Devices:" in await service.handle("/status@NetOpsBot", _ACTIVE)
