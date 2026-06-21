"""Device repository: all database access for the inventory."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.device import Device, DeviceCategory


class DeviceRepository:
    """CRUD and queries for :class:`~app.models.device.Device`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, device_id: uuid.UUID) -> Device | None:
        return await self._session.get(Device, device_id)

    async def get_by_name(self, name: str) -> Device | None:
        result = await self._session.execute(
            select(Device).where(Device.name == name)
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
        category: DeviceCategory | None = None,
        is_active: bool | None = None,
    ) -> list[Device]:
        stmt = select(Device)
        if category is not None:
            stmt = stmt.where(Device.category == category)
        if is_active is not None:
            stmt = stmt.where(Device.is_active == is_active)
        stmt = stmt.offset(skip).limit(limit).order_by(Device.name)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_active(self) -> list[Device]:
        result = await self._session.execute(
            select(Device).where(Device.is_active.is_(True))
        )
        return list(result.scalars().all())

    async def count(self, *, category: DeviceCategory | None = None) -> int:
        stmt = select(func.count()).select_from(Device)
        if category is not None:
            stmt = stmt.where(Device.category == category)
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def add(self, device: Device) -> Device:
        self._session.add(device)
        await self._session.flush()
        await self._session.refresh(device)
        return device

    async def update(self, device: Device) -> Device:
        await self._session.flush()
        await self._session.refresh(device)
        return device

    async def delete(self, device: Device) -> None:
        await self._session.delete(device)
        await self._session.flush()
