"""Unit tests for the Telegram rate limiter (deterministic via a fake clock)."""

import pytest

from app.telegram.rate_limit import RateLimiter


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.t = start
        self.slept: list[float] = []

    def now(self) -> float:
        return self.t

    async def sleep(self, delay: float) -> None:
        self.slept.append(delay)
        self.t += delay


@pytest.mark.asyncio
async def test_first_send_does_not_wait() -> None:
    clock = FakeClock()
    rl = RateLimiter(100.0, 1.0, clock=clock.now, sleep=clock.sleep)
    assert await rl.acquire(1) == 0.0
    assert clock.slept == []


@pytest.mark.asyncio
async def test_per_chat_interval_enforced() -> None:
    clock = FakeClock()
    rl = RateLimiter(1000.0, 1.0, clock=clock.now, sleep=clock.sleep)
    await rl.acquire(1)
    waited = await rl.acquire(1)  # same chat, immediately
    assert waited == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_global_interval_applies_across_chats() -> None:
    clock = FakeClock()
    # 2 msg/sec global => 0.5s minimum spacing between any two sends.
    rl = RateLimiter(2.0, 0.0, clock=clock.now, sleep=clock.sleep)
    await rl.acquire(1)
    waited = await rl.acquire(2)  # different chat, global limit still applies
    assert waited == pytest.approx(0.5)
