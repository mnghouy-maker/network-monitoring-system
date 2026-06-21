"""Device inventory model and related enumerations."""

import enum
import uuid

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, pg_enum


class DeviceCategory(enum.StrEnum):
    """High-level classification of a managed device."""

    ROUTER = "router"
    SWITCH = "switch"
    FIREWALL = "firewall"
    SERVER = "server"
    ACCESS_POINT = "access_point"
    LOAD_BALANCER = "load_balancer"
    OTHER = "other"


class SNMPVersion(enum.StrEnum):
    """Supported SNMP protocol versions for polling."""

    V1 = "v1"
    V2C = "v2c"
    V3 = "v3"


class Device(Base, TimestampMixin):
    """A network device tracked in the inventory and monitored."""

    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Identity / inventory ------------------------------------------------
    name: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    hostname: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[DeviceCategory] = mapped_column(
        pg_enum(DeviceCategory, "device_category"),
        default=DeviceCategory.OTHER,
        nullable=False,
        index=True,
    )
    vendor: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # SNMP polling configuration -----------------------------------------
    snmp_community: Mapped[str] = mapped_column(
        String(255), default="public", nullable=False
    )
    snmp_version: Mapped[SNMPVersion] = mapped_column(
        pg_enum(SNMPVersion, "snmp_version"),
        default=SNMPVersion.V2C,
        nullable=False,
    )
    snmp_port: Mapped[int] = mapped_column(
        Integer, default=161, nullable=False
    )

    # Zabbix integration --------------------------------------------------
    # Maps this inventory device to a Zabbix host (hostid) when monitored
    # through Zabbix rather than direct SNMP.
    zabbix_host_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )

    metrics: Mapped[list["DeviceMetric"]] = relationship(
        back_populates="device",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Device id={self.id} name={self.name!r} category={self.category}>"


# Imported at the bottom to avoid a circular import at module load time.
from app.models.metric import DeviceMetric  # noqa: E402
