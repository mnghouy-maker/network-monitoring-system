"""Alert notifier: routes alert/recovery messages to Telegram chats.

Routing is severity-based: an alert is delivered to every active chat whose
``min_severity`` is at or below the alert's severity.
"""

import logging

from app.models.alert import SEVERITY_RANK, AlertHistory
from app.models.device import Device
from app.repositories.telegram import TelegramChatRepository
from app.telegram.formatting import (
    ack_keyboard,
    format_alert,
    format_recovery,
)
from app.telegram.protocols import TelegramSender

logger = logging.getLogger(__name__)


class AlertNotifier:
    """Delivers alert and recovery notifications to routed Telegram chats."""

    def __init__(
        self, sender: TelegramSender, chat_repo: TelegramChatRepository
    ) -> None:
        self._sender = sender
        self._chats = chat_repo

    async def notify_alert(self, alert: AlertHistory, device: Device) -> int:
        """Send a firing alert with an Acknowledge button. Returns #sent."""
        if not self._sender.is_configured:
            logger.debug("Telegram disabled; alert not delivered")
            return 0
        text = format_alert(alert, device)
        keyboard = ack_keyboard(alert.id)
        return await self._broadcast(
            alert, text, reply_markup=keyboard
        )

    async def notify_recovery(self, alert: AlertHistory, device: Device) -> int:
        if not self._sender.is_configured:
            return 0
        text = format_recovery(alert, device)
        return await self._broadcast(alert, text, reply_markup=None)

    async def _broadcast(
        self,
        alert: AlertHistory,
        text: str,
        *,
        reply_markup: dict | None,
    ) -> int:
        sent = 0
        for chat in await self._chats.list_active():
            if SEVERITY_RANK[alert.severity] < SEVERITY_RANK[chat.min_severity]:
                continue
            if await self._sender.send_message(
                chat.chat_id, text, reply_markup=reply_markup
            ):
                sent += 1
        return sent
