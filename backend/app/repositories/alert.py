"""Repositories for alert rules, history, and acknowledgements."""

from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import (
    AlertAcknowledgement,
    AlertHistory,
    AlertRule,
    AlertSeverity,
    AlertStatus,
    AlertType,
)

_ACTIVE_STATUSES = (AlertStatus.FIRING, AlertStatus.ACKNOWLEDGED)


class AlertRuleRepository:
    """CRUD for :class:`~app.models.alert.AlertRule`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, rule_id: uuid.UUID) -> AlertRule | None:
        return await self._session.get(AlertRule, rule_id)

    async def list(self, *, skip: int = 0, limit: int = 100) -> list[AlertRule]:
        result = await self._session.execute(
            select(AlertRule).order_by(AlertRule.name).offset(skip).limit(limit)
        )
        return list(result.scalars().all())

    async def list_enabled_for_device(
        self, device_id: uuid.UUID
    ) -> list[AlertRule]:
        """Enabled rules scoped to this device or to all devices (NULL)."""
        result = await self._session.execute(
            select(AlertRule).where(
                AlertRule.is_enabled.is_(True),
                or_(
                    AlertRule.device_id == device_id,
                    AlertRule.device_id.is_(None),
                ),
            )
        )
        return list(result.scalars().all())

    async def add(self, rule: AlertRule) -> AlertRule:
        self._session.add(rule)
        await self._session.flush()
        await self._session.refresh(rule)
        return rule

    async def update(self, rule: AlertRule) -> AlertRule:
        await self._session.flush()
        await self._session.refresh(rule)
        return rule

    async def delete(self, rule: AlertRule) -> None:
        await self._session.delete(rule)
        await self._session.flush()


class AlertHistoryRepository:
    """Persistence and queries for :class:`~app.models.alert.AlertHistory`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, alert_id: uuid.UUID) -> AlertHistory | None:
        return await self._session.get(AlertHistory, alert_id)

    async def get_active(
        self, device_id: uuid.UUID, alert_type: AlertType
    ) -> AlertHistory | None:
        """Return the open (firing/acknowledged) alert for a device+type."""
        result = await self._session.execute(
            select(AlertHistory)
            .where(
                AlertHistory.device_id == device_id,
                AlertHistory.alert_type == alert_type,
                AlertHistory.status.in_(_ACTIVE_STATUSES),
            )
            .order_by(AlertHistory.triggered_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_active(
        self, *, severity: AlertSeverity | None = None, limit: int = 100
    ) -> list[AlertHistory]:
        stmt = select(AlertHistory).where(
            AlertHistory.status.in_(_ACTIVE_STATUSES)
        )
        if severity is not None:
            stmt = stmt.where(AlertHistory.severity == severity)
        stmt = stmt.order_by(AlertHistory.triggered_at.desc()).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_history(
        self,
        *,
        device_id: uuid.UUID | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[AlertHistory]:
        stmt = select(AlertHistory)
        if device_id is not None:
            stmt = stmt.where(AlertHistory.device_id == device_id)
        stmt = (
            stmt.order_by(AlertHistory.triggered_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def add(self, alert: AlertHistory) -> AlertHistory:
        self._session.add(alert)
        await self._session.flush()
        await self._session.refresh(alert, attribute_names=["triggered_at"])
        return alert

    async def update(self, alert: AlertHistory) -> AlertHistory:
        await self._session.flush()
        return alert


class AlertAcknowledgementRepository:
    """Persistence for :class:`~app.models.alert.AlertAcknowledgement`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self, ack: AlertAcknowledgement
    ) -> AlertAcknowledgement:
        self._session.add(ack)
        await self._session.flush()
        await self._session.refresh(ack, attribute_names=["acknowledged_at"])
        return ack
