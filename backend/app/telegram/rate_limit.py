"""Async rate limiter for outbound Telegram messages.

Telegram enforces roughly 30 messages/second globally and about 1 message/second
to an individual chat. This limiter paces sends to stay under both limits. The
clock and sleep functions are injectable so the behaviour is deterministically
testable without real time passing.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable


class RateLimiter:
    """Token-style limiter enforcing a global rate and a per-chat interval."""

    def __init__(
        self,
        rate_per_second: float,
        per_chat_interval: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._min_global_interval = (
            1.0 / rate_per_second if rate_per_second > 0 else 0.0
        )
        self._per_chat_interval = max(0.0, per_chat_interval)
        self._clock = clock
        self._sleep = sleep
        self._last_global = 0.0
        self._last_per_chat: dict[int, float] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, chat_id: int) -> float:
        """Block until a message to ``chat_id`` may be sent.

        Returns the number of seconds waited (useful for tests/metrics).
        """
        async with self._lock:
            now = self._clock()
            ready_at = max(
                self._last_global + self._min_global_interval,
                self._last_per_chat.get(chat_id, 0.0)
                + self._per_chat_interval,
            )
            waited = 0.0
            if ready_at > now:
                waited = ready_at - now
                await self._sleep(waited)
                now = ready_at
            self._last_global = now
            self._last_per_chat[chat_id] = now
            return waited
