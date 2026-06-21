"""Unit tests for the authentication service."""

import pytest

from app.core.security import create_access_token
from app.schemas.user import UserCreate
from app.services.auth import AuthService
from app.services.exceptions import (
    InactiveUserError,
    InvalidCredentialsError,
)
from app.services.user import UserService
from tests.conftest import FakeUserRepository


async def _seed_user(
    repo: FakeUserRepository, *, active: bool = True
) -> None:
    service = UserService(repo)  # type: ignore[arg-type]
    user = await service.create(
        UserCreate(
            email="bob@example.com",
            username="bob",
            password="correct-horse",
        )
    )
    user.is_active = active


@pytest.mark.asyncio
async def test_login_success_returns_token_pair(
    fake_repo: FakeUserRepository,
) -> None:
    await _seed_user(fake_repo)
    auth = AuthService(fake_repo)  # type: ignore[arg-type]
    token = await auth.login("bob", "correct-horse")
    assert token.access_token
    assert token.refresh_token
    assert token.token_type == "bearer"


@pytest.mark.asyncio
async def test_login_with_email_works(fake_repo: FakeUserRepository) -> None:
    await _seed_user(fake_repo)
    auth = AuthService(fake_repo)  # type: ignore[arg-type]
    token = await auth.login("bob@example.com", "correct-horse")
    assert token.access_token


@pytest.mark.asyncio
async def test_login_wrong_password_raises(
    fake_repo: FakeUserRepository,
) -> None:
    await _seed_user(fake_repo)
    auth = AuthService(fake_repo)  # type: ignore[arg-type]
    with pytest.raises(InvalidCredentialsError):
        await auth.login("bob", "wrong")


@pytest.mark.asyncio
async def test_login_inactive_user_raises(
    fake_repo: FakeUserRepository,
) -> None:
    await _seed_user(fake_repo, active=False)
    auth = AuthService(fake_repo)  # type: ignore[arg-type]
    with pytest.raises(InactiveUserError):
        await auth.login("bob", "correct-horse")


@pytest.mark.asyncio
async def test_refresh_with_access_token_rejected(
    fake_repo: FakeUserRepository,
) -> None:
    await _seed_user(fake_repo)
    auth = AuthService(fake_repo)  # type: ignore[arg-type]
    # An access token must not be accepted by the refresh endpoint.
    user = await fake_repo.get_by_username("bob")
    assert user is not None
    access = create_access_token(user.id)
    with pytest.raises(InvalidCredentialsError):
        await auth.refresh(access)


@pytest.mark.asyncio
async def test_refresh_rotates_tokens(fake_repo: FakeUserRepository) -> None:
    await _seed_user(fake_repo)
    auth = AuthService(fake_repo)  # type: ignore[arg-type]
    initial = await auth.login("bob", "correct-horse")
    refreshed = await auth.refresh(initial.refresh_token)
    assert refreshed.access_token
    assert refreshed.refresh_token
