"""LLM provider protocol and transport DTOs.

The service layer depends only on :class:`AIProvider`, so the concrete
Anthropic client (and any future provider) stays behind this seam and can be
swapped for a fake in tests without network access.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(slots=True)
class ChatTurn:
    """One conversational turn handed to the provider."""

    role: str  # "user" | "assistant"
    content: str


@dataclass(slots=True)
class AICompletion:
    """A provider's reply plus token accounting."""

    text: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None


@runtime_checkable
class AIProvider(Protocol):
    """A large language model backend."""

    @property
    def is_configured(self) -> bool:
        """Whether the provider has the credentials it needs to answer."""
        ...

    async def complete(
        self,
        *,
        system: str,
        messages: Sequence[ChatTurn],
        max_tokens: int,
    ) -> AICompletion: ...
