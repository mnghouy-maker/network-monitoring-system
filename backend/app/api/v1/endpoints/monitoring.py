"""Network monitoring endpoints.

* Triggering a poll is an operational action — Admin or Operator only.
* Reading metrics (latest / history) — any authenticated active user.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.dependencies import ActiveUser, MonitoringSvc, require_roles
from app.models.metric import MetricSource
from app.models.user import UserRole
from app.schemas.metric import DeviceMetricOut
from app.services.exceptions import EntityNotFoundError, MonitoringError

router = APIRouter(prefix="/monitoring", tags=["monitoring"])

_can_poll = require_roles(UserRole.ADMIN, UserRole.OPERATOR)


@router.post(
    "/devices/{device_id}/poll",
    response_model=DeviceMetricOut,
    summary="Poll a device now",
    dependencies=[Depends(_can_poll)],
)
async def poll_device(
    device_id: uuid.UUID,
    service: MonitoringSvc,
    source: MetricSource = MetricSource.SNMP,
) -> DeviceMetricOut:
    """Run an on-demand poll (ping + SNMP/Zabbix) and store the snapshot."""
    try:
        metric = await service.poll_device_by_id(device_id, source=source)
    except EntityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except MonitoringError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return DeviceMetricOut.model_validate(metric)


@router.get(
    "/devices/{device_id}/latest",
    response_model=DeviceMetricOut,
    summary="Latest metric snapshot",
)
async def latest_metric(
    device_id: uuid.UUID, service: MonitoringSvc, _: ActiveUser
) -> DeviceMetricOut:
    try:
        metric = await service.get_latest(device_id)
    except EntityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    if metric is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No metrics recorded for this device yet",
        )
    return DeviceMetricOut.model_validate(metric)


@router.get(
    "/devices/{device_id}/history",
    response_model=list[DeviceMetricOut],
    summary="Metric history",
)
async def metric_history(
    device_id: uuid.UUID,
    service: MonitoringSvc,
    _: ActiveUser,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[DeviceMetricOut]:
    try:
        metrics = await service.get_history(device_id, skip=skip, limit=limit)
    except EntityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return [DeviceMetricOut.model_validate(m) for m in metrics]
