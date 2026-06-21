"""FastAPI dependency-injection wiring.

This is the composition root: it assembles repositories and services from a
request-scoped database session, and provides the auth guards used to protect
endpoints. Endpoints depend on these factories rather than constructing their
own collaborators, which keeps them thin and testable.
"""

import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import ACCESS_TOKEN_TYPE, decode_token
from app.db.session import get_session
from app.models.user import User, UserRole
from app.repositories.user import UserRepository
from app.services.auth import AuthService
from app.services.user import UserService

# tokenUrl is used by Swagger UI's "Authorize" button.
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_PREFIX}/auth/login"
)

# --- Session ------------------------------------------------------------------
DbSession = Annotated[AsyncSession, Depends(get_session)]


# --- Repositories -------------------------------------------------------------
def get_user_repository(session: DbSession) -> UserRepository:
    return UserRepository(session)


UserRepo = Annotated[UserRepository, Depends(get_user_repository)]


# --- Services -----------------------------------------------------------------
def get_user_service(repo: UserRepo) -> UserService:
    return UserService(repo)


def get_auth_service(repo: UserRepo) -> AuthService:
    return AuthService(repo)


UserSvc = Annotated[UserService, Depends(get_user_service)]
AuthSvc = Annotated[AuthService, Depends(get_auth_service)]


# --- Current user / auth guards ----------------------------------------------
_credentials_exc = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    repo: UserRepo,
) -> User:
    """Resolve the authenticated user from a bearer access token."""
    claims = decode_token(token)
    if claims is None or claims.get("type") != ACCESS_TOKEN_TYPE:
        raise _credentials_exc

    try:
        user_id = uuid.UUID(str(claims.get("sub")))
    except (ValueError, TypeError):
        raise _credentials_exc from None

    user = await repo.get(user_id)
    if user is None:
        raise _credentials_exc
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_current_active_user(current_user: CurrentUser) -> User:
    """Like :func:`get_current_user` but rejects disabled accounts."""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user"
        )
    return current_user


ActiveUser = Annotated[User, Depends(get_current_active_user)]


def require_roles(*allowed: UserRole) -> Callable[[User], Awaitable[User]]:
    """Build a dependency that authorizes only the given roles.

    Superusers always pass. Usage::

        @router.get(..., dependencies=[Depends(require_roles(UserRole.ADMIN))])
    """

    async def _guard(current_user: ActiveUser) -> User:
        if current_user.is_superuser or current_user.role in allowed:
            return current_user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions for this operation",
        )

    return _guard
