"""Shared test fixtures.

These tests deliberately avoid a real database. The service layer depends only
on the ``UserRepository`` interface, so we substitute a lightweight in-memory
fake. This keeps unit tests fast and hermetic; database integration is covered
separately via Alembic/Docker in higher test tiers.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pytest

# Provide a SECRET_KEY before app modules import settings.
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")

from app.models.alert import (  # noqa: E402
    AlertAcknowledgement,
    AlertHistory,
    AlertRule,
    AlertSeverity,
    AlertStatus,
    AlertType,
)
from app.models.device import Device, DeviceCategory  # noqa: E402
from app.models.metric import DeviceMetric  # noqa: E402
from app.models.telegram import TelegramChat, TelegramUser  # noqa: E402
from app.models.user import User  # noqa: E402
from app.monitoring.types import MetricSample, PingResult  # noqa: E402


def _apply_timestamps(obj: object) -> None:
    """Populate ``created_at``/``updated_at`` the way DB server defaults would."""
    now = datetime.now(UTC)
    if getattr(obj, "created_at", None) is None:
        obj.created_at = now  # type: ignore[attr-defined]
    if getattr(obj, "updated_at", None) is None:
        obj.updated_at = now  # type: ignore[attr-defined]


class FakeUserRepository:
    """In-memory stand-in for :class:`app.repositories.user.UserRepository`."""

    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, User] = {}

    async def get(self, user_id: uuid.UUID) -> User | None:
        return self._by_id.get(user_id)

    async def get_by_email(self, email: str) -> User | None:
        return next(
            (u for u in self._by_id.values() if u.email == email), None
        )

    async def get_by_username(self, username: str) -> User | None:
        return next(
            (u for u in self._by_id.values() if u.username == username), None
        )

    async def list(self, skip: int = 0, limit: int = 100) -> list[User]:
        return list(self._by_id.values())[skip : skip + limit]

    async def add(self, user: User) -> User:
        if user.id is None:
            user.id = uuid.uuid4()
        # Mimic DB server defaults so response models can serialize.
        _apply_timestamps(user)
        if user.is_active is None:
            user.is_active = True
        if user.is_superuser is None:
            user.is_superuser = False
        self._by_id[user.id] = user
        return user

    async def update(self, user: User) -> User:
        self._by_id[user.id] = user
        return user

    async def delete(self, user: User) -> None:
        self._by_id.pop(user.id, None)


@pytest.fixture
def fake_repo() -> FakeUserRepository:
    return FakeUserRepository()


class FakeDeviceRepository:
    """In-memory stand-in for ``DeviceRepository``."""

    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, Device] = {}

    async def get(self, device_id: uuid.UUID) -> Device | None:
        return self._by_id.get(device_id)

    async def get_by_name(self, name: str) -> Device | None:
        return next(
            (d for d in self._by_id.values() if d.name == name), None
        )

    async def list(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
        category: DeviceCategory | None = None,
        is_active: bool | None = None,
    ) -> list[Device]:
        items = list(self._by_id.values())
        if category is not None:
            items = [d for d in items if d.category == category]
        if is_active is not None:
            items = [d for d in items if d.is_active == is_active]
        return items[skip : skip + limit]

    async def list_active(self) -> list[Device]:
        return [d for d in self._by_id.values() if d.is_active]

    async def count(self, *, category: DeviceCategory | None = None) -> int:
        return len(await self.list(category=category, limit=10_000))

    async def add(self, device: Device) -> Device:
        if device.id is None:
            device.id = uuid.uuid4()
        # Apply column defaults the DB would normally provide.
        if device.is_active is None:
            device.is_active = True
        _apply_timestamps(device)
        self._by_id[device.id] = device
        return device

    async def update(self, device: Device) -> Device:
        self._by_id[device.id] = device
        return device

    async def delete(self, device: Device) -> None:
        self._by_id.pop(device.id, None)


class FakeMetricRepository:
    """In-memory stand-in for ``MetricRepository``."""

    def __init__(self) -> None:
        self._items: list[DeviceMetric] = []

    async def add(self, metric: DeviceMetric) -> DeviceMetric:
        if metric.id is None:
            metric.id = uuid.uuid4()
        if metric.collected_at is None:
            metric.collected_at = datetime.now(UTC)
        self._items.append(metric)
        return metric

    async def get_latest(self, device_id: uuid.UUID) -> DeviceMetric | None:
        matches = [m for m in self._items if m.device_id == device_id]
        return matches[-1] if matches else None

    async def list_history(
        self, device_id: uuid.UUID, *, skip: int = 0, limit: int = 100
    ) -> list[DeviceMetric]:
        matches = [m for m in self._items if m.device_id == device_id]
        return list(reversed(matches))[skip : skip + limit]


class FakePingCollector:
    """Returns a preset :class:`PingResult`."""

    def __init__(self, result: PingResult) -> None:
        self._result = result
        self.calls: list[str] = []

    async def ping(self, host: str) -> PingResult:
        self.calls.append(host)
        return self._result


class FakeMetricCollector:
    """Returns a preset :class:`MetricSample`, or raises a preset error."""

    def __init__(
        self,
        sample: MetricSample | None = None,
        error: Exception | None = None,
    ) -> None:
        self._sample = sample or MetricSample()
        self._error = error
        self.calls: list[Device] = []

    async def collect(self, device: Device) -> MetricSample:
        self.calls.append(device)
        if self._error is not None:
            raise self._error
        return self._sample


@pytest.fixture
def fake_device_repo() -> FakeDeviceRepository:
    return FakeDeviceRepository()


@pytest.fixture
def fake_metric_repo() -> FakeMetricRepository:
    return FakeMetricRepository()


# --- Phase 3 fakes: alerting + telegram --------------------------------------
class FakeAlertRuleRepository:
    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, AlertRule] = {}

    async def get(self, rule_id: uuid.UUID) -> AlertRule | None:
        return self._by_id.get(rule_id)

    async def list(self, *, skip: int = 0, limit: int = 100) -> list[AlertRule]:
        return list(self._by_id.values())[skip : skip + limit]

    async def list_enabled_for_device(
        self, device_id: uuid.UUID
    ) -> list[AlertRule]:
        return [
            r
            for r in self._by_id.values()
            if r.is_enabled and r.device_id in (None, device_id)
        ]

    async def add(self, rule: AlertRule) -> AlertRule:
        if rule.id is None:
            rule.id = uuid.uuid4()
        # Mirror DB column defaults the ORM would apply at flush.
        if rule.is_enabled is None:
            rule.is_enabled = True
        if rule.severity is None:
            rule.severity = AlertSeverity.WARNING
        _apply_timestamps(rule)
        self._by_id[rule.id] = rule
        return rule

    async def update(self, rule: AlertRule) -> AlertRule:
        self._by_id[rule.id] = rule
        return rule

    async def delete(self, rule: AlertRule) -> None:
        self._by_id.pop(rule.id, None)


class FakeAlertHistoryRepository:
    def __init__(self) -> None:
        self._items: list[AlertHistory] = []

    async def get(self, alert_id: uuid.UUID) -> AlertHistory | None:
        return next((a for a in self._items if a.id == alert_id), None)

    async def get_active(
        self, device_id: uuid.UUID, alert_type: AlertType
    ) -> AlertHistory | None:
        active = [
            a
            for a in self._items
            if a.device_id == device_id
            and a.alert_type == alert_type
            and a.status in (AlertStatus.FIRING, AlertStatus.ACKNOWLEDGED)
        ]
        return active[-1] if active else None

    async def list_active(
        self, *, severity: AlertSeverity | None = None, limit: int = 100
    ) -> list[AlertHistory]:
        items = [
            a
            for a in self._items
            if a.status in (AlertStatus.FIRING, AlertStatus.ACKNOWLEDGED)
        ]
        if severity is not None:
            items = [a for a in items if a.severity == severity]
        return list(reversed(items))[:limit]

    async def list_history(
        self,
        *,
        device_id: uuid.UUID | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[AlertHistory]:
        items = self._items
        if device_id is not None:
            items = [a for a in items if a.device_id == device_id]
        return list(reversed(items))[skip : skip + limit]

    async def add(self, alert: AlertHistory) -> AlertHistory:
        if alert.id is None:
            alert.id = uuid.uuid4()
        if alert.triggered_at is None:
            alert.triggered_at = datetime.now(UTC)
        if alert.created_at is None:
            alert.created_at = datetime.now(UTC)
        self._items.append(alert)
        return alert

    async def update(self, alert: AlertHistory) -> AlertHistory:
        return alert


class FakeAlertAckRepository:
    def __init__(self) -> None:
        self.items: list[AlertAcknowledgement] = []

    async def add(
        self, ack: AlertAcknowledgement
    ) -> AlertAcknowledgement:
        if ack.id is None:
            ack.id = uuid.uuid4()
        ack.acknowledged_at = datetime.now(UTC)
        self.items.append(ack)
        return ack


class FakeTelegramUserRepository:
    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, TelegramUser] = {}

    async def get(self, pk: uuid.UUID) -> TelegramUser | None:
        return self._by_id.get(pk)

    async def get_by_telegram_id(self, tid: int) -> TelegramUser | None:
        return next(
            (u for u in self._by_id.values() if u.telegram_user_id == tid),
            None,
        )

    async def list(self, *, skip: int = 0, limit: int = 100) -> list[TelegramUser]:
        return list(self._by_id.values())[skip : skip + limit]

    async def add(self, user: TelegramUser) -> TelegramUser:
        if user.id is None:
            user.id = uuid.uuid4()
        if user.is_active is None:
            user.is_active = False
        _apply_timestamps(user)
        self._by_id[user.id] = user
        return user

    async def update(self, user: TelegramUser) -> TelegramUser:
        self._by_id[user.id] = user
        return user


class FakeTelegramChatRepository:
    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, TelegramChat] = {}

    async def get(self, pk: uuid.UUID) -> TelegramChat | None:
        return self._by_id.get(pk)

    async def get_by_chat_id(self, chat_id: int) -> TelegramChat | None:
        return next(
            (c for c in self._by_id.values() if c.chat_id == chat_id), None
        )

    async def list(self, *, skip: int = 0, limit: int = 100) -> list[TelegramChat]:
        return list(self._by_id.values())[skip : skip + limit]

    async def list_active(self) -> list[TelegramChat]:
        return [c for c in self._by_id.values() if c.is_active]

    async def add(self, chat: TelegramChat) -> TelegramChat:
        if chat.id is None:
            chat.id = uuid.uuid4()
        if chat.is_active is None:
            chat.is_active = True
        _apply_timestamps(chat)
        self._by_id[chat.id] = chat
        return chat

    async def update(self, chat: TelegramChat) -> TelegramChat:
        self._by_id[chat.id] = chat
        return chat

    async def delete(self, chat: TelegramChat) -> None:
        self._by_id.pop(chat.id, None)


class FakeTelegramSender:
    """Records outbound messages/callbacks instead of calling Telegram."""

    def __init__(self, configured: bool = True) -> None:
        self._configured = configured
        self.messages: list[tuple[int, str, dict | None]] = []
        self.callbacks: list[tuple[str, str | None]] = []

    @property
    def is_configured(self) -> bool:
        return self._configured

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        reply_markup: dict | None = None,
        parse_mode: str | None = "HTML",
    ) -> bool:
        self.messages.append((chat_id, text, reply_markup))
        return self._configured

    async def answer_callback_query(
        self, callback_query_id: str, text: str | None = None
    ) -> bool:
        self.callbacks.append((callback_query_id, text))
        return True

    async def get_updates(
        self, offset: int | None = None, timeout: int = 0
    ) -> list[dict]:
        return []


@pytest.fixture
def fake_rule_repo() -> FakeAlertRuleRepository:
    return FakeAlertRuleRepository()


@pytest.fixture
def fake_history_repo() -> FakeAlertHistoryRepository:
    return FakeAlertHistoryRepository()


@pytest.fixture
def fake_ack_repo() -> FakeAlertAckRepository:
    return FakeAlertAckRepository()


@pytest.fixture
def fake_tg_user_repo() -> FakeTelegramUserRepository:
    return FakeTelegramUserRepository()


@pytest.fixture
def fake_tg_chat_repo() -> FakeTelegramChatRepository:
    return FakeTelegramChatRepository()


@pytest.fixture
def fake_sender() -> FakeTelegramSender:
    return FakeTelegramSender()
