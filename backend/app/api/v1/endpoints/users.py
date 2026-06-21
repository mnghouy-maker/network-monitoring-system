"""User management endpoints.

Authorization model:
* Listing / creating / updating / deleting users requires the ADMIN role.
* Any active user can read their own profile via ``/auth/me``.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.dependencies import UserSvc, require_roles
from app.models.user import UserRole
from app.schemas.user import UserCreate, UserOut, UserUpdate
from app.services.exceptions import (
    EntityAlreadyExistsError,
    EntityNotFoundError,
)

router = APIRouter(
    prefix="/users",
    tags=["users"],
    # Every route in this router requires an authenticated ADMIN.
    dependencies=[Depends(require_roles(UserRole.ADMIN))],
)


@router.get("", response_model=list[UserOut], summary="List users")
async def list_users(
    service: UserSvc,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[UserOut]:
    users = await service.list(skip=skip, limit=limit)
    return [UserOut.model_validate(u) for u in users]


@router.post(
    "",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create user",
)
async def create_user(payload: UserCreate, service: UserSvc) -> UserOut:
    try:
        user = await service.create(payload)
    except EntityAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return UserOut.model_validate(user)


@router.get("/{user_id}", response_model=UserOut, summary="Get user by id")
async def get_user(user_id: uuid.UUID, service: UserSvc) -> UserOut:
    try:
        user = await service.get(user_id)
    except EntityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return UserOut.model_validate(user)


@router.patch("/{user_id}", response_model=UserOut, summary="Update user")
async def update_user(
    user_id: uuid.UUID, payload: UserUpdate, service: UserSvc
) -> UserOut:
    try:
        user = await service.update(user_id, payload)
    except EntityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except EntityAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return UserOut.model_validate(user)


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete user",
)
async def delete_user(user_id: uuid.UUID, service: UserSvc) -> None:
    try:
        await service.delete(user_id)
    except EntityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
