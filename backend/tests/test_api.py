"""API/integration tests driving the real ASGI app end to end.

These exercise routing, auth, RBAC, status codes and response serialization
without a database: the repository and collector *providers* are overridden with
the in-memory fakes from ``conftest``, so the full FastAPI dependency graph
(auth guards, services) runs for real while persistence is faked.
"""

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
from app.models.user import User, UserRole
from app.monitoring.types import InterfaceSample, MetricSample, PingResult
from app.services.monitoring import MonitoringService
from tests.conftest import (
    FakeDeviceRepository,
    FakeMetricCollector,
    FakeMetricRepository,
    FakePingCollector,
    FakeUserRepository,
)


def _seed_user(
    repo: FakeUserRepository,
    *,
    username: str,
    role: UserRole,
    password: str,
    is_superuser: bool = False,
) -> User:
    user = User(
        email=f"{username}@example.com",
        username=username,
        full_name=None,
        role=role,
        hashed_password=hash_password(password),
        is_active=True,
        is_superuser=is_superuser,
    )
    user.id = uuid.uuid4()
    user.created_at = user.updated_at = datetime.now(UTC)
    repo._by_id[user.id] = user
    return user


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def api() -> Iterator[SimpleNamespace]:
    users = FakeUserRepository()
    devices = FakeDeviceRepository()
    metrics = FakeMetricRepository()

    ping = FakePingCollector(
        PingResult(reachable=True, latency_ms=1.0, packet_loss_percent=0.0)
    )
    snmp = FakeMetricCollector(
        MetricSample(
            cpu_load_percent=10.0,
            memory_used_percent=20.0,
            uptime_seconds=100,
            interfaces=[
                InterfaceSample(name="eth0", if_index=1, oper_status="up")
            ],
        )
    )
    monitoring = MonitoringService(
        devices, metrics, ping, snmp, zabbix_collector=None
    )

    admin = _seed_user(
        users, username="admin", role=UserRole.ADMIN, password="adminpass1"
    )
    operator = _seed_user(
        users, username="oper", role=UserRole.OPERATOR, password="operpass1"
    )
    viewer = _seed_user(
        users, username="view", role=UserRole.VIEWER, password="viewpass1"
    )

    app.dependency_overrides[deps.get_user_repository] = lambda: users
    app.dependency_overrides[deps.get_device_repository] = lambda: devices
    app.dependency_overrides[deps.get_metric_repository] = lambda: metrics
    app.dependency_overrides[deps.get_monitoring_service] = lambda: monitoring

    yield SimpleNamespace(
        users=users,
        devices=devices,
        metrics=metrics,
        tokens={
            "admin": create_access_token(admin.id),
            "operator": create_access_token(operator.id),
            "viewer": create_access_token(viewer.id),
        },
        passwords={"admin": "adminpass1"},
    )

    app.dependency_overrides.clear()


# --- auth --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_login_and_me(api: SimpleNamespace) -> None:
    async with _client() as c:
        r = await c.post(
            "/api/v1/auth/login",
            data={"username": "admin", "password": "adminpass1"},
        )
        assert r.status_code == 200
        token = r.json()["access_token"]
        me = await c.get("/api/v1/auth/me", headers=_auth(token))
        assert me.status_code == 200
        assert me.json()["username"] == "admin"
        assert me.json()["role"] == "admin"


@pytest.mark.asyncio
async def test_login_wrong_password(api: SimpleNamespace) -> None:
    async with _client() as c:
        r = await c.post(
            "/api/v1/auth/login",
            data={"username": "admin", "password": "nope"},
        )
        assert r.status_code == 401


@pytest.mark.asyncio
async def test_unauthenticated_is_rejected(api: SimpleNamespace) -> None:
    async with _client() as c:
        assert (await c.get("/api/v1/devices")).status_code == 401


# --- device RBAC + CRUD ------------------------------------------------------
@pytest.mark.asyncio
async def test_viewer_can_read_but_not_write(api: SimpleNamespace) -> None:
    async with _client() as c:
        vh = _auth(api.tokens["viewer"])
        assert (await c.get("/api/v1/devices", headers=vh)).status_code == 200
        r = await c.post(
            "/api/v1/devices",
            headers=vh,
            json={"name": "d1", "hostname": "10.0.0.1"},
        )
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_operator_create_excludes_community_and_dedupes(
    api: SimpleNamespace,
) -> None:
    async with _client() as c:
        oh = _auth(api.tokens["operator"])
        r = await c.post(
            "/api/v1/devices",
            headers=oh,
            json={
                "name": "sw1",
                "hostname": "10.0.0.2",
                "category": "switch",
                "snmp_community": "s3cr3t",
            },
        )
        assert r.status_code == 201
        body = r.json()
        assert body["category"] == "switch"
        assert "snmp_community" not in body  # secret never serialized

        dup = await c.post(
            "/api/v1/devices",
            headers=oh,
            json={"name": "sw1", "hostname": "10.0.0.9"},
        )
        assert dup.status_code == 409


