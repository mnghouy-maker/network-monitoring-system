"""Unit tests for the Telegram client's retry/backoff logic (no network)."""

import pytest

from app.telegram.client import TelegramClient
from app.telegram.rate_limit import RateLimiter


class FakePost:
    """Returns queued responses; an Exception entry is raised when reached."""

    def __init__(self, responses: list) -> None:
        self._responses = list(responses)
        self.calls = 0

    async def __call__(self, method: str, payload: dict):
        self.calls += 1
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _client(post: FakePost) -> tuple[TelegramClient, list[float]]:
    slept: list[float] = []

    async def fake_sleep(delay: float) -> None:
        slept.append(delay)

    client = TelegramClient(
        "token",
        rate_limiter=RateLimiter(10_000.0, 0.0),
        max_retries=3,
        backoff_seconds=0.5,
        http_post=post,
        sleep=fake_sleep,
    )
    return client, slept


_OK = (200, {"ok": True, "result": {"message_id": 1}})


@pytest.mark.asyncio
async def test_send_success_single_call() -> None:
    post = FakePost([_OK])
    client, slept = _client(post)
    assert await client.send_message(1, "hi") is True
    assert post.calls == 1
    assert slept == []


@pytest.mark.asyncio
async def test_retries_on_429_then_succeeds() -> None:
    post = FakePost([(429, {"ok": False, "parameters": {"retry_after": 1.0}}), _OK])
    client, slept = _client(post)
    assert await client.send_message(1, "hi") is True
    assert post.calls == 2
    assert slept == [1.0]


@pytest.mark.asyncio
async def test_retries_on_500_then_succeeds() -> None:
    post = FakePost([(500, {"ok": False}), _OK])
    client, slept = _client(post)
    assert await client.send_message(1, "hi") is True
    assert post.calls == 2
    assert len(slept) == 1


@pytest.mark.asyncio
async def test_retries_on_network_error_then_succeeds() -> None:
    post = FakePost([ConnectionError("boom"), _OK])
    client, _slept = _client(post)
    assert await client.send_message(1, "hi") is True
    assert post.calls == 2


@pytest.mark.asyncio
async def test_permanent_4xx_is_not_retried() -> None:
    post = FakePost([(400, {"ok": False, "description": "bad request"})])
    client, slept = _client(post)
    assert await client.send_message(1, "hi") is False
    assert post.calls == 1
    assert slept == []


@pytest.mark.asyncio
async def test_gives_up_after_max_retries() -> None:
    post = FakePost([(500, {"ok": False})] * 4)  # max_retries=3 => 4 attempts
    client, _slept = _client(post)
    assert await client.send_message(1, "hi") is False
    assert post.calls == 4


@pytest.mark.asyncio
async def test_unconfigured_client_drops_message() -> None:
    client = TelegramClient(None)
    assert client.is_configured is False
    assert await client.send_message(1, "hi") is False
