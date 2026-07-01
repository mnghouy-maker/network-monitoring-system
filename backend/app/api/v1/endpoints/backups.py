"""Configuration backup endpoints.

Authorization:
* Connection profiles (contain credentials) — Admin only.
* Running backups — Admin or Operator.
* Backup metadata/listing — any authenticated user.
* Backup content and diffs (may contain sensitive config) — Admin or Operator.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.core.dependencies import (
    ActiveUser,
    ConfigBackupSvc,
    ConnectionProfileSvc,
    require_roles,
)
from app.models.backup import ConfigType
from app.models.user import UserRole
from app.schemas.backup import (
    ConfigBackupContentOut,
    ConfigBackupOut,
    ConfigDiffOut,
    ConnectionProfileOut,
    ConnectionProfileUpsert,
)
from app.services.exceptions import BackupError, EntityNotFoundError

router = APIRouter(tags=["backups"])

_admin_only = require_roles(UserRole.ADMIN)
_can_operate = require_roles(UserRole.ADMIN, UserRole.OPERATOR)


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# --- connection profiles (Admin) ---------------------------------------------
@router.put(
    "/devices/{device_id}/connection",
    response_model=ConnectionProfileOut,
    summary="Create/replace a device connection profile",
    dependencies=[Depends(_admin_only)],
)
async def upsert_connection(
    device_id: uuid.UUID,
    payload: ConnectionProfileUpsert,
    service: ConnectionProfileSvc,
) -> ConnectionProfileOut:
    try:
        profile = await service.upsert(device_id, payload)
    except EntityNotFoundError as exc:
        raise _not_found(exc) from exc
    return ConnectionProfileOut.model_validate(profile)


@router.get(
    "/devices/{device_id}/connection",
    response_model=ConnectionProfileOut,
    summary="Get a device connection profile",
    dependencies=[Depends(_admin_only)],
)
async def get_connection(
    device_id: uuid.UUID, service: ConnectionProfileSvc
) -> ConnectionProfileOut:
    try:
        profile = await service.get(device_id)
    except EntityNotFoundError as exc:
        raise _not_found(exc) from exc
    return ConnectionProfileOut.model_validate(profile)


@router.delete(
    "/devices/{device_id}/connection",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a device connection profile",
    dependencies=[Depends(_admin_only)],
)
async def delete_connection(
    device_id: uuid.UUID, service: ConnectionProfileSvc
) -> None:
    try:
        await service.delete(device_id)
    except EntityNotFoundError as exc:
        raise _not_found(exc) from exc


# --- running backups (Admin/Operator) ----------------------------------------
@router.post(
    "/devices/{device_id}/backups",
    response_model=ConfigBackupOut,
    summary="Back up a device now",
    dependencies=[Depends(_can_operate)],
)
async def run_backup(
    device_id: uuid.UUID,
    service: ConfigBackupSvc,
    response: Response,
    config_type: ConfigType = ConfigType.RUNNING,
) -> ConfigBackupOut:
    try:
        backup, created = await service.backup_device_by_id(
            device_id, config_type
        )
    except EntityNotFoundError as exc:
        raise _not_found(exc) from exc
    except BackupError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    response.status_code = (
        status.HTTP_201_CREATED if created else status.HTTP_200_OK
    )
    return ConfigBackupOut.model_validate(backup)


@router.post(
    "/backups/run",
    response_model=list[ConfigBackupOut],
    summary="Back up all devices with an active profile",
    dependencies=[Depends(_can_operate)],
)
async def run_all_backups(
    service: ConfigBackupSvc,
    config_type: ConfigType = ConfigType.RUNNING,
) -> list[ConfigBackupOut]:
    backups = await service.backup_all(config_type)
    return [ConfigBackupOut.model_validate(b) for b in backups]


# --- reads -------------------------------------------------------------------
@router.get(
    "/devices/{device_id}/backups",
    response_model=list[ConfigBackupOut],
    summary="List a device's backups",
)
async def list_backups(
    device_id: uuid.UUID,
    service: ConfigBackupSvc,
    _: ActiveUser,
    config_type: ConfigType | None = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[ConfigBackupOut]:
    backups = await service.list_for_device(
        device_id, config_type=config_type, skip=skip, limit=limit
    )
    return [ConfigBackupOut.model_validate(b) for b in backups]


@router.get(
    "/devices/{device_id}/backups/diff/latest",
    response_model=ConfigDiffOut,
    summary="Diff the two most recent successful backups",
    dependencies=[Depends(_can_operate)],
)
async def diff_latest(
    device_id: uuid.UUID,
    service: ConfigBackupSvc,
    config_type: ConfigType = ConfigType.RUNNING,
) -> ConfigDiffOut:
    try:
        frm, to, changed, diff = await service.diff_latest(
            device_id, config_type
        )
    except BackupError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return ConfigDiffOut(
        from_backup_id=frm, to_backup_id=to, changed=changed, diff=diff
    )


@router.get(
    "/backups/{backup_id}",
    response_model=ConfigBackupOut,
    summary="Get backup metadata",
)
async def get_backup(
    backup_id: uuid.UUID, service: ConfigBackupSvc, _: ActiveUser
) -> ConfigBackupOut:
    try:
        backup = await service.get(backup_id)
    except EntityNotFoundError as exc:
        raise _not_found(exc) from exc
    return ConfigBackupOut.model_validate(backup)


@router.get(
    "/backups/{backup_id}/content",
    response_model=ConfigBackupContentOut,
    summary="Get backup with full config text",
    dependencies=[Depends(_can_operate)],
)
async def get_backup_content(
    backup_id: uuid.UUID, service: ConfigBackupSvc
) -> ConfigBackupContentOut:
    try:
        backup = await service.get(backup_id)
    except EntityNotFoundError as exc:
        raise _not_found(exc) from exc
    return ConfigBackupContentOut.model_validate(backup)


@router.get(
    "/backups/{backup_id}/diff/{other_id}",
    response_model=ConfigDiffOut,
    summary="Diff two backups",
    dependencies=[Depends(_can_operate)],
)
async def diff_backups(
    backup_id: uuid.UUID, other_id: uuid.UUID, service: ConfigBackupSvc
) -> ConfigDiffOut:
    try:
        frm, to, changed, diff = await service.diff(backup_id, other_id)
    except EntityNotFoundError as exc:
        raise _not_found(exc) from exc
    return ConfigDiffOut(
        from_backup_id=frm, to_backup_id=to, changed=changed, diff=diff
    )
