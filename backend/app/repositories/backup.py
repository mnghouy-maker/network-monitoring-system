"""Repositories for device connection profiles and configuration backups."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.backup import (
    BackupStatus,
    ConfigBackup,
    ConfigType,
    DeviceConnectionProfile,
)


class ConnectionProfileRepository:
    """CRUD for :class:`~app.models.backup.DeviceConnectionProfile`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_device(
        self, device_id: uuid.UUID
    ) -> DeviceConnectionProfile | None:
        result = await self._session.execute(
            select(DeviceConnectionProfile).where(
                DeviceConnectionProfile.device_id == device_id
            )
        )
        return result.scalar_one_or_none()

    async def list_active(self) -> list[DeviceConnectionProfile]:
        result = await self._session.execute(
            select(DeviceConnectionProfile).where(
                DeviceConnectionProfile.is_active.is_(True)
            )
        )
        return list(result.scalars().all())

    async def add(
        self, profile: DeviceConnectionProfile
    ) -> DeviceConnectionProfile:
        self._session.add(profile)
        await self._session.flush()
        await self._session.refresh(profile)
        return profile

    async def update(
        self, profile: DeviceConnectionProfile
    ) -> DeviceConnectionProfile:
        await self._session.flush()
        await self._session.refresh(profile)
        return profile

    async def delete(self, profile: DeviceConnectionProfile) -> None:
        await self._session.delete(profile)
        await self._session.flush()


class ConfigBackupRepository:
    """Persistence and queries for :class:`~app.models.backup.ConfigBackup`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, backup_id: uuid.UUID) -> ConfigBackup | None:
        return await self._session.get(ConfigBackup, backup_id)

    async def get_latest_success(
        self, device_id: uuid.UUID, config_type: ConfigType
    ) -> ConfigBackup | None:
        result = await self._session.execute(
            select(ConfigBackup)
            .where(
                ConfigBackup.device_id == device_id,
                ConfigBackup.config_type == config_type,
                ConfigBackup.status == BackupStatus.SUCCESS,
            )
            .order_by(ConfigBackup.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_for_device(
        self,
        device_id: uuid.UUID,
        *,
        config_type: ConfigType | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[ConfigBackup]:
        stmt = select(ConfigBackup).where(ConfigBackup.device_id == device_id)
        if config_type is not None:
            stmt = stmt.where(ConfigBackup.config_type == config_type)
        stmt = (
            stmt.order_by(ConfigBackup.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def add(self, backup: ConfigBackup) -> ConfigBackup:
        self._session.add(backup)
        await self._session.flush()
        await self._session.refresh(backup, attribute_names=["created_at"])
        return backup
