"""Telegram endpoints: inbound webhook + admin management of users and chats.

The webhook is unauthenticated but gated by a shared secret in the URL path
(and optionally the ``X-Telegram-Bot-Api-Secret-Token`` header). User/chat
management requires an Admin platform account.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, status

from app.core.config import settings
from app.core.dependencies import (
    TelegramAdminSvc,
    TelegramDispatcher,
    require_roles,
)
from app.models.user import UserRole
from app.schemas.telegram import (
    TelegramChatCreate,
    TelegramChatOut,
    TelegramChatUpdate,
    TelegramUserOut,
    TelegramUserUpdate,
)
from app.services.exceptions import (
    EntityAlreadyExistsError,
    EntityNotFoundError,
)

router = APIRouter(prefix="/telegram", tags=["telegram"])

_admin_only = require_roles(UserRole.ADMIN)


@router.post("/webhook/{secret}", summary="Telegram update webhook")
async def telegram_webhook(
    secret: str,
    dispatcher: TelegramDispatcher,
    update: Annotated[dict[str, Any], Body(...)],
    x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None,
) -> dict[str, bool]:
    """Receive an update from Telegram and dispatch it.

    Returns 404 (rather than 401) on a bad/secret-less request so the endpoint's
    existence is not advertised to unauthenticated callers.
    """
    expected = settings.TELEGRAM_WEBHOOK_SECRET
    header_ok = (
        x_telegram_bot_api_secret_token == expected
        if x_telegram_bot_api_secret_token is not None
        else True
    )
    if not expected or secret != expected or not header_ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    await dispatcher.dispatch(update)
    return {"ok": True}


# --- Telegram users (authorization allowlist) --------------------------------
@router.get(
    "/users",
    response_model=list[TelegramUserOut],
    summary="List Telegram users",
    dependencies=[Depends(_admin_only)],
)
async def list_telegram_users(
    service: TelegramAdminSvc,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[TelegramUserOut]:
    users = await service.list_users(skip=skip, limit=limit)
    return [TelegramUserOut.model_validate(u) for u in users]


@router.patch(
    "/users/{user_id}",
    response_model=TelegramUserOut,
    summary="Authorize/deactivate a Telegram user",
    dependencies=[Depends(_admin_only)],
)
async def update_telegram_user(
    user_id: uuid.UUID,
    payload: TelegramUserUpdate,
    service: TelegramAdminSvc,
) -> TelegramUserOut:
    try:
        user = await service.update_user(user_id, payload)
    except EntityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return TelegramUserOut.model_validate(user)


# --- Telegram chats (alert routing targets) ----------------------------------
@router.get(
    "/chats",
    response_model=list[TelegramChatOut],
    summary="List alert chats",
    dependencies=[Depends(_admin_only)],
)
async def list_chats(
    service: TelegramAdminSvc,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[TelegramChatOut]:
    chats = await service.list_chats(skip=skip, limit=limit)
    return [TelegramChatOut.model_validate(c) for c in chats]


@router.post(
    "/chats",
    response_model=TelegramChatOut,
    status_code=status.HTTP_201_CREATED,
    summary="Register an alert chat",
    dependencies=[Depends(_admin_only)],
)
async def create_chat(
    payload: TelegramChatCreate, service: TelegramAdminSvc
) -> TelegramChatOut:
    try:
        chat = await service.create_chat(payload)
    except EntityAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return TelegramChatOut.model_validate(chat)


@router.patch(
    "/chats/{chat_pk}",
    response_model=TelegramChatOut,
    summary="Update an alert chat",
    dependencies=[Depends(_admin_only)],
)
async def update_chat(
    chat_pk: uuid.UUID, payload: TelegramChatUpdate, service: TelegramAdminSvc
) -> TelegramChatOut:
    try:
        chat = await service.update_chat(chat_pk, payload)
    except EntityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return TelegramChatOut.model_validate(chat)


@router.delete(
    "/chats/{chat_pk}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an alert chat",
    dependencies=[Depends(_admin_only)],
)
async def delete_chat(chat_pk: uuid.UUID, service: TelegramAdminSvc) -> None:
    try:
        await service.delete_chat(chat_pk)
    except EntityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc