"""Telegram bot: command handling and update dispatch.

``TelegramCommandService`` turns a command string into a reply (pure-ish: only
reads repositories), which makes it easy to test. ``TelegramUpdateDispatcher``
parses a raw Telegram update (from webhook or long-polling), resolves/registers
the sender, runs the command or acknowledges an alert, and replies.
"""

import logging
import uuid
from html import escape

from app.models.alert import AlertSeverity
from app.models.telegram import TelegramChat, TelegramUser
from app.repositories.alert import AlertHistoryRepository
from app.repositories.device import DeviceRepository
from app.repositories.metric import MetricRepository
from app.repositories.telegram import (
    TelegramChatRepository,
    TelegramUserRepository,
)
from app.schemas.telegram import (
    TelegramChatCreate,
    TelegramChatUpdate,
    TelegramUserUpdate,
)
from app.services.alerting import AlertingService
from app.services.exceptions import (
    EntityAlreadyExistsError,
    EntityNotFoundError,
    ServiceError,
)
from app.telegram.formatting import alert_type_label, severity_icon
from app.telegram.protocols import TelegramSender

logger = logging.getLogger(__name__)

_HELP = (
    "🤖 <b>NetOps Bot</b>\n"
    "/help — show this message\n"
    "/status — platform summary\n"
    "/devices — list devices\n"
    "/device &lt;hostname&gt; — device details\n"
    "/alerts — active alerts\n"
    "/critical — active critical alerts"
)


