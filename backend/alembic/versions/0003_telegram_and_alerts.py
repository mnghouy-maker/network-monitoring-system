"""telegram users/chats and alerting tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-21

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()

    # create_type=False: types are created explicitly below so create_table
    # does not also emit CREATE TYPE.
    alert_type = postgresql.ENUM(
        "device_offline",
        "device_online",
        "high_cpu",
        "high_memory",
        "high_disk",
        "high_interface_util",
        "packet_loss",
        name="alert_type",
        create_type=False,
    )
    alert_severity = postgresql.ENUM(
        "info", "warning", "critical", name="alert_severity", create_type=False
    )
    alert_status = postgresql.ENUM(
        "firing",
        "acknowledged",
        "resolved",
        name="alert_status",
        create_type=False,
    )
    chat_type = postgresql.ENUM(
        "private",
        "group",
        "supergroup",
        "channel",
        name="chat_type",
        create_type=False,
    )
    for enum_type in (alert_type, alert_severity, alert_status, chat_type):
        enum_type.create(bind, checkfirst=True)

    ts = lambda: sa.DateTime(timezone=True)  # noqa: E731

    # --- telegram_users --------------------------------------------------
    op.create_table(
        "telegram_users",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("first_name", sa.String(length=255), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("platform_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", ts(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", ts(), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(
        op.f("ix_telegram_users_telegram_user_id"),
        "telegram_users",
        ["telegram_user_id"],
        unique=True,
    )

    # --- telegram_chats --------------------------------------------------
    op.create_table(
        "telegram_chats",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column(
            "chat_type", chat_type, server_default="private", nullable=False
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "min_severity",
            alert_severity,
            server_default="info",
            nullable=False,
        ),
        sa.Column("created_at", ts(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", ts(), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(
        op.f("ix_telegram_chats_chat_id"),
        "telegram_chats",
        ["chat_id"],
        unique=True,
    )

    # --- alert_rules -----------------------------------------------------
    op.create_table(
        "alert_rules",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("alert_type", alert_type, nullable=False),
        sa.Column(
            "severity", alert_severity, server_default="warning", nullable=False
        ),
        sa.Column("threshold", sa.Float(), nullable=True),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "is_enabled",
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
        op.f("ix_alert_rules_device_id"), "alert_rules", ["device_id"]
    )

    # --- alert_history ---------------------------------------------------
    op.create_table(
        "alert_history",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rule_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("alert_type", alert_type, nullable=False),
        sa.Column("severity", alert_severity, nullable=False),
        sa.Column(
            "status", alert_status, server_default="firing", nullable=False
        ),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("threshold", sa.Float(), nullable=True),
        sa.Column(
            "triggered_at", ts(), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("resolved_at", ts(), nullable=True),
        sa.Column("created_at", ts(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["device_id"], ["devices.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["rule_id"], ["alert_rules.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        op.f("ix_alert_history_device_id"), "alert_history", ["device_id"]
    )
    op.create_index(
        op.f("ix_alert_history_triggered_at"), "alert_history", ["triggered_at"]
    )
    op.create_index(
        "ix_alert_history_device_type",
        "alert_history",
        ["device_id", "alert_type"],
    )
    op.create_index("ix_alert_history_status", "alert_history", ["status"])

    # --- alert_acknowledgements ------------------------------------------
    op.create_table(
        "alert_acknowledgements",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column("alert_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "telegram_user_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "acknowledged_at",
            ts(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["alert_id"], ["alert_history.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["telegram_user_id"], ["telegram_users.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        op.f("ix_alert_acknowledgements_alert_id"),
        "alert_acknowledgements",
        ["alert_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_alert_acknowledgements_alert_id"),
        table_name="alert_acknowledgements",
    )
    op.drop_table("alert_acknowledgements")

    op.drop_index("ix_alert_history_status", table_name="alert_history")
    op.drop_index("ix_alert_history_device_type", table_name="alert_history")
    op.drop_index(
        op.f("ix_alert_history_triggered_at"), table_name="alert_history"
    )
    op.drop_index(
        op.f("ix_alert_history_device_id"), table_name="alert_history"
    )
    op.drop_table("alert_history")

    op.drop_index(op.f("ix_alert_rules_device_id"), table_name="alert_rules")
    op.drop_table("alert_rules")

    op.drop_index(
        op.f("ix_telegram_chats_chat_id"), table_name="telegram_chats"
    )
    op.drop_table("telegram_chats")

    op.drop_index(
        op.f("ix_telegram_users_telegram_user_id"),
        table_name="telegram_users",
    )
    op.drop_table("telegram_users")

    bind = op.get_bind()
    for name in ("chat_type", "alert_status", "alert_severity", "alert_type"):
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
