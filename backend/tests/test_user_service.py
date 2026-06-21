"""Unit tests for the user service business rules."""

import uuid

import pytest

from app.models.user import UserRole
from app.schemas.user import UserCreate, UserUpdate
from app.services.exceptions import (
    EntityAlreadyExistsError,
    EntityNotFoundError,
)
from app.services.user import UserService
from tests.conftest import FakeUserRepository


def _payload(**overrides: object) -> UserCreate:
    data: dict[str, object] = {
        "email": "alice@example.com",
        "username": "alice",
        "password": "supersecret",
        "role": UserRole.OPERATOR,
    }
    data.update(overrides)
    return UserCreate(**data)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_create_user_hashes_password(fake_repo: FakeUserRepository) -> None:
    service = UserService(fake_repo)  # type: ignore[arg-type]
    user = await service.create(_payload())
    assert user.email == "alice@example.com"
    assert user.role is UserRole.OPERATOR
    assert user.hashed_password != "supersecret"


@pytest.mark.asyncio
async def test_create_duplicate_email_raises(
    fake_repo: FakeUserRepository,
) -> None:
    service = UserService(fake_repo)  # type: ignore[arg-type]
    await service.create(_payload())
    with pytest.raises(EntityAlreadyExistsError):
        await service.create(_payload(username="alice2"))


@pytest.mark.asyncio
async def test_create_duplicate_username_raises(
    fake_repo: FakeUserRepository,
) -> None:
    service = UserService(fake_repo)  # type: ignore[arg-type]
    await service.create(_payload())
    with pytest.raises(EntityAlreadyExistsError):
        await service.create(_payload(email="other@example.com"))


@pytest.mark.asyncio
async def test_get_missing_user_raises(fake_repo: FakeUserRepository) -> None:
    service = UserService(fake_repo)  # type: ignore[arg-type]
    with pytest.raises(EntityNotFoundError):
        await service.get(uuid.uuid4())


@pytest.mark.asyncio
async def test_update_changes_role_and_password(
    fake_repo: FakeUserRepository,
) -> None:
    service = UserService(fake_repo)  # type: ignore[arg-type]
    user = await service.create(_payload())
    old_hash = user.hashed_password
    updated = await service.update(
        user.id, UserUpdate(role=UserRole.ADMIN, password="newpassword")
    )
    assert updated.role is UserRole.ADMIN
    assert updated.hashed_password != old_hash


@pytest.mark.asyncio
async def test_ensure_first_admin_is_idempotent(
    fake_repo: FakeUserRepository,
) -> None:
    service = UserService(fake_repo)  # type: ignore[arg-type]
    created = await service.ensure_first_admin(
        "admin@example.com", "admin", "password123"
    )
    assert created is not None
    assert created.role is UserRole.ADMIN
    assert created.is_superuser is True

    again = await service.ensure_first_admin(
        "admin@example.com", "admin", "password123"
    )
    assert again is None
