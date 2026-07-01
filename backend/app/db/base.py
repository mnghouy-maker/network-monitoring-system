"""SQLAlchemy declarative base and shared column mixins.

``Base`` is imported by every model and by Alembic's ``env.py`` so that
``Base.metadata`` knows about all tables for autogeneration.
"""

import enum
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Project-wide declarative base."""


# One SQLAlchemy type object per PG enum name, so an enum shared by several
# columns/tables (e.g. ``alert_severity``) maps to a single type rather than
# duplicate ``CREATE TYPE`` statements.
_ENUM_TYPES: dict[str, SAEnum] = {}


def pg_enum(enum_cls: type[enum.Enum], name: str) -> SAEnum:
    """Build (and memoize) a native PostgreSQL enum column type for ``enum_cls``.

    Crucially this stores the enum *value* (e.g. ``"admin"``) rather than the
    member *name* (``"ADMIN"``) that SQLAlchemy would use by default, keeping
    the ORM consistent with the lowercase values defined in the migrations.
    """
    cached = _ENUM_TYPES.get(name)
    if cached is None:
        cached = SAEnum(
            enum_cls,
            name=name,
            native_enum=True,
            values_callable=lambda cls: [member.value for member in cls],
        )
        _ENUM_TYPES[name] = cached
    return cached


class TimestampMixin:
    """Adds ``created_at`` / ``updated_at`` columns managed by the database."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
