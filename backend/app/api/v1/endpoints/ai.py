"""AI troubleshooting assistant endpoints.

* Chatting, creating and deleting sessions, and running a diagnosis — Admin
  or Operator (these calls consume LLM tokens and act on live context).
* Reading sessions and message history — any authenticated user.

All chat/diagnose calls return ``503`` when no provider is configured.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.dependencies import ActiveUser, TroubleshootingSvc, require_roles
from app.models.user import UserRole
from app.schemas.ai import (
    AIChatRequest,
    AIDiagnoseRequest,
    AIMessageOut,
    AISessionCreate,
    AISessionDetailOut,
    AISessionOut,
)
from app.services.exceptions import AIError, EntityNotFoundError, ServiceError

router = APIRouter(prefix="/ai", tags=["ai-assistant"])

_can_use = require_roles(UserRole.ADMIN, UserRole.OPERATOR)


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _unavailable(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
    )


@router.get(
    "/status",
    summary="Whether the AI assistant is configured",
)
async def ai_status(service: TroubleshootingSvc, _: ActiveUser) -> dict:
    return {"enabled": service.is_configured}


@router.get(
    "/sessions",
    response_model=list[AISessionOut],
    summary="List troubleshooting sessions",
)
async def list_sessions(
    service: TroubleshootingSvc,
    _: ActiveUser,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[AISessionOut]:
    sessions = await service.list_sessions(skip=skip, limit=limit)
    return [AISessionOut.model_validate(s) for s in sessions]


@router.post(
    "/sessions",
    response_model=AISessionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Open a troubleshooting session",
    dependencies=[Depends(_can_use)],
)
async def create_session(
    payload: AISessionCreate, service: TroubleshootingSvc
) -> AISessionOut:
    try:
        session = await service.create_session(payload)
    except EntityNotFoundError as exc:
        raise _not_found(exc) from exc
    except ServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return AISessionOut.model_validate(session)


@router.get(
    "/sessions/{session_id}",
    response_model=AISessionDetailOut,
    summary="Get a session with its messages",
)
async def get_session(
    session_id: uuid.UUID, service: TroubleshootingSvc, _: ActiveUser
) -> AISessionDetailOut:
    try:
        session = await service.get_session(session_id)
        messages = await service.list_messages(session_id)
    except EntityNotFoundError as exc:
        raise _not_found(exc) from exc
    detail = AISessionDetailOut.model_validate(session)
    detail.messages = [AIMessageOut.model_validate(m) for m in messages]
    return detail


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a session",
    dependencies=[Depends(_can_use)],
)
async def delete_session(
    session_id: uuid.UUID, service: TroubleshootingSvc
) -> None:
    try:
        await service.delete_session(session_id)
    except EntityNotFoundError as exc:
        raise _not_found(exc) from exc


@router.post(
    "/sessions/{session_id}/messages",
    response_model=AIMessageOut,
    summary="Send a message and get the assistant's reply",
    dependencies=[Depends(_can_use)],
)
async def send_message(
    session_id: uuid.UUID,
    payload: AIChatRequest,
    service: TroubleshootingSvc,
) -> AIMessageOut:
    try:
        reply = await service.send_message(session_id, payload.message)
    except EntityNotFoundError as exc:
        raise _not_found(exc) from exc
    except AIError as exc:
        raise _unavailable(exc) from exc
    return AIMessageOut.model_validate(reply)


@router.post(
    "/diagnose",
    response_model=AISessionDetailOut,
    status_code=status.HTTP_201_CREATED,
    summary="One-shot diagnosis: opens a session and returns the first reply",
    dependencies=[Depends(_can_use)],
)
async def diagnose(
    payload: AIDiagnoseRequest, service: TroubleshootingSvc
) -> AISessionDetailOut:
    try:
        session, _reply = await service.diagnose(
            payload.subject_type, payload.subject_id, payload.question
        )
        messages = await service.list_messages(session.id)
    except EntityNotFoundError as exc:
        raise _not_found(exc) from exc
    except AIError as exc:
        raise _unavailable(exc) from exc
    except ServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    detail = AISessionDetailOut.model_validate(session)
    detail.messages = [AIMessageOut.model_validate(m) for m in messages]
    return detail
