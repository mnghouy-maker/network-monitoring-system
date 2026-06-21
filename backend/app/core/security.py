"""Security primitives: password hashing and JWT creation/verification.

This module is intentionally framework-agnostic. It knows nothing about
FastAPI or the database, which keeps it easy to unit test in isolation.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

# bcrypt is the industry-standard adaptive password hash.
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Token "type" claim values so an access token can never be used as a refresh
# token (and vice-versa).
ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"


def hash_password(password: str) -> str:
    """Return a salted bcrypt hash for ``password``."""
    return _pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Check a plaintext password against a stored hash."""
    return _pwd_context.verify(plain_password, hashed_password)


def _create_token(
    subject: str | Any,
    token_type: str,
    expires_delta: timedelta,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Encode a signed JWT with standard registered claims."""
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_access_token(
    subject: str | Any, extra_claims: dict[str, Any] | None = None
) -> str:
    """Create a short-lived access token for ``subject`` (the user id)."""
    return _create_token(
        subject,
        ACCESS_TOKEN_TYPE,
        timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        extra_claims,
    )


def create_refresh_token(subject: str | Any) -> str:
    """Create a long-lived refresh token for ``subject`` (the user id)."""
    return _create_token(
        subject,
        REFRESH_TOKEN_TYPE,
        timedelta(minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES),
    )


def decode_token(token: str) -> dict[str, Any] | None:
    """Decode and verify a JWT.

    Returns the claims payload, or ``None`` if the token is invalid or
    expired. Callers decide what to do with a ``None`` result.
    """
    try:
        return jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
    except JWTError:
        return None
