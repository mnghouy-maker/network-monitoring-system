"""Server health services: server inventory and health polling."""

import logging
import uuid
from dataclasses import dataclass

from app.core.crypto import decrypt_secret, encrypt_secret
from app.health.protocols import HealthCollector, HealthSample, HealthTarget
from app.models.server import (
    Server,
    ServerHealthCheck,
    ServerHealthStatus,
    ServerMonitorMethod,
)
from app.repositories.server import ServerHealthRepository, ServerRepository
from app.schemas.server import ServerCreate, ServerUpdate
from app.services.exceptions import (
    EntityAlreadyExistsError,
    EntityNotFoundError,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class HealthThresholds:
    """warn/crit percentage thresholds per resource."""

    cpu_warn: float
    cpu_crit: float
    memory_warn: float
    memory_crit: float
    disk_warn: float
    disk_crit: float


def classify_health(
    sample: HealthSample, thresholds: HealthThresholds
) -> ServerHealthStatus:
    """Classify a health sample against thresholds (pure)."""
    if not sample.reachable:
        return ServerHealthStatus.UNREACHABLE

    gauges = (
        (sample.cpu_percent, thresholds.cpu_warn, thresholds.cpu_crit),
        (sample.memory_percent, thresholds.memory_warn, thresholds.memory_crit),
        (sample.disk_percent, thresholds.disk_warn, thresholds.disk_crit),
    )
    status = ServerHealthStatus.HEALTHY
    for value, warn, crit in gauges:
        if value is None:
            continue
        if value >= crit:
            return ServerHealthStatus.CRITICAL
        if value >= warn:
            status = ServerHealthStatus.WARNING
    return status


class ServerService:
    """Manage the server inventory (with encrypted SSH passwords)."""

    def __init__(self, repository: ServerRepository) -> None:
        self._repo = repository

    async def get(self, server_id: uuid.UUID) -> Server:
        server = await self._repo.get(server_id)
        if server is None:
            raise EntityNotFoundError(f"Server {server_id} not found")
        return server

    async def list(self, *, skip: int = 0, limit: int = 100) -> list[Server]:
        return await self._repo.list(skip=skip, limit=limit)

    async def create(self, payload: ServerCreate) -> Server:
        if await self._repo.get_by_name(payload.name):
            raise EntityAlreadyExistsError(
                f"A server named {payload.name!r} already exists"
            )
        data = payload.model_dump(exclude={"ssh_password"})
        server = Server(**data)
        if payload.ssh_password:
            server.ssh_password_encrypted = encrypt_secret(payload.ssh_password)
        return await self._repo.add(server)

    async def update(
        self, server_id: uuid.UUID, payload: ServerUpdate
    ) -> Server:
        server = await self.get(server_id)
        data = payload.model_dump(exclude_unset=True)

        new_name = data.get("name")
        if new_name and new_name != server.name:
            if await self._repo.get_by_name(new_name):
                raise EntityAlreadyExistsError(
                    f"A server named {new_name!r} already exists"
                )
        if "ssh_password" in data:
            password = data.pop("ssh_password")
            server.ssh_password_encrypted = (
                encrypt_secret(password) if password else None
            )
        for field, value in data.items():
            setattr(server, field, value)
        return await self._repo.update(server)

    async def delete(self, server_id: uuid.UUID) -> None:
        await self._repo.delete(await self.get(server_id))


class ServerHealthService:
    """Poll servers, classify and persist health snapshots."""

    def __init__(
        self,
        server_repo: ServerRepository,
        health_repo: ServerHealthRepository,
        local_collector: HealthCollector,
        ssh_collector: HealthCollector,
        thresholds: HealthThresholds,
        ssh_timeout: float = 15.0,
    ) -> None:
        self._servers = server_repo
        self._health = health_repo
        self._local = local_collector
        self._ssh = ssh_collector
        self._thresholds = thresholds
        self._timeout = ssh_timeout

    def _target(self, server: Server) -> HealthTarget:
        password = (
            decrypt_secret(server.ssh_password_encrypted)
            if server.ssh_password_encrypted
            else None
        )
        return HealthTarget(
            hostname=server.hostname,
            ssh_port=server.ssh_port,
            ssh_username=server.ssh_username,
            ssh_password=password,
            timeout=self._timeout,
        )

    async def poll_server(self, server: Server) -> ServerHealthCheck:
        collector = (
            self._ssh
            if server.monitor_method is ServerMonitorMethod.SSH
            else self._local
        )
        error: str | None = None
        try:
            sample = await collector.collect(self._target(server))
        except Exception as exc:  # noqa: BLE001 - record as unreachable
            logger.warning("Health poll failed for %s: %s", server.name, exc)
            sample = HealthSample(reachable=False)
            error = str(exc)[:2000]

        status = classify_health(sample, self._thresholds)
        check = ServerHealthCheck(
            server_id=server.id,
            reachable=sample.reachable,
            status=status,
            cpu_percent=sample.cpu_percent,
            memory_percent=sample.memory_percent,
            disk_percent=sample.disk_percent,
            load1=sample.load1,
            load5=sample.load5,
            load15=sample.load15,
            uptime_seconds=sample.uptime_seconds,
            error=error,
        )
        return await self._health.add(check)

    async def poll_server_by_id(
        self, server_id: uuid.UUID
    ) -> ServerHealthCheck:
        server = await self._servers.get(server_id)
        if server is None:
            raise EntityNotFoundError(f"Server {server_id} not found")
        return await self.poll_server(server)

    async def poll_all_active(self) -> list[ServerHealthCheck]:
        results: list[ServerHealthCheck] = []
        for server in await self._servers.list_active():
            try:
                results.append(await self.poll_server(server))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Health poll error for %s: %s", server.name, exc)
        return results

    async def get_latest(
        self, server_id: uuid.UUID
    ) -> ServerHealthCheck | None:
        await self._ensure_exists(server_id)
        return await self._health.get_latest(server_id)

    async def get_history(
        self, server_id: uuid.UUID, *, skip: int = 0, limit: int = 100
    ) -> list[ServerHealthCheck]:
        await self._ensure_exists(server_id)
        return await self._health.list_for_server(
            server_id, skip=skip, limit=limit
        )

    async def _ensure_exists(self, server_id: uuid.UUID) -> None:
        if await self._servers.get(server_id) is None:
            raise EntityNotFoundError(f"Server {server_id} not found")
