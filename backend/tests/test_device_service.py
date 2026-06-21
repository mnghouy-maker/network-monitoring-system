"""Unit tests for the device inventory service."""

import uuid

import pytest

from app.models.device import DeviceCategory, SNMPVersion
from app.schemas.device import DeviceCreate, DeviceUpdate
from app.services.device import DeviceService
from app.services.exceptions import (
    EntityAlreadyExistsError,
    EntityNotFoundError,
)
from tests.conftest import FakeDeviceRepository


def _payload(**overrides: object) -> DeviceCreate:
    data: dict[str, object] = {
        "name": "core-sw-1",
        "hostname": "10.0.0.1",
        "category": DeviceCategory.SWITCH,
        "vendor": "Cisco",
        "location": "DC-A / Rack 3",
    }
    data.update(overrides)
    return DeviceCreate(**data)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_create_device_persists_fields(
    fake_device_repo: FakeDeviceRepository,
) -> None:
    service = DeviceService(fake_device_repo)  # type: ignore[arg-type]
    device = await service.create(_payload())
    assert device.name == "core-sw-1"
    assert device.category is DeviceCategory.SWITCH
    assert device.vendor == "Cisco"
    assert device.location == "DC-A / Rack 3"
    assert device.snmp_version is SNMPVersion.V2C  # schema default


@pytest.mark.asyncio
async def test_create_duplicate_name_raises(
    fake_device_repo: FakeDeviceRepository,
) -> None:
    service = DeviceService(fake_device_repo)  # type: ignore[arg-type]
    await service.create(_payload())
    with pytest.raises(EntityAlreadyExistsError):
        await service.create(_payload(hostname="10.0.0.2"))


@pytest.mark.asyncio
async def test_get_missing_raises(
    fake_device_repo: FakeDeviceRepository,
) -> None:
    service = DeviceService(fake_device_repo)  # type: ignore[arg-type]
    with pytest.raises(EntityNotFoundError):
        await service.get(uuid.uuid4())


@pytest.mark.asyncio
async def test_update_changes_fields(
    fake_device_repo: FakeDeviceRepository,
) -> None:
    service = DeviceService(fake_device_repo)  # type: ignore[arg-type]
    device = await service.create(_payload())
    updated = await service.update(
        device.id,
        DeviceUpdate(location="DC-B / Rack 1", category=DeviceCategory.ROUTER),
    )
    assert updated.location == "DC-B / Rack 1"
    assert updated.category is DeviceCategory.ROUTER


@pytest.mark.asyncio
async def test_update_name_conflict_raises(
    fake_device_repo: FakeDeviceRepository,
) -> None:
    service = DeviceService(fake_device_repo)  # type: ignore[arg-type]
    await service.create(_payload(name="sw-a", hostname="10.0.0.1"))
    other = await service.create(_payload(name="sw-b", hostname="10.0.0.2"))
    with pytest.raises(EntityAlreadyExistsError):
        await service.update(other.id, DeviceUpdate(name="sw-a"))


@pytest.mark.asyncio
async def test_delete_removes_device(
    fake_device_repo: FakeDeviceRepository,
) -> None:
    service = DeviceService(fake_device_repo)  # type: ignore[arg-type]
    device = await service.create(_payload())
    await service.delete(device.id)
    with pytest.raises(EntityNotFoundError):
        await service.get(device.id)


@pytest.mark.asyncio
async def test_list_filters_by_category(
    fake_device_repo: FakeDeviceRepository,
) -> None:
    service = DeviceService(fake_device_repo)  # type: ignore[arg-type]
    await service.create(_payload(name="r1", category=DeviceCategory.ROUTER))
    await service.create(_payload(name="s1", category=DeviceCategory.SWITCH))
    routers = await service.list(category=DeviceCategory.ROUTER)
    assert [d.name for d in routers] == ["r1"]
