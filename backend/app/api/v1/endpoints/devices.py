"""Device inventory endpoints.

Authorization:
* Read (list/get) — any authenticated active user (incl. Viewer).
* Write (create/update/delete) — Admin or Operator.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.dependencies import ActiveUser, DeviceSvc, require_roles
from app.models.device import DeviceCategory
from app.models.user import UserRole
from app.schemas.device import DeviceCreate, DeviceOut, DeviceUpdate
from app.services.exceptions import (
    EntityAlreadyExistsError,
    EntityNotFoundError,
)

router = APIRouter(prefix="/devices", tags=["devices"])

# Operators and Admins may modify the inventory.
_can_write = require_roles(UserRole.ADMIN, UserRole.OPERATOR)


@router.get("", response_model=list[DeviceOut], summary="List devices")
async def list_devices(
    service: DeviceSvc,
    _: ActiveUser,
    category: DeviceCategory | None = None,
    is_active: bool | None = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[DeviceOut]:
    devices = await service.list(
        skip=skip, limit=limit, category=category, is_active=is_active
    )
    return [DeviceOut.model_validate(d) for d in devices]


@router.post(
    "",
    response_model=DeviceOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a device",
    dependencies=[Depends(_can_write)],
)
async def create_device(payload: DeviceCreate, service: DeviceSvc) -> DeviceOut:
    try:
        device = await service.create(payload)
    except EntityAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return DeviceOut.model_validate(device)


@router.get("/{device_id}", response_model=DeviceOut, summary="Get a device")
async def get_device(
    device_id: uuid.UUID, service: DeviceSvc, _: ActiveUser
) -> DeviceOut:
    try:
        device = await service.get(device_id)
    except EntityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return DeviceOut.model_validate(device)


@router.patch(
    "/{device_id}",
    response_model=DeviceOut,
    summary="Edit a device",
    dependencies=[Depends(_can_write)],
)
async def update_device(
    device_id: uuid.UUID, payload: DeviceUpdate, service: DeviceSvc
) -> DeviceOut:
    try:
        device = await service.update(device_id, payload)
    except EntityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except EntityAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return DeviceOut.model_validate(device)


@router.delete(
    "/{device_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a device",
    dependencies=[Depends(_can_write)],
)
async def delete_device(device_id: uuid.UUID, service: DeviceSvc) -> None:
    try:
        await service.delete(device_id)
    except EntityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
