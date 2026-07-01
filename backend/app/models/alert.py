"""Alerting models: rules, alert history, and acknowledgements."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, pg_enum


class AlertType(enum.StrEnum):
    """Conditions the alerting engine understands.

    ``DEVICE_ONLINE`` is not a rule type — it labels the recovery notification
    emitted when a ``DEVICE_OFFLINE`` alert resolves.
    """

    DEVICE_OFFLINE = "device_offline"
    DEVICE_ONLINE = "device_online"
    HIGH_CPU = "high_cpu"
    HIGH_MEMORY = "high_memory"
    HIGH_DISK = "high_disk"
    HIGH_INTERFACE_UTIL = "high_interface_util"
    PACKET_LOSS = "packet_loss"


class AlertSeverity(enum.StrEnum):
    """Severity levels, ordered by :data:`SEVERITY_RANK`."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


# Ordering helper (StrEnum has no natural ordering).
SEVERITY_RANK: dict[str, int] = {
    AlertSeverity.INFO: 0,
    AlertSeverity.WARNING: 1,
    AlertSeverity.CRITICAL: 2,
}


class AlertStatus(enum.StrEnum):
    """Lifecycle of an alert."""

    FIRING = "firing"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class AlertRule(Base, TimestampMixin):
    """A threshold/condition that produces alerts for one or all devices."""

    __tablename__ = "alert_rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    alert_type: Mapped[AlertType] = mapped_column(
        pg_enum(AlertType, "alert_type"), nullable=False
    )
    severity: Mapped[AlertSeverity] = mapped_column(
        pg_enum(AlertSeverity, "alert_severity"),
        default=AlertSeverity.WARNING,
        nullable=False,
    )
    # Threshold for gauge conditions (CPU/memory/disk/util/loss). Ignored for
    # device_offline. When NULL the engine falls back to a configured default.
    threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    # NULL device_id => the rule applies to every device.
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<AlertRule name={self.name!r} type={self.alert_type} "
            f"threshold={self.threshold}>"
        )


class AlertHistory(Base):
    """A fired alert and its lifecycle (firing → acknowledged → resolved)."""

    __tablename__ = "alert_history"
    __table_args__ = (
        Index("ix_alert_history_device_type", "device_id", "alert_type"),
        Index("ix_alert_history_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rule_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("alert_rules.id", ondelete="SET NULL"),
        nullable=True,
    )
    alert_type: Mapped[AlertType] = mapped_column(
        pg_enum(AlertType, "alert_type"), nullable=False
    )
    severity: Mapped[AlertSeverity] = mapped_column(
        pg_enum(AlertSeverity, "alert_severity"), nullable=False
    )
    status: Mapped[AlertStatus] = mapped_column(
        pg_enum(AlertStatus, "alert_status"),
        default=AlertStatus.FIRING,
        nullable=False,
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    acknowledgements: Mapped[list["AlertAcknowledgement"]] = relationship(
        back_populates="alert",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @property
    def is_active(self) -> bool:
        return self.status in (AlertStatus.FIRING, AlertStatus.ACKNOWLEDGED)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<AlertHistory device_id={self.device_id} type={self.alert_type} "
            f"status={self.status}>"
        )


class AlertAcknowledgement(Base):
    """Records who acknowledged an alert, and when."""

    __tablename__ = "alert_acknowledgements"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    alert_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("alert_history.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    telegram_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("telegram_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    acknowledged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    alert: Mapped["AlertHistory"] = relationship(
        back_populates="acknowledgements"
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<AlertAcknowledgement alert_id={self.alert_id}>"
