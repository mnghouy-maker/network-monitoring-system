"""API/integration tests for the configuration-backup router."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest

from app.core import dependencies as deps
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.device import Device
from app.models.user import User, UserRole
from app.services.backup import ConfigBackupService
from tests.conftest import (
    FakeConfigBackend,
    FakeConfigBackupRepository,
    FakeConnectionProfileRepository,
    FakeDeviceRepository,
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
    profiles = FakeConnectionProfileRepository()
    backups = FakeConfigBackupRepository()
    backend = FakeConfigBackend(content="hostname r1\n!")
    backup_service = ConfigBackupService(
        backups, profiles, devices, backend, backend
    )

    app.dependency_overrides.update(
        {
            deps.get_user_repository: lambda: users,
            deps.get_device_repository: lambda: devices,
            deps.get_connection_profile_repository: lambda: profiles,
            deps.get_config_backup_repository: lambda: backups,
            deps.get_config_backup_service: lambda: backup_service,
        }
    )

    admin = _seed_user(users, "admin", UserRole.ADMIN)
    operator = _seed_user(users, "oper", UserRole.OPERATOR)
    viewer = _seed_user(users, "view", UserRole.VIEWER)

    yield SimpleNamespace(
        devices=devices,
        backend=backend,
        tokens={
            "admin": create_access_token(admin.id),
            "operator": create_access_token(operator.id),
            "viewer": create_access_token(viewer.id),
        },
    )
    app.dependency_overrides.clear()


async def _make_device(api: SimpleNamespace) -> uuid.UUID:
    device = await api.devices.add(Device(name="rtr", hostname="10.0.0.1"))
    return device.id


_PROFILE = {"platform": "ios", "username": "netadmin", "password": "s3cret"}


@pytest.mark.asyncio
async def test_connection_profile_is_admin_only_and_hides_secrets(
    api: SimpleNamespace,
) -> None:
    device_id = await _make_device(api)
    async with _client() as c:
        oh = _auth(api.tokens["operator"])
        ah = _auth(api.tokens["admin"])

        denied = await c.put(
            f"/api/v1/devices/{device_id}/connection", headers=oh, json=_PROFILE
        )
        assert denied.status_code == 403

        created = await c.put(
            f"/api/v1/devices/{device_id}/connection", headers=ah, json=_PROFILE
        )
        assert created.status_code == 200
        body = created.json()
        assert body["username"] == "netadmin"
        assert "password" not in body  # secret never serialized
        assert body["has_enable_secret"] is False


@pytest.mark.asyncio
async def test_backup_run_dedup_and_content_access(
    api: SimpleNamespace,
) -> None:
    device_id = await _make_device(api)
    async with _client() as c:
        ah = _auth(api.tokens["admin"])
        oh = _auth(api.tokens["operator"])
        vh = _auth(api.tokens["viewer"])

        await c.put(
            f"/api/v1/devices/{device_id}/connection", headers=ah, json=_PROFILE
        )

        first = await c.post(
            f"/api/v1/devices/{device_id}/backups", headers=oh
        )
        assert first.status_code == 201
        assert first.json()["status"] == "success"
        backup_id = first.json()["id"]

        # Unchanged config -> deduplicated -> 200.
        second = await c.post(
            f"/api/v1/devices/{device_id}/backups", headers=oh
        )
        assert second.status_code == 200

        # Viewer can list metadata but not read content.
        listed = await c.get(
            f"/api/v1/devices/{device_id}/backups", headers=vh
        )
        assert listed.status_code == 200 and len(listed.json()) == 1
        assert (
            await c.get(f"/api/v1/backups/{backup_id}/content", headers=vh)
        ).status_code == 403
        content = await c.get(
            f"/api/v1/backups/{backup_id}/content", headers=oh
        )
        assert content.status_code == 200
        assert content.json()["content"] == "hostname r1\n!"


@pytest.mark.asyncio
async def test_backup_without_profile_returns_400(api: SimpleNamespace) -> None:
    device_id = await _make_device(api)
    async with _client() as c:
        r = await c.post(
            f"/api/v1/devices/{device_id}/backups",
            headers=_auth(api.tokens["admin"]),
        )
        assert r.status_code == 400
