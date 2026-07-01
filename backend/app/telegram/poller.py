"""Long-polling worker: an alternative to the webhook for receiving updates.

Run as a standalone process (``python -m app.telegram.poller``) for deployments
that cannot expose an HTTPS webhook. It reuses the exact same
``TelegramUpdateDispatcher`` as the webhook, building a fresh DB session
(unit of work) per update.
"""

import asyncio
import logging

from app.core.config import settings
from app.core.dependencies import _alert_default_thresholds, get_telegram_client
from app.db.session import AsyncSessionLocal
from app.repositories.alert import (
    AlertAcknowledgementRepository,
    AlertHistoryRepository,
    AlertRuleRepository,
)
from app.repositories.device import DeviceRepository
from app.repositories.metric import MetricRepository
from app.repositories.telegram import (
    TelegramChatRepository,
    TelegramUserRepository,
)
from app.services.alerting import AlertingService
from app.services.notifier import AlertNotifier
from app.services.telegram_bot import (
    TelegramCommandService,
    TelegramUpdateDispatcher,
)
from app.telegram.client import TelegramClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _build_dispatcher(session, client: TelegramClient) -> TelegramUpdateDispatcher:
    device_repo = DeviceRepository(session)
    metric_repo = MetricRepository(session)
    history_repo = AlertHistoryRepository(session)
    notifier = AlertNotifier(client, TelegramChatRepository(session))
    alerting = AlertingService(
        rule_repo=AlertRuleRepository(session),
        history_repo=history_repo,
        ack_repo=AlertAcknowledgementRepository(session),
        device_repo=device_repo,
        metric_repo=metric_repo,
        notifier=notifier,
        default_thresholds=_alert_default_thresholds(),
    )
    commands = TelegramCommandService(device_repo, metric_repo, history_repo)
    return TelegramUpdateDispatcher(
        sender=client,
        command_service=commands,
        alerting_service=alerting,
        telegram_user_repo=TelegramUserRepository(session),
    )


async def run_polling() -> None:
    client = get_telegram_client()
    if not client.is_configured:
        logger.error("TELEGRAM_BOT_TOKEN is not set; poller exiting")
        return

    logger.info("Telegram poller started")
    offset: int | None = None
    while True:
        try:
            updates = await client.get_updates(offset=offset, timeout=0)
        except Exception as exc:  # noqa: BLE001 - keep the loop alive
            logger.warning("get_updates failed: %s", exc)
            await asyncio.sleep(settings.TELEGRAM_POLL_INTERVAL_SECONDS)
            continue

        for update in updates:
            offset = int(update["update_id"]) + 1
            async with AsyncSessionLocal() as session:
                try:
                    dispatcher = _build_dispatcher(session, client)
                    await dispatcher.dispatch(update)
                    await session.commit()
                except Exception as exc:  # noqa: BLE001
                    await session.rollback()
                    logger.warning("Failed to handle update: %s", exc)

        if not updates:
            await asyncio.sleep(settings.TELEGRAM_POLL_INTERVAL_SECONDS)


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(run_polling())