@pytest.mark.asyncio
async def test_device_get_patch_delete_lifecycle(api: SimpleNamespace) -> None:
    async with _client() as c:
        ah = _auth(api.tokens["admin"])
        created = (
            await c.post(
                "/api/v1/devices",
                headers=ah,
                json={"name": "r1", "hostname": "10.0.0.3"},
            )
        ).json()
        did = created["id"]

        assert (
            await c.get(f"/api/v1/devices/{uuid.uuid4()}", headers=ah)
        ).status_code == 404

        patched = await c.patch(
            f"/api/v1/devices/{did}",
            headers=ah,
            json={"location": "DC-B", "category": "router"},
        )
        assert patched.status_code == 200
        assert patched.json()["location"] == "DC-B"
        assert patched.json()["category"] == "router"

        assert (
            await c.delete(f"/api/v1/devices/{did}", headers=ah)
        ).status_code == 204
        assert (
            await c.get(f"/api/v1/devices/{did}", headers=ah)
        ).status_code == 404


@pytest.mark.asyncio
async def test_user_management_is_admin_only(api: SimpleNamespace) -> None:
    async with _client() as c:
        assert (
            await c.get("/api/v1/users", headers=_auth(api.tokens["viewer"]))
        ).status_code == 403
        r = await c.post(
            "/api/v1/users",
            headers=_auth(api.tokens["admin"]),
            json={
                "email": "new@example.com",
                "username": "newbie",
                "password": "newpass12",
                "role": "operator",
            },
        )
        assert r.status_code == 201
        assert r.json()["role"] == "operator"


# --- monitoring --------------------------------------------------------------
@pytest.mark.asyncio
async def test_poll_and_read_metrics(api: SimpleNamespace) -> None:
    async with _client() as c:
        oh = _auth(api.tokens["operator"])
        did = (
            await c.post(
                "/api/v1/devices",
                headers=oh,
                json={"name": "rtr", "hostname": "127.0.0.1"},
            )
        ).json()["id"]

        poll = await c.post(
            f"/api/v1/monitoring/devices/{did}/poll", headers=oh
        )
        assert poll.status_code == 200
        body = poll.json()
        assert body["reachable"] is True
        assert body["source"] == "snmp"
        assert body["cpu_load_percent"] == 10.0
        assert len(body["interfaces"]) == 1
        assert body["interfaces"][0]["name"] == "eth0"

        latest = await c.get(
            f"/api/v1/monitoring/devices/{did}/latest", headers=oh
        )
        assert latest.status_code == 200
        history = await c.get(
            f"/api/v1/monitoring/devices/{did}/history", headers=oh
        )
        assert history.status_code == 200
        assert len(history.json()) == 1


@pytest.mark.asyncio
async def test_viewer_cannot_poll(api: SimpleNamespace) -> None:
    async with _client() as c:
        ah = _auth(api.tokens["admin"])
        did = (
            await c.post(
                "/api/v1/devices",
                headers=ah,
                json={"name": "rtr2", "hostname": "127.0.0.1"},
            )
        ).json()["id"]
        r = await c.post(
            f"/api/v1/monitoring/devices/{did}/poll",
            headers=_auth(api.tokens["viewer"]),
        )
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_poll_zabbix_unconfigured_returns_400(
    api: SimpleNamespace,
) -> None:
    async with _client() as c:
        oh = _auth(api.tokens["operator"])
        did = (
            await c.post(
                "/api/v1/devices",
                headers=oh,
                json={"name": "rtr3", "hostname": "127.0.0.1"},
            )
        ).json()["id"]
        r = await c.post(
            f"/api/v1/monitoring/devices/{did}/poll?source=zabbix",
            headers=oh,
        )
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_metrics_for_unknown_device_404(api: SimpleNamespace) -> None:
    """B4: latest/history on an unknown device must be 404, not 200."""
    async with _client() as c:
        oh = _auth(api.tokens["operator"])
        ghost = uuid.uuid4()
        assert (
            await c.get(
                f"/api/v1/monitoring/devices/{ghost}/latest", headers=oh
            )
        ).status_code == 404
        assert (
            await c.get(
                f"/api/v1/monitoring/devices/{ghost}/history", headers=oh
            )
        ).status_code == 404
