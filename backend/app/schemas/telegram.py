"""Telegram schemas (request/response contracts)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.alert import AlertSeverity
from app.models.telegram import ChatType


class TelegramUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    telegram_user_id: int
    username: str | None
    first_name: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class TelegramUserUpdate(BaseModel):
    """Admins toggle authorization for a Telegram user."""

    is_active: bool | None = None
    username: str | None = Field(default=None, max_length=255)


class TelegramChatBase(BaseModel):
    chat_id: int
    title: str | None = Field(default=None, max_length=255)
    chat_type: ChatType = ChatType.PRIVATE
    is_active: bool = True
    min_severity: AlertSeverity = AlertSeverity.INFO


class TelegramChatCreate(TelegramChatBase):
    """Register a chat to receive routed alerts."""


class TelegramChatUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    chat_type: ChatType | None = None
    is_active: bool | None = None
    min_severity: AlertSeverity | None = None


class TelegramChatOut(TelegramChatBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
