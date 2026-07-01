"""Telegram infrastructure: Bot API client, rate limiting, and formatting.

The client lives here (infrastructure) so the service layer depends only on the
:class:`~app.telegram.protocols.TelegramSender` protocol and can be tested with
a fake.
"""

from app.telegram.protocols import TelegramSender
from app.telegram.rate_limit import RateLimiter

__all__ = ["TelegramSender", "RateLimiter"]
