"""ai troubleshooting sessions and messages

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-27

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()

    subject_type = postgresql.ENUM(
        "device",
        "server",
        "general",
        name="ai_subject_type",
        create_type=False,
    )
    message_role = postgresql.ENUM(
        "user", "assistant", name="ai_message_role", create_type=False
    )
    for enum_type in (subject_type, message_role):
        enum_type.create(bind, checkfirst=True)

    ts = lambda: sa.DateTime(timezone=True)  # noqa: E731

    op.create_table(
        "ai_sessions",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column(
            "subject_type",
            subject_type,
            server_default="general",
            nullable=False,
        ),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", ts(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", ts(), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(
        op.f("ix_ai_sessions_subject_id"), "ai_sessions", ["subject_id"]
    )

    op.create_table(
        "ai_messages",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", message_role, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", ts(), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["ai_sessions.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        op.f("ix_ai_messages_session_id"), "ai_messages", ["session_id"]
    )
    op.create_index(
        op.f("ix_ai_messages_created_at"), "ai_messages", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_ai_messages_created_at"), table_name="ai_messages")
    op.drop_index(op.f("ix_ai_messages_session_id"), table_name="ai_messages")
    op.drop_table("ai_messages")
    op.drop_index(op.f("ix_ai_sessions_subject_id"), table_name="ai_sessions")
    op.drop_table("ai_sessions")

    bind = op.get_bind()
    for name in ("ai_message_role", "ai_subject_type"):
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
