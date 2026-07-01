"""Server health monitoring models."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, pg_enum


class ServerMonitorMethod(enum.StrEnum):
    """How a server's health is collected."""

    LOCAL = "local"  # the host running this platform, via psutil
    SSH = "ssh"  # a remote host, via SSH commands


class ServerHealthStatus(enum.StrEnum):
    """Classification of a health snapshot against thresholds."""

    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    UNREACHABLE = "unreachable"


class Server(Base, TimestampMixin):
    """A server (host) whose system health is monitored."""

    __tablename__ = "servers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    hostname: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    monitor_method: Mapped[ServerMonitorMethod] = mapped_column(
        pg_enum(ServerMonitorMethod, "server_monitor_method"),
        default=ServerMonitorMethod.LOCAL,
        nullable=False,
    )
    ssh_port: Mapped[int] = mapped_column(Integer, default=22, nullable=False)
    ssh_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ssh_password_encrypted: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )

    checks: Mapped[list["ServerHealthCheck"]] = relationship(
        back_populates="server",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @property
    def has_ssh_password(self) -> bool:
        return self.ssh_password_encrypted is not None

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Server name={self.name!r} method={self.monitor_method}>"


class ServerHealthCheck(Base):
    """A point-in-time health snapshot for a server."""

    __tablename__ = "server_health_checks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    server_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("servers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    reachable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[ServerHealthStatus] = mapped_column(
        pg_enum(ServerHealthStatus, "server_health_status"), nullable=False
    )
    cpu_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    memory_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    disk_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    load1: Mapped[float | None] = mapped_column(Float, nullable=True)
    load5: Mapped[float | None] = mapped_column(Float, nullable=True)
    load15: Mapped[float | None] = mapped_column(Float, nullable=True)
    uptime_seconds: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    server: Mapped["Server"] = relationship(back_populates="checks")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<ServerHealthCheck server_id={self.server_id} "
            f"status={self.status}>"
        )
