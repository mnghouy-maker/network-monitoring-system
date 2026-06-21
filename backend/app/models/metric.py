"""Monitoring metric models: device-level snapshots and interface statistics."""

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
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, pg_enum


class MetricSource(enum.StrEnum):
    """Where a metric snapshot was collected from."""

    SNMP = "snmp"
    ZABBIX = "zabbix"


class DeviceMetric(Base):
    """A point-in-time monitoring snapshot for a device.

    One row is written per poll. Reachability (ping) is always recorded; the
    SNMP/Zabbix-derived gauges are nullable because a device may be down or a
    given metric unavailable.
    """

    __tablename__ = "device_metrics"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    source: Mapped[MetricSource] = mapped_column(
        pg_enum(MetricSource, "metric_source"),
        nullable=False,
    )

    # Reachability (ICMP ping) -------------------------------------------
    reachable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    packet_loss_percent: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )

    # Health gauges -------------------------------------------------------
    cpu_load_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    memory_used_percent: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    uptime_seconds: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )

    device: Mapped["object"] = relationship(  # type: ignore[assignment]
        "Device", back_populates="metrics"
    )
    interfaces: Mapped[list["InterfaceStat"]] = relationship(
        back_populates="metric",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<DeviceMetric device_id={self.device_id} "
            f"reachable={self.reachable} source={self.source}>"
        )


class InterfaceStat(Base):
    """Per-interface statistics captured as part of a metric snapshot."""

    __tablename__ = "interface_stats"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    metric_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("device_metrics.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    if_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    oper_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    speed_bps: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    in_octets: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    out_octets: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    in_errors: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    out_errors: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    metric: Mapped["DeviceMetric"] = relationship(
        back_populates="interfaces"
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<InterfaceStat name={self.name!r} status={self.oper_status}>"
