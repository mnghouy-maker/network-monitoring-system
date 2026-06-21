"""Device service: business rules for the inventory."""

import uuid

from app.models.device import Device, DeviceCategory
from app.repositories.device import DeviceRepository
from app.schemas.device import DeviceCreate, DeviceUpdate
from app.services.exceptions import (
    EntityAlreadyExistsError,
    EntityNotFoundError,
)


class DeviceService:
    """Encapsulates device lifecycle operations."""

    def __init__(self, repository: DeviceRepository) -> None:
        self._repo = repository

    async def get(self, device_id: uuid.UUID) -> Device:
        device = await self._repo.get(device_id)
        if device is None:
            raise EntityNotFoundError(f"Device {device_id} not found")
        return device

    async def list(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
        category: DeviceCategory | None = None,
        is_active: bool | None = None,
    ) -> list[Device]:
        return await self._repo.list(
            skip=skip, limit=limit, category=category, is_active=is_active
        )

    async def create(self, payload: DeviceCreate) -> Device:
        if await self._repo.get_by_name(payload.name):
            raise EntityAlreadyExistsError(
                f"A device named {payload.name!r} already exists"
            )
        device = Device(**payload.model_dump())
        return await self._repo.add(device)

    async def update(
        self, device_id: uuid.UUID, payload: DeviceUpdate
    ) -> Device:
        device = await self.get(device_id)
        data = payload.model_dump(exclude_unset=True)

        new_name = data.get("name")
        if new_name and new_name != device.name:
            if await self._repo.get_by_name(new_name):
                raise EntityAlreadyExistsError(
                    f"A device named {new_name!r} already exists"
                )

        for field, value in data.items():
            setattr(device, field, value)
        return await self._repo.update(device)

    async def delete(self, device_id: uuid.UUID) -> None:
        device = await self.get(device_id)
        await self._repo.delete(device)
