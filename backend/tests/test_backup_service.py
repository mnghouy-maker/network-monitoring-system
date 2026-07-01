"""Unit tests for the connection-profile and config-backup services."""

import pytest

from app.core.crypto import decrypt_secret
from app.models.backup import BackupStatus
from app.models.device import Device
from app.schemas.backup import ConnectionProfileUpsert
from app.services.backup import ConfigBackupService, ConnectionProfileService
from app.services.exceptions import BackupError, EntityNotFoundError
from tests.conftest import (
    FakeConfigBackend,
    FakeConfigBackupRepository,
    FakeConnectionProfileRepository,
    FakeDeviceRepository,
)


def _upsert(**over: object) -> ConnectionProfileUpsert:
    data: dict[str, object] = {
        "platform": "ios",
        "username": "netadmin",
        "password": "s3cret",
    }
    data.update(over)
    return ConnectionProfileUpsert(**data)  # type: ignore[arg-type]


async def _profile_service():
    devices = FakeDeviceRepository()
    profiles = FakeConnectionProfileRepository()
    device = await devices.add(Device(name="rtr", hostname="10.0.0.1"))
    return ConnectionProfileService(profiles, devices), devices, profiles, device


@pytest.mark.asyncio
async def test_upsert_encrypts_password() -> None:
    service, _devices, _profiles, device = await _profile_service()
    profile = await service.upsert(device.id, _upsert(password="topsecret"))
    assert profile.password_encrypted != "topsecret"
    assert decrypt_secret(profile.password_encrypted) == "topsecret"
    assert profile.has_enable_secret is False


@pytest.mark.asyncio
async def test_upsert_updates_existing() -> None:
    service, _devices, profiles, device = await _profile_service()
    await service.upsert(device.id, _upsert(username="a"))
    updated = await service.upsert(
        device.id, _upsert(username="b", enable_secret="en")
    )
    assert updated.username == "b"
    assert updated.has_enable_secret is True
    assert len(profiles._by_device) == 1  # replaced, not duplicated


@pytest.mark.asyncio
async def test_upsert_unknown_device_raises() -> None:
    service, _devices, _profiles, _device = await _profile_service()
    import uuid

    with pytest.raises(EntityNotFoundError):
        await service.upsert(uuid.uuid4(), _upsert())


async def _backup_service(backend: FakeConfigBackend):
    devices = FakeDeviceRepository()
    profiles = FakeConnectionProfileRepository()
    backups = FakeConfigBackupRepository()
    device = await devices.add(Device(name="rtr", hostname="10.0.0.1"))
    await ConnectionProfileService(profiles, devices).upsert(
        device.id, _upsert()
    )
    service = ConfigBackupService(
        backup_repo=backups,
        profile_repo=profiles,
        device_repo=devices,
        napalm_backend=backend,
        netmiko_backend=backend,
    )
    return service, device, backups


@pytest.mark.asyncio
async def test_backup_success_stores_content_and_hash() -> None:
    service, device, backups = await _backup_service(
        FakeConfigBackend(content="hostname r1")
    )
    backup, created = await service.backup_device(device)
    assert created is True
    assert backup.status is BackupStatus.SUCCESS
    assert backup.content == "hostname r1"
    assert backup.content_hash and backup.size_bytes == len(b"hostname r1")


@pytest.mark.asyncio
async def test_unchanged_config_is_deduplicated() -> None:
    service, device, backups = await _backup_service(
        FakeConfigBackend(content="same config")
    )
    first, created1 = await service.backup_device(device)
    second, created2 = await service.backup_device(device)
    assert created1 is True and created2 is False
    assert second.id == first.id
    assert len(backups._items) == 1


@pytest.mark.asyncio
async def test_changed_config_creates_new_version() -> None:
    backend = FakeConfigBackend(content="v1")
    service, device, backups = await _backup_service(backend)
    await service.backup_device(device)
    backend.content = "v2"
    _second, created = await service.backup_device(device)
    assert created is True
    assert len(backups._items) == 2


@pytest.mark.asyncio
async def test_failed_backup_is_recorded() -> None:
    service, device, backups = await _backup_service(
        FakeConfigBackend(error=RuntimeError("ssh timeout"))
    )
    backup, created = await service.backup_device(device)
    assert created is True
    assert backup.status is BackupStatus.FAILED
    assert "ssh timeout" in backup.error
    assert backup.content is None


@pytest.mark.asyncio
async def test_backup_without_profile_raises() -> None:
    devices = FakeDeviceRepository()
    profiles = FakeConnectionProfileRepository()
    device = await devices.add(Device(name="x", hostname="1.1.1.1"))
    service = ConfigBackupService(
        FakeConfigBackupRepository(),
        profiles,
        devices,
        FakeConfigBackend(),
        FakeConfigBackend(),
    )
    with pytest.raises(BackupError):
        await service.backup_device(device)


@pytest.mark.asyncio
async def test_diff_reports_changes() -> None:
    backend = FakeConfigBackend(content="line1\nline2")
    service, device, _backups = await _backup_service(backend)
    b1, _ = await service.backup_device(device)
    backend.content = "line1\nline2-changed"
    b2, _ = await service.backup_device(device)

    _f, _t, changed, diff = await service.diff(b1.id, b2.id)
    assert changed is True
    assert "line2-changed" in diff

    older, newer, changed2, _diff2 = await service.diff_latest(device.id)
    assert changed2 is True
    assert newer == b2.id and older == b1.id


@pytest.mark.asyncio
async def test_diff_latest_needs_two_backups() -> None:
    service, device, _backups = await _backup_service(FakeConfigBackend())
    await service.backup_device(device)
    with pytest.raises(BackupError):
        await service.diff_latest(device.id)
