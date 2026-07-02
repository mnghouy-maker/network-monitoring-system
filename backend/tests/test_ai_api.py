"""API/integration tests for the AI troubleshooting router."""

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


def _make_service(provider: FakeAIProvider) -> TroubleshootingService:
    return TroubleshootingService(
        session_repo=FakeAISessionRepository(),
        message_repo=FakeAIMessageRepository(),
        provider=provider,
        device_repo=FakeDeviceRepository(),
        metric_repo=FakeMetricRepository(),
        alert_repo=FakeAlertHistoryRepository(),
        server_repo=FakeServerRepository(),
        server_health_repo=FakeServerHealthRepository(),
        backup_repo=FakeConfigBackupRepository(),
        model="test-model",
    )


def _install(service: TroubleshootingService) -> SimpleNamespace:
    users = FakeUserRepository()
    app.dependency_overrides.update(
        {
            deps.get_user_repository: lambda: users,
            deps.get_troubleshooting_service: lambda: service,
        }
    )
    admin = _seed_user(users, "admin", UserRole.ADMIN)
    viewer = _seed_user(users, "view", UserRole.VIEWER)
    return SimpleNamespace(
        tokens={
            "admin": create_access_token(admin.id),
            "viewer": create_access_token(viewer.id),
        }
    )


@pytest.fixture
def api() -> Iterator[SimpleNamespace]:
    ctx = _install(_make_service(FakeAIProvider()))
    yield ctx
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_status_reports_enabled(api: SimpleNamespace) -> None:
    async with _client() as c:
        r = await c.get("/api/v1/ai/status", headers=_auth(api.tokens["admin"]))
        assert r.status_code == 200
        assert r.json()["enabled"] is True


@pytest.mark.asyncio
async def test_full_chat_flow_and_rbac(api: SimpleNamespace) -> None:
    async with _client() as c:
        ah = _auth(api.tokens["admin"])
        vh = _auth(api.tokens["viewer"])

        # Viewer cannot open a session.
        denied = await c.post(
            "/api/v1/ai/sessions", headers=vh, json={"subject_type": "general"}
        )
        assert denied.status_code == 403

        created = await c.post(
            "/api/v1/ai/sessions", headers=ah, json={"subject_type": "general"}
        )
        assert created.status_code == 201
        session_id = created.json()["id"]

        chat = await c.post(
            f"/api/v1/ai/sessions/{session_id}/messages",
            headers=ah,
            json={"message": "What is wrong?"},
        )
        assert chat.status_code == 200
        assert chat.json()["role"] == "assistant"
        assert chat.json()["content"] == "Here is my assessment."

        # Viewer can read the session and its messages.
        got = await c.get(f"/api/v1/ai/sessions/{session_id}", headers=vh)
        assert got.status_code == 200
        assert len(got.json()["messages"]) == 2


@pytest.mark.asyncio
async def test_diagnose_returns_session_with_reply(api: SimpleNamespace) -> None:
    async with _client() as c:
        r = await c.post(
            "/api/v1/ai/diagnose",
            headers=_auth(api.tokens["admin"]),
            json={"subject_type": "general"},
        )
        assert r.status_code == 201
        body = r.json()
        assert body["subject_type"] == "general"
        assert any(m["role"] == "assistant" for m in body["messages"])


@pytest.mark.asyncio
async def test_chat_returns_503_when_unconfigured() -> None:
    ctx = _install(_make_service(FakeAIProvider(configured=False)))
    try:
        async with _client() as c:
            ah = _auth(ctx.tokens["admin"])
            session_id = (
                await c.post(
                    "/api/v1/ai/sessions",
                    headers=ah,
                    json={"subject_type": "general"},
                )
            ).json()["id"]
            chat = await c.post(
                f"/api/v1/ai/sessions/{session_id}/messages",
                headers=ah,
                json={"message": "hi"},
            )
            assert chat.status_code == 503

            status = await c.get("/api/v1/ai/status", headers=ah)
            assert status.json()["enabled"] is False
    finally:
        app.dependency_overrides.clear()
