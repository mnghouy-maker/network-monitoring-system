"""User-related Pydantic schemas.

These define the public API contract and are deliberately separate from the
SQLAlchemy model so internal columns (e.g. ``hashed_password``) are never
serialized to clients.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.user import UserRole


class UserBase(BaseModel):
    """Fields shared between create/update/read schemas."""

    email: EmailStr
    username: str = Field(min_length=3, max_length=100)
    full_name: str | None = Field(default=None, max_length=255)
    role: UserRole = UserRole.VIEWER
    is_active: bool = True


class UserCreate(UserBase):
    """Payload for creating a user."""

    password: str = Field(min_length=8, max_length=128)


class UserUpdate(BaseModel):
    """Payload for partially updating a user. All fields optional."""

    email: EmailStr | None = None
    username: str | None = Field(default=None, min_length=3, max_length=100)
    full_name: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    role: UserRole | None = None
    is_active: bool | None = None


class UserOut(UserBase):
    """User representation returned to clients."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    is_superuser: bool
    created_at: datetime
    updated_at: datetime