def _format_uptime(seconds: int) -> str:
    days, rem = divmod(int(seconds), 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


class TelegramCommandService:
    """Maps bot commands to reply text (HTML)."""

    def __init__(
        self,
        device_repo: DeviceRepository,
        metric_repo: MetricRepository,
        history_repo: AlertHistoryRepository,
    ) -> None:
        self._devices = device_repo
        self._metrics = metric_repo
        self._history = history_repo

    async def handle(self, text: str, user: TelegramUser | None) -> str:
        parts = text.strip().split()
        if not parts:
            return _HELP
        command = parts[0].lower().lstrip("/").split("@", 1)[0]
        args = parts[1:]

        if command == "start":
            return self._start_text(user)
        if command == "help":
            return _HELP
        if user is None or not user.is_active:
            return self._unauthorized(user)

        if command == "status":
            return await self._cmd_status()
        if command == "devices":
            return await self._cmd_devices()
        if command == "device":
            return await self._cmd_device(args)
        if command == "alerts":
            return await self._cmd_alerts()
        if command == "critical":
            return await self._cmd_critical()
        return "Unknown command. Send /help for the list of commands."

    # --- command handlers -------------------------------------------------
    def _start_text(self, user: TelegramUser | None) -> str:
        tid = user.telegram_user_id if user else "unknown"
        active = user.is_active if user else False
        if active:
            return "👋 You're authorized. Send /help to see commands."
        return (
            "👋 Welcome to the NetOps Bot.\n"
            f"Your Telegram ID is <code>{tid}</code>.\n"
            "Ask an administrator to authorize this ID."
        )

    def _unauthorized(self, user: TelegramUser | None) -> str:
        tid = user.telegram_user_id if user else "unknown"
        return (
            "⛔ You are not authorized to use this bot.\n"
            f"Your Telegram ID is <code>{tid}</code>; "
            "ask an administrator to enable it."
        )

    async def _cmd_status(self) -> str:
        devices = await self._devices.list(limit=10_000)
        active_devices = sum(1 for d in devices if d.is_active)
        alerts = await self._history.list_active()
        critical = sum(
            1 for a in alerts if a.severity is AlertSeverity.CRITICAL
        )
        return (
            "📊 <b>Platform status</b>\n"
            f"Devices: {len(devices)} ({active_devices} active)\n"
            f"Active alerts: {len(alerts)}\n"
            f"Critical: {critical}"
        )

    async def _cmd_devices(self) -> str:
        devices = await self._devices.list(limit=50)
        if not devices:
            return "No devices registered."
        lines = ["🖥 <b>Devices</b>"]
        for d in devices:
            lines.append(
                f"• <b>{escape(d.name)}</b> [{d.category.value}] "
                f"<code>{escape(d.hostname)}</code>"
            )
        return "\n".join(lines)

    async def _cmd_device(self, args: list[str]) -> str:
        if not args:
            return "Usage: /device &lt;hostname&gt;"
        query = args[0]
        devices = await self._devices.list(limit=10_000)
        device = next(
            (d for d in devices if query in (d.hostname, d.name)), None
        )
        if device is None:
            return f"No device found matching <code>{escape(query)}</code>."

        lines = [
            f"🖥 <b>{escape(device.name)}</b> <code>{escape(device.hostname)}</code>",
            f"Category: {device.category.value}",
        ]
        if device.location:
            lines.append(f"Location: {escape(device.location)}")

        latest = await self._metrics.get_latest(device.id)
        if latest is None:
            lines.append("No metrics collected yet.")
        else:
            lines.append(
                f"Status: {'🟢 online' if latest.reachable else '🔴 offline'}"
            )
            if latest.cpu_load_percent is not None:
                lines.append(f"CPU: {latest.cpu_load_percent:.0f}%")
            if latest.memory_used_percent is not None:
                lines.append(f"Memory: {latest.memory_used_percent:.0f}%")
            if latest.uptime_seconds is not None:
                lines.append(f"Uptime: {_format_uptime(latest.uptime_seconds)}")

        active = [
            a
            for a in await self._history.list_active()
            if a.device_id == device.id
        ]
        if active:
            lines.append("\n<b>Active alerts:</b>")
            for a in active:
                lines.append(
                    f"{severity_icon(a.severity)} "
                    f"{alert_type_label(a.alert_type)} ({a.status.value})"
                )
        return "\n".join(lines)

    async def _cmd_alerts(self) -> str:
        return await self._render_alerts(
            await self._history.list_active(), "Active alerts"
        )

    async def _cmd_critical(self) -> str:
        return await self._render_alerts(
            await self._history.list_active(severity=AlertSeverity.CRITICAL),
            "Critical alerts",
        )

    async def _render_alerts(self, alerts: list, title: str) -> str:
        if not alerts:
            return "✅ No active alerts."
        lines = [f"🔔 <b>{title}</b>"]
        for a in alerts:
            device = await self._devices.get(a.device_id)
            name = device.name if device else str(a.device_id)
            lines.append(
                f"{severity_icon(a.severity)} <b>{escape(name)}</b>: "
                f"{alert_type_label(a.alert_type)} ({a.status.value})"
            )
        return "\n".join(lines)


class TelegramUpdateDispatcher:
    """Processes a raw Telegram update from webhook or polling."""

    def __init__(
        self,
        sender: TelegramSender,
        command_service: TelegramCommandService,
        alerting_service: AlertingService,
        telegram_user_repo: TelegramUserRepository,
    ) -> None:
        self._sender = sender
        self._commands = command_service
        self._alerting = alerting_service
        self._users = telegram_user_repo

    async def dispatch(self, update: dict) -> None:
        if "callback_query" in update:
            await self._on_callback(update["callback_query"])
        elif "message" in update:
            await self._on_message(update["message"])

    async def _on_message(self, message: dict) -> None:
        text = message.get("text") or ""
        if not text.startswith("/"):
            return
        chat_id = (message.get("chat") or {}).get("id")
        if chat_id is None:
            return
        user = await self._resolve_user(message.get("from") or {})
        reply = await self._commands.handle(text, user)
        await self._sender.send_message(chat_id, reply)

    async def _on_callback(self, callback: dict) -> None:
        callback_id = callback.get("id")
        data = callback.get("data") or ""
        user = await self._resolve_user(callback.get("from") or {})

        if not data.startswith("ack:"):
            if callback_id:
                await self._sender.answer_callback_query(callback_id)
            return
        if user is None or not user.is_active:
            if callback_id:
                await self._sender.answer_callback_query(
                    callback_id, "Not authorized"
                )
            return

        message = "Acknowledged ✅"
        try:
            alert_id = uuid.UUID(data.split(":", 1)[1])
            await self._alerting.acknowledge(alert_id, telegram_user=user)
        except (ValueError, ServiceError):
            message = "Could not acknowledge this alert"
        if callback_id:
            await self._sender.answer_callback_query(callback_id, message)

    async def _resolve_user(self, from_obj: dict) -> TelegramUser | None:
        telegram_id = from_obj.get("id")
        if telegram_id is None:
            return None
        user = await self._users.get_by_telegram_id(telegram_id)
        if user is None:
            # Auto-register unknown users as inactive (pending authorization).
            user = TelegramUser(
                telegram_user_id=telegram_id,
                username=from_obj.get("username"),
                first_name=from_obj.get("first_name"),
                is_active=False,
            )
            await self._users.add(user)
        return user


class TelegramAdminService:
    """Admin management of Telegram users (authorization) and chats (routing)."""

    def __init__(
        self,
        user_repo: TelegramUserRepository,
        chat_repo: TelegramChatRepository,
    ) -> None:
        self._users = user_repo
        self._chats = chat_repo

    # --- users ------------------------------------------------------------
    async def list_users(
        self, *, skip: int = 0, limit: int = 100
    ) -> list[TelegramUser]:
        return await self._users.list(skip=skip, limit=limit)

    async def update_user(
        self, user_id: uuid.UUID, payload: TelegramUserUpdate
    ) -> TelegramUser:
        user = await self._users.get(user_id)
        if user is None:
            raise EntityNotFoundError(f"Telegram user {user_id} not found")
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(user, field, value)
        return await self._users.update(user)

    # --- chats ------------------------------------------------------------
    async def list_chats(
        self, *, skip: int = 0, limit: int = 100
    ) -> list[TelegramChat]:
        return await self._chats.list(skip=skip, limit=limit)

    async def get_chat(self, chat_pk: uuid.UUID) -> TelegramChat:
        chat = await self._chats.get(chat_pk)
        if chat is None:
            raise EntityNotFoundError(f"Telegram chat {chat_pk} not found")
        return chat

    async def create_chat(self, payload: TelegramChatCreate) -> TelegramChat:
        if await self._chats.get_by_chat_id(payload.chat_id):
            raise EntityAlreadyExistsError(
                f"Chat {payload.chat_id} is already registered"
            )
        return await self._chats.add(TelegramChat(**payload.model_dump()))

    async def update_chat(
        self, chat_pk: uuid.UUID, payload: TelegramChatUpdate
    ) -> TelegramChat:
        chat = await self.get_chat(chat_pk)
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(chat, field, value)
        return await self._chats.update(chat)

    async def delete_chat(self, chat_pk: uuid.UUID) -> None:
        chat = await self.get_chat(chat_pk)
        await self._chats.delete(chat)
