"""Shared test fixtures.

These tests deliberately avoid a real database. The service layer depends only
on the ``UserRepository`` interface, so we substitute a lightweight in-memory
fake. This keeps unit tests fast and hermetic; database integration is covered
separately via Alembic/Docker in higher test tiers.
"""

import os
import uuid

import pytest

# Provide a SECRET_KEY before app modules import settings.
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")

from app.models.user import User  # noqa: E402


class FakeUserRepository:
    """In-memory stand-in for :class:`app.repositories.user.UserRepository`."""

    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, User] = {}

    async def get(self, user_id: uuid.UUID) -> User | None:
        return self._by_id.get(user_id)

    async def get_by_email(self, email: str) -> User | None:
        return next(
            (u for u in self._by_id.values() if u.email == email), None
        )

    async def get_by_username(self, username: str) -> User | None:
        return next(
            (u for u in self._by_id.values() if u.username == username), None
        )

    async def list(self, skip: int = 0, limit: int = 100) -> list[User]:
        return list(self._by_id.values())[skip : skip + limit]

    async def add(self, user: User) -> User:
        if user.id is None:
            user.id = uuid.uuid4()
        self._by_id[user.id] = user
        return user

    async def update(self, user: User) -> User:
        self._by_id[user.id] = user
        return user

    async def delete(self, user: User) -> None:
        self._by_id.pop(user.id, None)


@pytest.fixture
def fake_repo() -> FakeUserRepository:
    return FakeUserRepository()
