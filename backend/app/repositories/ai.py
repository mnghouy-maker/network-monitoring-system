"""Repositories for AI troubleshooting sessions and messages."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai import AIMessage, AISession


class AISessionRepository:
    """CRUD for :class:`~app.models.ai.AISession`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, session_id: uuid.UUID) -> AISession | None:
        return await self._session.get(AISession, session_id)

    async def list(
        self, *, skip: int = 0, limit: int = 100
    ) -> list[AISession]:
        result = await self._session.execute(
            select(AISession)
            .order_by(AISession.updated_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def add(self, session: AISession) -> AISession:
        self._session.add(session)
        await self._session.flush()
        await self._session.refresh(session)
        return session

    async def touch(self, session: AISession) -> AISession:
        """Flush pending changes and refresh timestamps."""
        await self._session.flush()
        await self._session.refresh(session)
        return session

    async def delete(self, session: AISession) -> None:
        await self._session.delete(session)
        await self._session.flush()


class AIMessageRepository:
    """Persistence and queries for chat messages."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, message: AIMessage) -> AIMessage:
        self._session.add(message)
        await self._session.flush()
        await self._session.refresh(message)
        return message

    async def list_for_session(
        self, session_id: uuid.UUID, *, skip: int = 0, limit: int = 200
    ) -> list[AIMessage]:
        result = await self._session.execute(
            select(AIMessage)
            .where(AIMessage.session_id == session_id)
            .order_by(AIMessage.created_at)
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())
