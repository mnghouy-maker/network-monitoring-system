"""Shared test fixtures.

These tests deliberately avoid a real database. The service layer depends only
on the ``UserRepository`` interface, so we substitute a lightweight in-memory
fake. This keeps unit tests fast and hermetic; database integration is covered
separately via Alembic/Docker in higher test tiers.
"""

from __future__ import annotations

import os
import uuid

import pytest

# Provide a SECRET_KEY before app modules import settings.
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")

from app.models.device import Device, DeviceCategory  # noqa: E402
from app.models.metric import DeviceMetric  # noqa: E402
from app.models.user import User  # noqa: E402
from app.monitoring.types import MetricSample, PingResult  # noqa: E402


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
