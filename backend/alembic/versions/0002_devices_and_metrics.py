"""device inventory and monitoring metrics

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-21

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()

    # create_type=False: the enum types are created explicitly below, so the
    # create_table calls must not also emit CREATE TYPE for these columns.
    device_category = postgresql.ENUM(
        "router",
        "switch",
        "firewall",
        "server",
        "access_point",
        "load_balancer",
        "other",
        name="device_category",
        create_type=False,
    )
    snmp_version = postgresql.ENUM(
        "v1", "v2c", "v3", name="snmp_version", create_type=False
    )
    metric_source = postgresql.ENUM(
        "snmp", "zabbix", name="metric_source", create_type=False
    )
    device_category.create(bind, checkfirst=True)
    snmp_version.create(bind, checkfirst=True)
    metric_source.create(bind, checkfirst=True)

    # --- devices ---------------------------------------------------------
    op.create_table(
        "devices",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column(
            "category",
            device_category,
            server_default="other",
            nullable=False,
        ),
        sa.Column("vendor", sa.String(length=100), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "snmp_community",
            sa.String(length=255),
            server_default="public",
            nullable=False,
        ),
        sa.Column(
            "snmp_version",
            snmp_version,
            server_default="v2c",
            nullable=False,
        ),
        sa.Column(
            "snmp_port",
            sa.Integer(),
            server_default=sa.text("161"),
            nullable=False,
        ),
        sa.Column("zabbix_host_id", sa.String(length=64), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(op.f("ix_devices_name"), "devices", ["name"], unique=True)
    op.create_index(
        op.f("ix_devices_category"), "devices", ["category"], unique=False
    )

    # --- device_metrics --------------------------------------------------
    op.create_table(
        "device_metrics",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            "device_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "collected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("source", metric_source, nullable=False),
        sa.Column("reachable", sa.Boolean(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("packet_loss_percent", sa.Float(), nullable=True),
        sa.Column("cpu_load_percent", sa.Float(), nullable=True),
        sa.Column("memory_used_percent", sa.Float(), nullable=True),
        sa.Column("uptime_seconds", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(
            ["device_id"], ["devices.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        op.f("ix_device_metrics_device_id"),
        "device_metrics",
        ["device_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_device_metrics_collected_at"),
        "device_metrics",
        ["collected_at"],
        unique=False,
    )

    # --- interface_stats -------------------------------------------------
    op.create_table(
        "interface_stats",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            "metric_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("if_index", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("oper_status", sa.String(length=32), nullable=True),
        sa.Column("speed_bps", sa.BigInteger(), nullable=True),
        sa.Column("in_octets", sa.BigInteger(), nullable=True),
        sa.Column("out_octets", sa.BigInteger(), nullable=True),
        sa.Column("in_errors", sa.BigInteger(), nullable=True),
        sa.Column("out_errors", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(
            ["metric_id"], ["device_metrics.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        op.f("ix_interface_stats_metric_id"),
        "interface_stats",
        ["metric_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_interface_stats_metric_id"), table_name="interface_stats"
    )
    op.drop_table("interface_stats")
    op.drop_index(
        op.f("ix_device_metrics_collected_at"), table_name="device_metrics"
    )
    op.drop_index(
        op.f("ix_device_metrics_device_id"), table_name="device_metrics"
    )
    op.drop_table("device_metrics")
    op.drop_index(op.f("ix_devices_category"), table_name="devices")
    op.drop_index(op.f("ix_devices_name"), table_name="devices")
    op.drop_table("devices")

    bind = op.get_bind()
    postgresql.ENUM(name="metric_source").drop(bind, checkfirst=True)
    postgresql.ENUM(name="snmp_version").drop(bind, checkfirst=True)
    postgresql.ENUM(name="device_category").drop(bind, checkfirst=True)
