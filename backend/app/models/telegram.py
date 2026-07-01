"""Telegram models: users who interact with the bot and chats alerts go to."""

import enum
import uuid

from sqlalchemy import BigInteger, Boolean, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, pg_enum
from app.models.alert import AlertSeverity


class ChatType(enum.StrEnum):
    """Telegram chat kinds."""

    PRIVATE = "private"
    GROUP = "group"
    SUPERGROUP = "supergroup"
    CHANNEL = "channel"


class TelegramUser(Base, TimestampMixin):
    """A Telegram user authorized (or pending) to use the bot.

    Unknown users are auto-registered as ``is_active=False`` on first contact
    and must be enabled by a platform admin before they can run commands or
    acknowledge alerts — an allowlist on top of the bot token.
    """

    __tablename__ = "telegram_users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    telegram_user_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, index=True, nullable=False
    )
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    # Optional link to a platform user account.
    platform_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<TelegramUser tg_id={self.telegram_user_id} "
            f"active={self.is_active}>"
        )


class TelegramChat(Base, TimestampMixin):
    """A chat (private/group/channel) that receives routed alert messages."""

    __tablename__ = "telegram_chats"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    chat_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, index=True, nullable=False
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    chat_type: Mapped[ChatType] = mapped_column(
        pg_enum(ChatType, "chat_type"),
        default=ChatType.PRIVATE,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    # Routing: only alerts at or above this severity are delivered here.
    min_severity: Mapped[AlertSeverity] = mapped_column(
        pg_enum(AlertSeverity, "alert_severity"),
        default=AlertSeverity.INFO,
        nullable=False,
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<TelegramChat chat_id={self.chat_id} active={self.is_active}>"
