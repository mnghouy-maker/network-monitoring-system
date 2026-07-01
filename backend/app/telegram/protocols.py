"""Protocol for sending to Telegram, so services don't depend on the client."""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class TelegramSender(Protocol):
    """The slice of the Telegram Bot API the application needs."""

    @property
    def is_configured(self) -> bool:
        """Whether a bot token is configured (delivery enabled)."""
        ...

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        reply_markup: dict[str, Any] | None = None,
        parse_mode: str | None = "HTML",
    ) -> bool: ...

    async def answer_callback_query(
        self, callback_query_id: str, text: str | None = None
    ) -> bool: ...

    async def get_updates(
        self, offset: int | None = None, timeout: int = 0
    ) -> list[dict[str, Any]]: ...
