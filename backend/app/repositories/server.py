"""Repositories for servers and server health checks."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.server import Server, ServerHealthCheck


class ServerRepository:
    """CRUD for :class:`~app.models.server.Server`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, server_id: uuid.UUID) -> Server | None:
        return await self._session.get(Server, server_id)

    async def get_by_name(self, name: str) -> Server | None:
        result = await self._session.execute(
            select(Server).where(Server.name == name)
        )
        return result.scalar_one_or_none()

    async def list(self, *, skip: int = 0, limit: int = 100) -> list[Server]:
        result = await self._session.execute(
            select(Server).order_by(Server.name).offset(skip).limit(limit)
        )
        return list(result.scalars().all())

    async def list_active(self) -> list[Server]:
        result = await self._session.execute(
            select(Server).where(Server.is_active.is_(True))
        )
        return list(result.scalars().all())

    async def add(self, server: Server) -> Server:
        self._session.add(server)
        await self._session.flush()
        await self._session.refresh(server)
        return server

    async def update(self, server: Server) -> Server:
        await self._session.flush()
        await self._session.refresh(server)
        return server

    async def delete(self, server: Server) -> None:
        await self._session.delete(server)
        await self._session.flush()


class ServerHealthRepository:
    """Persistence and queries for server health snapshots."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, check: ServerHealthCheck) -> ServerHealthCheck:
        self._session.add(check)
        await self._session.flush()
        await self._session.refresh(check, attribute_names=["collected_at"])
        return check

    async def get_latest(
        self, server_id: uuid.UUID
    ) -> ServerHealthCheck | None:
        result = await self._session.execute(
            select(ServerHealthCheck)
            .where(ServerHealthCheck.server_id == server_id)
            .order_by(ServerHealthCheck.collected_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_for_server(
        self, server_id: uuid.UUID, *, skip: int = 0, limit: int = 100
    ) -> list[ServerHealthCheck]:
        result = await self._session.execute(
            select(ServerHealthCheck)
            .where(ServerHealthCheck.server_id == server_id)
            .order_by(ServerHealthCheck.collected_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())
