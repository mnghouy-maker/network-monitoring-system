"""servers and server health checks

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-21

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()

    monitor_method = postgresql.ENUM(
        "local", "ssh", name="server_monitor_method", create_type=False
    )
    health_status = postgresql.ENUM(
        "healthy",
        "warning",
        "critical",
        "unreachable",
        name="server_health_status",
        create_type=False,
    )
    for enum_type in (monitor_method, health_status):
        enum_type.create(bind, checkfirst=True)

    ts = lambda: sa.DateTime(timezone=True)  # noqa: E731

    op.create_table(
        "servers",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "monitor_method",
            monitor_method,
            server_default="local",
            nullable=False,
        ),
        sa.Column(
            "ssh_port", sa.Integer(), server_default=sa.text("22"), nullable=False
        ),
        sa.Column("ssh_username", sa.String(length=255), nullable=True),
        sa.Column("ssh_password_encrypted", sa.Text(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("created_at", ts(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", ts(), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(op.f("ix_servers_name"), "servers", ["name"], unique=True)

    op.create_table(
        "server_health_checks",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column("server_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "collected_at", ts(), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("reachable", sa.Boolean(), nullable=False),
        sa.Column("status", health_status, nullable=False),
        sa.Column("cpu_percent", sa.Float(), nullable=True),
        sa.Column("memory_percent", sa.Float(), nullable=True),
        sa.Column("disk_percent", sa.Float(), nullable=True),
        sa.Column("load1", sa.Float(), nullable=True),
        sa.Column("load5", sa.Float(), nullable=True),
        sa.Column("load15", sa.Float(), nullable=True),
        sa.Column("uptime_seconds", sa.BigInteger(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["server_id"], ["servers.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        op.f("ix_server_health_checks_server_id"),
        "server_health_checks",
        ["server_id"],
    )
    op.create_index(
        op.f("ix_server_health_checks_collected_at"),
        "server_health_checks",
        ["collected_at"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_server_health_checks_collected_at"),
        table_name="server_health_checks",
    )
    op.drop_index(
        op.f("ix_server_health_checks_server_id"),
        table_name="server_health_checks",
    )
    op.drop_table("server_health_checks")
    op.drop_index(op.f("ix_servers_name"), table_name="servers")
    op.drop_table("servers")

    bind = op.get_bind()
    for name in ("server_health_status", "server_monitor_method"):
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
