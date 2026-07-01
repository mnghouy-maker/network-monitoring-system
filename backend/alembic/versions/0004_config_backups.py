"""device connection profiles and configuration backups

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-21

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()

    connection_method = postgresql.ENUM(
        "napalm", "netmiko", name="connection_method", create_type=False
    )
    config_type = postgresql.ENUM(
        "running", "startup", name="config_type", create_type=False
    )
    backup_status = postgresql.ENUM(
        "success", "failed", name="backup_status", create_type=False
    )
    for enum_type in (connection_method, config_type, backup_status):
        enum_type.create(bind, checkfirst=True)

    ts = lambda: sa.DateTime(timezone=True)  # noqa: E731

    # --- device_connection_profiles --------------------------------------
    op.create_table(
        "device_connection_profiles",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "method",
            connection_method,
            server_default="napalm",
            nullable=False,
        ),
        sa.Column("platform", sa.String(length=64), nullable=False),
        sa.Column(
            "ssh_port",
            sa.Integer(),
            server_default=sa.text("22"),
            nullable=False,
        ),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("password_encrypted", sa.Text(), nullable=False),
        sa.Column("enable_secret_encrypted", sa.Text(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("created_at", ts(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", ts(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["device_id"], ["devices.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        op.f("ix_device_connection_profiles_device_id"),
        "device_connection_profiles",
        ["device_id"],
        unique=True,
    )

    # --- config_backups --------------------------------------------------
    op.create_table(
        "config_backups",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "config_type", config_type, server_default="running", nullable=False
        ),
        sa.Column("method", connection_method, nullable=False),
        sa.Column("status", backup_status, nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", ts(), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["device_id"], ["devices.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        op.f("ix_config_backups_device_id"), "config_backups", ["device_id"]
    )
    op.create_index(
        op.f("ix_config_backups_created_at"), "config_backups", ["created_at"]
    )
    op.create_index(
        "ix_config_backups_device_type",
        "config_backups",
        ["device_id", "config_type"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_config_backups_device_type", table_name="config_backups"
    )
    op.drop_index(
        op.f("ix_config_backups_created_at"), table_name="config_backups"
    )
    op.drop_index(
        op.f("ix_config_backups_device_id"), table_name="config_backups"
    )
    op.drop_table("config_backups")

    op.drop_index(
        op.f("ix_device_connection_profiles_device_id"),
        table_name="device_connection_profiles",
    )
    op.drop_table("device_connection_profiles")

    bind = op.get_bind()
    for name in ("backup_status", "config_type", "connection_method"):
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
