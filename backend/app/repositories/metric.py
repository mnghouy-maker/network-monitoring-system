"""Metric repository: persistence and retrieval of monitoring snapshots."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.metric import DeviceMetric


class MetricRepository:
    """Stores and queries :class:`~app.models.metric.DeviceMetric` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, metric: DeviceMetric) -> DeviceMetric:
        self._session.add(metric)
        await self._session.flush()
        # Refresh only the server-defaulted column. A full refresh would expire
        # the in-memory ``interfaces`` collection and turn it into a lazy load,
        # which fails under the async engine when later serialized.
        await self._session.refresh(metric, attribute_names=["collected_at"])
        return metric

    async def get_latest(self, device_id: uuid.UUID) -> DeviceMetric | None:
        result = await self._session.execute(
            select(DeviceMetric)
            .where(DeviceMetric.device_id == device_id)
            .order_by(DeviceMetric.collected_at.desc())
            .options(selectinload(DeviceMetric.interfaces))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_history(
        self, device_id: uuid.UUID, *, skip: int = 0, limit: int = 100
    ) -> list[DeviceMetric]:
        result = await self._session.execute(
            select(DeviceMetric)
            .where(DeviceMetric.device_id == device_id)
            .order_by(DeviceMetric.collected_at.desc())
            .options(selectinload(DeviceMetric.interfaces))
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())
