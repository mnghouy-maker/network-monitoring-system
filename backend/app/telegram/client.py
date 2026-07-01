"""Telegram Bot API client with rate limiting, retries and logging.

The client is a process-wide singleton (it holds the rate limiter's per-chat
state). Network I/O goes through ``_post``, which can be replaced via the
``http_post`` injection seam so the retry/backoff logic is unit-testable
without real HTTP.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app.telegram.rate_limit import RateLimiter

logger = logging.getLogger(__name__)

# (method, payload) -> (status_code, parsed_json_body)
HttpPost = Callable[[str, dict[str, Any]], Awaitable[tuple[int, dict[str, Any]]]]


class TelegramClient:
    """A thin async wrapper over the Telegram Bot API."""

    def __init__(
        self,
        token: str | None,
        *,
        base_url: str = "https://api.telegram.org",
        rate_limiter: RateLimiter | None = None,
        max_retries: int = 3,
        backoff_seconds: float = 0.5,
        timeout_seconds: float = 10.0,
        http_post: HttpPost | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._token = token
        self._base = f"{base_url.rstrip('/')}/bot{token}" if token else None
        self._rate_limiter = rate_limiter or RateLimiter(25.0, 1.0)
        self._max_retries = max(0, max_retries)
        self._backoff = backoff_seconds
        self._timeout = timeout_seconds
        self._http_post = http_post
        self._sleep = sleep

    @property
    def is_configured(self) -> bool:
        return bool(self._token)

    # --- public API -------------------------------------------------------
    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        reply_markup: dict[str, Any] | None = None,
        parse_mode: str | None = "HTML",
    ) -> bool:
        if not self.is_configured:
            logger.warning("Telegram not configured; dropping message to %s", chat_id)
            return False
        await self._rate_limiter.acquire(chat_id)
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return await self._request("sendMessage", payload) is not None

    async def answer_callback_query(
        self, callback_query_id: str, text: str | None = None
    ) -> bool:
        if not self.is_configured:
            return False
        payload: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        return await self._request("answerCallbackQuery", payload) is not None

    async def get_updates(
        self, offset: int | None = None, timeout: int = 0
    ) -> list[dict[str, Any]]:
        if not self.is_configured:
            return []
        payload: dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            payload["offset"] = offset
        result = await self._request("getUpdates", payload)
        return result if isinstance(result, list) else []

    # --- internals --------------------------------------------------------
    async def _request(self, method: str, payload: dict[str, Any]) -> Any:
        """Call ``method`` with retries; return the API ``result`` or ``None``."""
        for attempt in range(self._max_retries + 1):
            try:
                status, body = await self._post(method, payload)
            except Exception as exc:  # noqa: BLE001 - network errors are retried
                await self._backoff_sleep(attempt, f"network error: {exc}")
                continue

            if status == 200 and body.get("ok"):
                return body.get("result")

            if status == 429:
                retry_after = float(
                    body.get("parameters", {}).get("retry_after", 0)
                ) or self._backoff_for(attempt)
                logger.warning(
                    "Telegram rate-limited (%s); retrying in %.1fs",
                    method,
                    retry_after,
                )
                await self._sleep(retry_after)
                continue

            if status >= 500:
                await self._backoff_sleep(attempt, f"server error {status}")
                continue

            # 4xx (other than 429) are permanent: do not retry.
            logger.error(
                "Telegram API %s failed (%s): %s",
                method,
                status,
                body.get("description"),
            )
            return None

        logger.error("Telegram API %s gave up after retries", method)
        return None

    def _backoff_for(self, attempt: int) -> float:
        return self._backoff * (2**attempt)

    async def _backoff_sleep(self, attempt: int, reason: str) -> None:
        delay = self._backoff_for(attempt)
        logger.warning("Telegram retry (%s) in %.1fs", reason, delay)
        await self._sleep(delay)

    async def _post(
        self, method: str, payload: dict[str, Any]
    ) -> tuple[int, dict[str, Any]]:
        if self._http_post is not None:
            return await self._http_post(method, payload)

        import httpx

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base}/{method}", json=payload
            )
            try:
                body = response.json()
            except ValueError:
                body = {}
            return response.status_code, body
