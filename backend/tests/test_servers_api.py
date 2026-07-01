"""API/integration tests for the server health router."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest

from app.core import dependencies as deps
from app.core.security import create_access_token, hash_password
from app.health.protocols import HealthSample
from app.main import app
from app.models.user import User, UserRole
from app.services.server_health import HealthThresholds, ServerHealthService
from tests.conftest import (
    FakeHealthCollector,
    FakeServerHealthRepository,
    FakeServerRepository,
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


_TH = HealthThresholds(80, 95, 80, 95, 80, 95)


@pytest.fixture
def api() -> Iterator[SimpleNamespace]:
    users = FakeUserRepository()
    servers = FakeServerRepository()
    health = FakeServerHealthRepository()
    collector = FakeHealthCollector(
        HealthSample(cpu_percent=88, memory_percent=20, disk_percent=30)
    )
    health_service = ServerHealthService(
        servers, health, collector, collector, _TH
    )

    app.dependency_overrides.update(
        {
            deps.get_user_repository: lambda: users,
            deps.get_server_repository: lambda: servers,
            deps.get_server_health_repository: lambda: health,
            deps.get_server_health_service: lambda: health_service,
        }
    )
    admin = _seed_user(users, "admin", UserRole.ADMIN)
    operator = _seed_user(users, "oper", UserRole.OPERATOR)
    viewer = _seed_user(users, "view", UserRole.VIEWER)

    yield SimpleNamespace(
        tokens={
            "admin": create_access_token(admin.id),
            "operator": create_access_token(operator.id),
            "viewer": create_access_token(viewer.id),
        }
    )
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_server_crud_rbac_and_secret_hidden(api: SimpleNamespace) -> None:
    async with _client() as c:
        vh = _auth(api.tokens["viewer"])
        oh = _auth(api.tokens["operator"])
        body = {
            "name": "app-1",
            "hostname": "10.0.0.5",
            "monitor_method": "ssh",
            "ssh_username": "ops",
            "ssh_password": "s3cret",
        }
        denied = await c.post("/api/v1/servers", headers=vh, json=body)
        assert denied.status_code == 403
        created = await c.post("/api/v1/servers", headers=oh, json=body)
        assert created.status_code == 201
        assert "ssh_password" not in created.json()
        assert created.json()["has_ssh_password"] is True
        # viewer can read
        assert (await c.get("/api/v1/servers", headers=vh)).status_code == 200


@pytest.mark.asyncio
async def test_poll_health_and_read(api: SimpleNamespace) -> None:
    async with _client() as c:
        oh = _auth(api.tokens["operator"])
        vh = _auth(api.tokens["viewer"])
        sid = (
            await c.post(
                "/api/v1/servers",
                headers=oh,
                json={"name": "app-2", "hostname": "127.0.0.1"},
            )
        ).json()["id"]

        # Viewer cannot poll.
        assert (
            await c.post(f"/api/v1/servers/{sid}/health/poll", headers=vh)
        ).status_code == 403

        poll = await c.post(f"/api/v1/servers/{sid}/health/poll", headers=oh)
        assert poll.status_code == 200
        assert poll.json()["status"] == "warning"  # cpu 88 -> warning
        assert poll.json()["cpu_percent"] == 88

        latest = await c.get(f"/api/v1/servers/{sid}/health/latest", headers=vh)
        assert latest.status_code == 200
        history = await c.get(
            f"/api/v1/servers/{sid}/health/history", headers=vh
        )
        assert history.status_code == 200 and len(history.json()) == 1


@pytest.mark.asyncio
async def test_latest_unknown_server_404(api: SimpleNamespace) -> None:
    async with _client() as c:
        r = await c.get(
            f"/api/v1/servers/{uuid.uuid4()}/health/latest",
            headers=_auth(api.tokens["operator"]),
        )
        assert r.status_code == 404
