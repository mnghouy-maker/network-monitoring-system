"""Unit tests for the AI troubleshooting service (fake provider, no network)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.models.ai import AIMessageRole, AISubjectType
from app.models.device import Device, DeviceCategory
from app.models.metric import DeviceMetric, MetricSource
from app.models.server import Server, ServerMonitorMethod
from app.schemas.ai import AISessionCreate
from app.services.exceptions import (
    AIError,
    EntityNotFoundError,
    ServiceError,
)
from app.services.troubleshooting import TroubleshootingService
from tests.conftest import (
    FakeAIMessageRepository,
    FakeAIProvider,
    FakeAISessionRepository,
    FakeAlertHistoryRepository,
    FakeConfigBackupRepository,
    FakeDeviceRepository,
    FakeMetricRepository,
    FakeServerHealthRepository,
    FakeServerRepository,
)


def _build(provider: FakeAIProvider | None = None):
    devices = FakeDeviceRepository()
    metrics = FakeMetricRepository()
    alerts = FakeAlertHistoryRepository()
    servers = FakeServerRepository()
    server_health = FakeServerHealthRepository()
    backups = FakeConfigBackupRepository()
    service = TroubleshootingService(
        session_repo=FakeAISessionRepository(),
        message_repo=FakeAIMessageRepository(),
        provider=provider or FakeAIProvider(),
        device_repo=devices,
        metric_repo=metrics,
        alert_repo=alerts,
        server_repo=servers,
        server_health_repo=server_health,
        backup_repo=backups,
        model="test-model",
        max_tokens=512,
        max_history=10,
    )
    return service, devices, metrics, servers


async def _add_device(repo: FakeDeviceRepository, name: str = "r1") -> Device:
    device = Device(
        name=name,
        hostname="10.0.0.1",
        category=DeviceCategory.ROUTER,
    )
    return await repo.add(device)


@pytest.mark.asyncio
async def test_general_session_chat_persists_turns() -> None:
    service, *_ = _build()
    session = await service.create_session(
        AISessionCreate(subject_type=AISubjectType.GENERAL)
    )
    reply = await service.send_message(session.id, "What is broken?")

    assert reply.role is AIMessageRole.ASSISTANT
    assert reply.content == "Here is my assessment."
    assert reply.model == "fake-model"

    history = await service.list_messages(session.id)
    assert [m.role for m in history] == [
        AIMessageRole.USER,
        AIMessageRole.ASSISTANT,
    ]


@pytest.mark.asyncio
async def test_device_context_is_passed_to_provider() -> None:
    provider = FakeAIProvider()
    service, devices, metrics, _ = _build(provider)
    device = await _add_device(devices, "core-sw")
    await metrics.add(
        DeviceMetric(
            device_id=device.id,
            source=MetricSource.SNMP,
            reachable=True,
            cpu_load_percent=97.0,
            collected_at=datetime.now(UTC),
        )
    )

    session = await service.create_session(
        AISessionCreate(
            subject_type=AISubjectType.DEVICE, subject_id=device.id
        )
    )
    await service.send_message(session.id, "Why is CPU high?")

    system_prompt = provider.calls[-1][0]
    assert "core-sw" in system_prompt
    assert "97.0%" in system_prompt


@pytest.mark.asyncio
async def test_create_device_session_requires_existing_device() -> None:
    service, *_ = _build()
    with pytest.raises(EntityNotFoundError):
        await service.create_session(
            AISessionCreate(
                subject_type=AISubjectType.DEVICE, subject_id=uuid.uuid4()
            )
        )


@pytest.mark.asyncio
async def test_device_session_requires_subject_id() -> None:
    service, *_ = _build()
    with pytest.raises(ServiceError):
        await service.create_session(
            AISessionCreate(subject_type=AISubjectType.DEVICE)
        )


@pytest.mark.asyncio
async def test_chat_when_provider_unconfigured_raises() -> None:
    service, *_ = _build(FakeAIProvider(configured=False))
    session = await service.create_session(
        AISessionCreate(subject_type=AISubjectType.GENERAL)
    )
    with pytest.raises(AIError):
        await service.send_message(session.id, "hello")


@pytest.mark.asyncio
async def test_diagnose_server_opens_session_and_replies() -> None:
    service, _, _, servers = _build()
    server = await servers.add(
        Server(
            name="db-1",
            hostname="10.0.0.9",
            monitor_method=ServerMonitorMethod.LOCAL,
        )
    )
    session, reply = await service.diagnose(
        AISubjectType.SERVER, server.id, None
    )
    assert session.subject_id == server.id
    assert reply.role is AIMessageRole.ASSISTANT
    messages = await service.list_messages(session.id)
    assert messages[0].role is AIMessageRole.USER
