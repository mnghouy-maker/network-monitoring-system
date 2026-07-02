"""Anthropic Claude provider.

The ``anthropic`` SDK is imported lazily so the dependency is only required
when the assistant is actually configured and used. Requests stream and are
resolved with ``get_final_message()`` to avoid request timeouts on long
answers, and use adaptive extended thinking for stronger diagnostics.
"""

from collections.abc import Sequence

from app.ai.protocols import AICompletion, ChatTurn
from app.services.exceptions import AIError


class AnthropicProvider:
    """Talk to Claude via the official Anthropic Python SDK."""

    def __init__(
        self,
        api_key: str | None,
        model: str,
        *,
        timeout_seconds: float = 60.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout = timeout_seconds
        self._client: object | None = None

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _get_client(self) -> object:
        if self._client is None:
            import anthropic

            self._client = anthropic.AsyncAnthropic(
                api_key=self._api_key, timeout=self._timeout
            )
        return self._client

    async def complete(
        self,
        *,
        system: str,
        messages: Sequence[ChatTurn],
        max_tokens: int,
    ) -> AICompletion:
        if not self.is_configured:
            raise AIError("The AI assistant is not configured")

        client = self._get_client()
        payload = [{"role": m.role, "content": m.content} for m in messages]

        try:
            async with client.messages.stream(  # type: ignore[attr-defined]
                model=self._model,
                max_tokens=max_tokens,
                system=system,
                messages=payload,
                thinking={"type": "adaptive"},
            ) as stream:
                message = await stream.get_final_message()
        except AIError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalize SDK/transport errors
            raise AIError(f"AI provider request failed: {exc}") from exc

        text = "".join(
            block.text
            for block in message.content
            if getattr(block, "type", None) == "text"
        ).strip()
        usage = getattr(message, "usage", None)
        return AICompletion(
            text=text,
            model=getattr(message, "model", self._model),
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
        )
