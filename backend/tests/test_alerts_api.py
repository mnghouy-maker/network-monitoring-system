"""API/integration tests for the alerts and telegram routers.

Uses dependency overrides with in-memory fakes (no DB, no network). The real
alerting service runs; the Telegram client singleton is unconfigured, so
notifications are no-ops.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest

from app.core import dependencies as deps
from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.alert import AlertRule, AlertType
from app.models.device import Device
from app.models.metric import DeviceMetric, MetricSource
from app.models.user import User, UserRole
from tests.conftest import (
    FakeAlertAckRepository,
    FakeAlertHistoryRepository,
    FakeAlertRuleRepository,
    FakeDeviceRepository,
    FakeMetricRepository,
    FakeTelegramChatRepository,
    FakeTelegramUserRepository,
    FakeUserRepository,
)


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_user(repo: FakeUserRepository, username: str, role: UserRole) -> User:
    user = User(
        email=f"{username}@example.com",
        username=username,
        role=role,
        hashed_password=hash_password("password1"),
        is_active=True,
    )
    user.id = uuid.uuid4()
    user.created_at = user.updated_at = datetime.now(UTC)
    repo._by_id[user.id] = user
    return user


@pytest.fixture
def api() -> Iterator[SimpleNamespace]:
    users = FakeUserRepository()
    devices = FakeDeviceRepository()
    metrics = FakeMetricRepository()
    rules = FakeAlertRuleRepository()
    history = FakeAlertHistoryRepository()
    acks = FakeAlertAckRepository()
    tg_users = FakeTelegramUserRepository()
    tg_chats = FakeTelegramChatRepository()

    overrides = {
        deps.get_user_repository: lambda: users,
        deps.get_device_repository: lambda: devices,
        deps.get_metric_repository: lambda: metrics,
        deps.get_alert_rule_repository: lambda: rules,
        deps.get_alert_history_repository: lambda: history,
        deps.get_alert_ack_repository: lambda: acks,
        deps.get_telegram_user_repository: lambda: tg_users,
        deps.get_telegram_chat_repository: lambda: tg_chats,
    }
    app.dependency_overrides.update(overrides)

    admin = _seed_user(users, "admin", UserRole.ADMIN)
    operator = _seed_user(users, "oper", UserRole.OPERATOR)
    viewer = _seed_user(users, "view", UserRole.VIEWER)

    yield SimpleNamespace(
        devices=devices,
        metrics=metrics,
        rules=rules,
        history=history,
        tg_users=tg_users,
        tokens={
            "admin": create_access_token(admin.id),
            "operator": create_access_token(operator.id),
            "viewer": create_access_token(viewer.id),
        },
    )
    app.dependency_overrides.clear()


async def _seed_breaching_device(api: SimpleNamespace) -> uuid.UUID:
    device = await api.devices.add(Device(name="rtr", hostname="10.0.0.1"))
    await api.metrics.add(
        DeviceMetric(
            device_id=device.id,
            source=MetricSource.SNMP,
            reachable=True,
            cpu_load_percent=95.0,
            collected_at=datetime.now(UTC),
        )
    )
    await api.rules.add(
        AlertRule(
            name="cpu",
            alert_type=AlertType.HIGH_CPU,
            threshold=90.0,
            is_enabled=True,
        )
    )
    return device.id


# --- rules RBAC --------------------------------------------------------------
@pytest.mark.asyncio
async def test_rule_crud_rbac(api: SimpleNamespace) -> None:
    async with _client() as c:
        vh = _auth(api.tokens["viewer"])
        ah = _auth(api.tokens["admin"])
        body = {"name": "cpu", "alert_type": "high_cpu", "threshold": 90}

        denied = await c.post("/api/v1/alerts/rules", headers=vh, json=body)
        assert denied.status_code == 403
        created = await c.post("/api/v1/alerts/rules", headers=ah, json=body)
        assert created.status_code == 201
        # Any authenticated user can read rules.
        assert (await c.get("/api/v1/alerts/rules", headers=vh)).status_code == 200


# --- evaluate -> active -> ack -----------------------------------------------
@pytest.mark.asyncio
async def test_evaluate_fires_then_acknowledge(api: SimpleNamespace) -> None:
    device_id = await _seed_breaching_device(api)
    async with _client() as c:
        oh = _auth(api.tokens["operator"])

        evaluated = await c.post(
            f"/api/v1/alerts/evaluate/{device_id}", headers=oh
        )
        assert evaluated.status_code == 200
        assert len(evaluated.json()) == 1
        alert_id = evaluated.json()[0]["id"]
        assert evaluated.json()[0]["status"] == "firing"

        active = await c.get("/api/v1/alerts", headers=oh)
        assert active.status_code == 200
        assert len(active.json()) == 1

        # WARNING alert -> not in /critical.
        assert (await c.get("/api/v1/alerts/critical", headers=oh)).json() == []

        acked = await c.post(
            f"/api/v1/alerts/{alert_id}/ack",
            headers=oh,
            json={"note": "investigating"},
        )
        assert acked.status_code == 200
        assert acked.json()["status"] == "acknowledged"

        # Acking again (still active) is fine; acking a resolved one is 409 —
        # covered in the service unit tests.


@pytest.mark.asyncio
async def test_viewer_cannot_evaluate(api: SimpleNamespace) -> None:
    device_id = await _seed_breaching_device(api)
    async with _client() as c:
        r = await c.post(
            f"/api/v1/alerts/evaluate/{device_id}",
            headers=_auth(api.tokens["viewer"]),
        )
        assert r.status_code == 403


# --- telegram admin + webhook ------------------------------------------------
@pytest.mark.asyncio
async def test_telegram_chat_management_admin_only(api: SimpleNamespace) -> None:
    async with _client() as c:
        oh = _auth(api.tokens["operator"])
        ah = _auth(api.tokens["admin"])
        body = {"chat_id": -1001, "chat_type": "group", "min_severity": "warning"}

        denied = await c.post("/api/v1/telegram/chats", headers=oh, json=body)
        assert denied.status_code == 403
        created = await c.post("/api/v1/telegram/chats", headers=ah, json=body)
        assert created.status_code == 201
        dup = await c.post("/api/v1/telegram/chats", headers=ah, json=body)
        assert dup.status_code == 409


@pytest.mark.asyncio
async def test_webhook_requires_matching_secret(api: SimpleNamespace) -> None:
    update = {
        "update_id": 1,
        "message": {
            "text": "/help",
            "chat": {"id": 5},
            "from": {"id": 5, "username": "u"},
        },
    }
    original = settings.TELEGRAM_WEBHOOK_SECRET
    settings.TELEGRAM_WEBHOOK_SECRET = "s3cr3t"
    try:
        async with _client() as c:
            bad = await c.post("/api/v1/telegram/webhook/wrong", json=update)
            assert bad.status_code == 404
            ok = await c.post("/api/v1/telegram/webhook/s3cr3t", json=update)
            assert ok.status_code == 200
            assert ok.json() == {"ok": True}
        # The sender auto-registered the unknown user.
        assert await api.tg_users.get_by_telegram_id(5) is not None
    finally:
        settings.TELEGRAM_WEBHOOK_SECRET = original
