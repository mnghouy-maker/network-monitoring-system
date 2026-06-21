"""Authentication endpoints: login and token refresh."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from app.core.dependencies import ActiveUser, AuthSvc
from app.schemas.token import Token, TokenRefreshRequest
from app.schemas.user import UserOut
from app.services.exceptions import (
    InactiveUserError,
    InvalidCredentialsError,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=Token, summary="Obtain JWT tokens")
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    auth_service: AuthSvc,
) -> Token:
    """Authenticate with username/email + password (OAuth2 password flow)."""
    try:
        return await auth_service.login(form_data.username, form_data.password)
    except InactiveUserError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


@router.post("/refresh", response_model=Token, summary="Refresh access token")
async def refresh(
    payload: TokenRefreshRequest,
    auth_service: AuthSvc,
) -> Token:
    """Exchange a valid refresh token for a new access/refresh pair."""
    try:
        return await auth_service.refresh(payload.refresh_token)
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc


@router.get("/me", response_model=UserOut, summary="Current user profile")
async def read_me(current_user: ActiveUser) -> UserOut:
    """Return the profile of the authenticated user."""
    return UserOut.model_validate(current_user)
