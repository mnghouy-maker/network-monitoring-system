"""Alert endpoints: rules CRUD, alert history, acknowledgement, evaluation.

Reads are available to any authenticated user; mutating operations (rules,
acknowledgement, triggering evaluation) require Admin or Operator.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.dependencies import ActiveUser, AlertingSvc, require_roles
from app.models.alert import AlertSeverity
from app.models.user import UserRole
from app.schemas.alert import (
    AlertAcknowledgeRequest,
    AlertHistoryOut,
    AlertRuleCreate,
    AlertRuleOut,
    AlertRuleUpdate,
)
from app.services.exceptions import (
    AlertError,
    EntityNotFoundError,
)

router = APIRouter(prefix="/alerts", tags=["alerts"])

_can_manage = require_roles(UserRole.ADMIN, UserRole.OPERATOR)


# --- rules (declared first so static paths win over /{alert_id}) -------------
@router.get("/rules", response_model=list[AlertRuleOut], summary="List rules")
async def list_rules(
    service: AlertingSvc,
    _: ActiveUser,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AlertRuleOut]:
    rules = await service.list_rules(skip=skip, limit=limit)
    return [AlertRuleOut.model_validate(r) for r in rules]


@router.post(
    "/rules",
    response_model=AlertRuleOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create rule",
    dependencies=[Depends(_can_manage)],
)
async def create_rule(
    payload: AlertRuleCreate, service: AlertingSvc
) -> AlertRuleOut:
    try:
        rule = await service.create_rule(payload)
    except EntityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return AlertRuleOut.model_validate(rule)


@router.get(
    "/rules/{rule_id}", response_model=AlertRuleOut, summary="Get a rule"
)
async def get_rule(
    rule_id: uuid.UUID, service: AlertingSvc, _: ActiveUser
) -> AlertRuleOut:
    try:
        rule = await service.get_rule(rule_id)
    except EntityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return AlertRuleOut.model_validate(rule)


@router.patch(
    "/rules/{rule_id}",
    response_model=AlertRuleOut,
    summary="Update a rule",
    dependencies=[Depends(_can_manage)],
)
async def update_rule(
    rule_id: uuid.UUID, payload: AlertRuleUpdate, service: AlertingSvc
) -> AlertRuleOut:
    try:
        rule = await service.update_rule(rule_id, payload)
    except EntityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return AlertRuleOut.model_validate(rule)


@router.delete(
    "/rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a rule",
    dependencies=[Depends(_can_manage)],
)
async def delete_rule(rule_id: uuid.UUID, service: AlertingSvc) -> None:
    try:
        await service.delete_rule(rule_id)
    except EntityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


# --- evaluation --------------------------------------------------------------
@router.post(
    "/evaluate",
    response_model=list[AlertHistoryOut],
    summary="Evaluate all active devices",
    dependencies=[Depends(_can_manage)],
)
async def evaluate_all(service: AlertingSvc) -> list[AlertHistoryOut]:
    changed = await service.evaluate_all_active()
    return [AlertHistoryOut.model_validate(a) for a in changed]


@router.post(
    "/evaluate/{device_id}",
    response_model=list[AlertHistoryOut],
    summary="Evaluate one device",
    dependencies=[Depends(_can_manage)],
)
async def evaluate_device(
    device_id: uuid.UUID, service: AlertingSvc
) -> list[AlertHistoryOut]:
    try:
        changed = await service.evaluate_device_by_id(device_id)
    except EntityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return [AlertHistoryOut.model_validate(a) for a in changed]


# --- alert history / state ---------------------------------------------------
@router.get("", response_model=list[AlertHistoryOut], summary="Active alerts")
async def list_active(
    service: AlertingSvc,
    _: ActiveUser,
    severity: AlertSeverity | None = None,
) -> list[AlertHistoryOut]:
    alerts = await service.list_active(severity=severity)
    return [AlertHistoryOut.model_validate(a) for a in alerts]


@router.get(
    "/critical",
    response_model=list[AlertHistoryOut],
    summary="Active critical alerts",
)
async def list_critical(
    service: AlertingSvc, _: ActiveUser
) -> list[AlertHistoryOut]:
    alerts = await service.list_active(severity=AlertSeverity.CRITICAL)
    return [AlertHistoryOut.model_validate(a) for a in alerts]


@router.get(
    "/history", response_model=list[AlertHistoryOut], summary="Alert history"
)
async def list_history(
    service: AlertingSvc,
    _: ActiveUser,
    device_id: uuid.UUID | None = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AlertHistoryOut]:
    alerts = await service.list_history(
        device_id=device_id, skip=skip, limit=limit
    )
    return [AlertHistoryOut.model_validate(a) for a in alerts]


@router.post(
    "/{alert_id}/ack",
    response_model=AlertHistoryOut,
    summary="Acknowledge an alert",
    dependencies=[Depends(_can_manage)],
)
async def acknowledge(
    alert_id: uuid.UUID,
    payload: AlertAcknowledgeRequest,
    service: AlertingSvc,
) -> AlertHistoryOut:
    try:
        alert = await service.acknowledge(
            alert_id,
            telegram_user=None,
            note=payload.note,
        )
    except EntityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except AlertError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return AlertHistoryOut.model_validate(alert)