"""AI troubleshooting assistant models: chat sessions and messages."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, pg_enum


class AISubjectType(enum.StrEnum):
    """What a troubleshooting session is scoped to."""

    DEVICE = "device"  # a network device from the inventory
    SERVER = "server"  # a monitored server host
    GENERAL = "general"  # platform-wide / free-form


class AIMessageRole(enum.StrEnum):
    """Author of a chat message."""

    USER = "user"
    ASSISTANT = "assistant"


class AISession(Base, TimestampMixin):
    """A troubleshooting conversation, optionally scoped to a device/server."""

    __tablename__ = "ai_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject_type: Mapped[AISubjectType] = mapped_column(
        pg_enum(AISubjectType, "ai_subject_type"),
        default=AISubjectType.GENERAL,
        nullable=False,
    )
    # Points at a device or server id depending on ``subject_type``. Kept as a
    # loose reference (no FK) so a session survives the subject being deleted.
    subject_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )

    messages: Mapped[list["AIMessage"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AIMessage.created_at",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<AISession id={self.id} subject={self.subject_type} "
            f"subject_id={self.subject_id}>"
        )


class AIMessage(Base):
    """A single turn in an :class:`AISession`."""

    __tablename__ = "ai_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[AIMessageRole] = mapped_column(
        pg_enum(AIMessageRole, "ai_message_role"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Provider metadata, recorded for assistant turns only.
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    session: Mapped["AISession"] = relationship(back_populates="messages")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<AIMessage session_id={self.session_id} role={self.role}>"
