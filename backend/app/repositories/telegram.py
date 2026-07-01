"""Repositories for Telegram users and chats."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.telegram import TelegramChat, TelegramUser


class TelegramUserRepository:
    """CRUD for :class:`~app.models.telegram.TelegramUser`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, pk: uuid.UUID) -> TelegramUser | None:
        return await self._session.get(TelegramUser, pk)

    async def get_by_telegram_id(
        self, telegram_user_id: int
    ) -> TelegramUser | None:
        result = await self._session.execute(
            select(TelegramUser).where(
                TelegramUser.telegram_user_id == telegram_user_id
            )
        )
        return result.scalar_one_or_none()

    async def list(self, *, skip: int = 0, limit: int = 100) -> list[TelegramUser]:
        result = await self._session.execute(
            select(TelegramUser)
            .order_by(TelegramUser.created_at)
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def add(self, user: TelegramUser) -> TelegramUser:
        self._session.add(user)
        await self._session.flush()
        await self._session.refresh(user)
        return user

    async def update(self, user: TelegramUser) -> TelegramUser:
        await self._session.flush()
        await self._session.refresh(user)
        return user


class TelegramChatRepository:
    """CRUD for :class:`~app.models.telegram.TelegramChat`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, pk: uuid.UUID) -> TelegramChat | None:
        return await self._session.get(TelegramChat, pk)

    async def get_by_chat_id(self, chat_id: int) -> TelegramChat | None:
        result = await self._session.execute(
            select(TelegramChat).where(TelegramChat.chat_id == chat_id)
        )
        return result.scalar_one_or_none()

    async def list(self, *, skip: int = 0, limit: int = 100) -> list[TelegramChat]:
        result = await self._session.execute(
            select(TelegramChat)
            .order_by(TelegramChat.created_at)
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_active(self) -> list[TelegramChat]:
        result = await self._session.execute(
            select(TelegramChat).where(TelegramChat.is_active.is_(True))
        )
        return list(result.scalars().all())

    async def add(self, chat: TelegramChat) -> TelegramChat:
        self._session.add(chat)
        await self._session.flush()
        await self._session.refresh(chat)
        return chat

    async def update(self, chat: TelegramChat) -> TelegramChat:
        await self._session.flush()
        await self._session.refresh(chat)
        return chat

    async def delete(self, chat: TelegramChat) -> None:
        await self._session.delete(chat)
        await self._session.flush()
