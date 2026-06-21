"""Authentication service: credential verification and token issuance."""

import uuid

from app.core.security import (
    REFRESH_TOKEN_TYPE,
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.models.user import User
from app.repositories.user import UserRepository
from app.schemas.token import Token
from app.services.exceptions import (
    InactiveUserError,
    InvalidCredentialsError,
)


class AuthService:
    """Handles login and token refresh."""

    def __init__(self, repository: UserRepository) -> None:
        self._repo = repository

    async def authenticate(self, username_or_email: str, password: str) -> User:
        """Verify credentials and return the user, or raise.

        Accepts either a username or an email in ``username_or_email`` so the
        login form is forgiving.
        """
        user = await self._repo.get_by_email(username_or_email)
        if user is None:
            user = await self._repo.get_by_username(username_or_email)
        if user is None or not verify_password(password, user.hashed_password):
            raise InvalidCredentialsError("Incorrect username or password")
        if not user.is_active:
            raise InactiveUserError("User account is disabled")
        return user

    def issue_tokens(self, user: User) -> Token:
        """Mint a fresh access/refresh token pair for ``user``."""
        return Token(
            access_token=create_access_token(
                user.id, extra_claims={"role": user.role.value}
            ),
            refresh_token=create_refresh_token(user.id),
        )

    async def login(self, username_or_email: str, password: str) -> Token:
        user = await self.authenticate(username_or_email, password)
        return self.issue_tokens(user)

    async def refresh(self, refresh_token: str) -> Token:
        """Exchange a valid refresh token for a new token pair."""
        claims = decode_token(refresh_token)
        if claims is None or claims.get("type") != REFRESH_TOKEN_TYPE:
            raise InvalidCredentialsError("Invalid refresh token")

        subject = claims.get("sub")
        try:
            user_id = uuid.UUID(str(subject))
        except (ValueError, TypeError) as exc:
            raise InvalidCredentialsError("Invalid refresh token") from exc

        user = await self._repo.get(user_id)
        if user is None or not user.is_active:
            raise InvalidCredentialsError("Invalid refresh token")
        return self.issue_tokens(user)
