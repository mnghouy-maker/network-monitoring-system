"""Server health monitoring endpoints.

* Server inventory writes and polling — Admin or Operator.
* Reads (list/get, health latest/history) — any authenticated user.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.dependencies import (
    ActiveUser,
    ServerHealthSvc,
    ServerSvc,
    require_roles,
)
from app.models.user import UserRole
from app.schemas.server import (
    ServerCreate,
    ServerHealthOut,
    ServerOut,
    ServerUpdate,
)
from app.services.exceptions import (
    EntityAlreadyExistsError,
    EntityNotFoundError,
)

router = APIRouter(prefix="/servers", tags=["servers"])

_can_write = require_roles(UserRole.ADMIN, UserRole.OPERATOR)


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("", response_model=list[ServerOut], summary="List servers")
async def list_servers(
    service: ServerSvc,
    _: ActiveUser,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[ServerOut]:
    servers = await service.list(skip=skip, limit=limit)
    return [ServerOut.model_validate(s) for s in servers]


@router.post(
    "",
    response_model=ServerOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a server",
    dependencies=[Depends(_can_write)],
)
async def create_server(payload: ServerCreate, service: ServerSvc) -> ServerOut:
    try:
        server = await service.create(payload)
    except EntityAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return ServerOut.model_validate(server)


@router.get("/{server_id}", response_model=ServerOut, summary="Get a server")
async def get_server(
    server_id: uuid.UUID, service: ServerSvc, _: ActiveUser
) -> ServerOut:
    try:
        server = await service.get(server_id)
    except EntityNotFoundError as exc:
        raise _not_found(exc) from exc
    return ServerOut.model_validate(server)


@router.patch(
    "/{server_id}",
    response_model=ServerOut,
    summary="Update a server",
    dependencies=[Depends(_can_write)],
)
async def update_server(
    server_id: uuid.UUID, payload: ServerUpdate, service: ServerSvc
) -> ServerOut:
    try:
        server = await service.update(server_id, payload)
    except EntityNotFoundError as exc:
        raise _not_found(exc) from exc
    except EntityAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return ServerOut.model_validate(server)


@router.delete(
    "/{server_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a server",
    dependencies=[Depends(_can_write)],
)
async def delete_server(server_id: uuid.UUID, service: ServerSvc) -> None:
    try:
        await service.delete(server_id)
    except EntityNotFoundError as exc:
        raise _not_found(exc) from exc


# --- health ------------------------------------------------------------------
@router.post(
    "/{server_id}/health/poll",
    response_model=ServerHealthOut,
    summary="Poll a server's health now",
    dependencies=[Depends(_can_write)],
)
async def poll_health(
    server_id: uuid.UUID, service: ServerHealthSvc
) -> ServerHealthOut:
    try:
        check = await service.poll_server_by_id(server_id)
    except EntityNotFoundError as exc:
        raise _not_found(exc) from exc
    return ServerHealthOut.model_validate(check)


@router.post(
    "/health/poll-all",
    response_model=list[ServerHealthOut],
    summary="Poll all active servers",
    dependencies=[Depends(_can_write)],
)
async def poll_all(service: ServerHealthSvc) -> list[ServerHealthOut]:
    checks = await service.poll_all_active()
    return [ServerHealthOut.model_validate(c) for c in checks]


@router.get(
    "/{server_id}/health/latest",
    response_model=ServerHealthOut,
    summary="Latest health snapshot",
)
async def latest_health(
    server_id: uuid.UUID, service: ServerHealthSvc, _: ActiveUser
) -> ServerHealthOut:
    try:
        check = await service.get_latest(server_id)
    except EntityNotFoundError as exc:
        raise _not_found(exc) from exc
    if check is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No health checks recorded for this server yet",
        )
    return ServerHealthOut.model_validate(check)


@router.get(
    "/{server_id}/health/history",
    response_model=list[ServerHealthOut],
    summary="Health history",
)
async def health_history(
    server_id: uuid.UUID,
    service: ServerHealthSvc,
    _: ActiveUser,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[ServerHealthOut]:
    try:
        checks = await service.get_history(server_id, skip=skip, limit=limit)
    except EntityNotFoundError as exc:
        raise _not_found(exc) from exc
    return [ServerHealthOut.model_validate(c) for c in checks]
