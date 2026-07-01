"""Configuration backup services: connection profiles and backup lifecycle."""

import difflib
import hashlib
import logging
import uuid

from app.backup.protocols import ConfigBackend, ConnectionParams
from app.core.crypto import decrypt_secret, encrypt_secret
from app.models.backup import (
    BackupStatus,
    ConfigBackup,
    ConfigType,
    ConnectionMethod,
    DeviceConnectionProfile,
)
from app.models.device import Device
from app.repositories.backup import (
    ConfigBackupRepository,
    ConnectionProfileRepository,
)
from app.repositories.device import DeviceRepository
from app.schemas.backup import ConnectionProfileUpsert
from app.services.exceptions import BackupError, EntityNotFoundError

logger = logging.getLogger(__name__)


class ConnectionProfileService:
    """Manages per-device SSH connection profiles (with encrypted secrets)."""

    def __init__(
        self,
        profile_repo: ConnectionProfileRepository,
        device_repo: DeviceRepository,
    ) -> None:
        self._profiles = profile_repo
        self._devices = device_repo

    async def get(self, device_id: uuid.UUID) -> DeviceConnectionProfile:
        profile = await self._profiles.get_by_device(device_id)
        if profile is None:
            raise EntityNotFoundError(
                f"Device {device_id} has no connection profile"
            )
        return profile

    async def upsert(
        self, device_id: uuid.UUID, payload: ConnectionProfileUpsert
    ) -> DeviceConnectionProfile:
        if await self._devices.get(device_id) is None:
            raise EntityNotFoundError(f"Device {device_id} not found")

        profile = await self._profiles.get_by_device(device_id)
        encrypted_password = encrypt_secret(payload.password)
        encrypted_enable = (
            encrypt_secret(payload.enable_secret)
            if payload.enable_secret
            else None
        )

        if profile is None:
            profile = DeviceConnectionProfile(
                device_id=device_id,
                method=payload.method,
                platform=payload.platform,
                ssh_port=payload.ssh_port,
                username=payload.username,
                password_encrypted=encrypted_password,
                enable_secret_encrypted=encrypted_enable,
                is_active=payload.is_active,
            )
            return await self._profiles.add(profile)

        profile.method = payload.method
        profile.platform = payload.platform
        profile.ssh_port = payload.ssh_port
        profile.username = payload.username
        profile.password_encrypted = encrypted_password
        profile.enable_secret_encrypted = encrypted_enable
        profile.is_active = payload.is_active
        return await self._profiles.update(profile)

    async def delete(self, device_id: uuid.UUID) -> None:
        await self._profiles.delete(await self.get(device_id))


class ConfigBackupService:
    """Retrieves, stores, versions and diffs device configurations."""

    def __init__(
        self,
        backup_repo: ConfigBackupRepository,
        profile_repo: ConnectionProfileRepository,
        device_repo: DeviceRepository,
        napalm_backend: ConfigBackend,
        netmiko_backend: ConfigBackend,
        ssh_timeout: float = 30.0,
    ) -> None:
        self._backups = backup_repo
        self._profiles = profile_repo
        self._devices = device_repo
        self._napalm = napalm_backend
        self._netmiko = netmiko_backend
        self._timeout = ssh_timeout

    def _backend_for(self, method: ConnectionMethod) -> ConfigBackend:
        return (
            self._netmiko
            if method is ConnectionMethod.NETMIKO
            else self._napalm
        )

    def _params(self, profile: DeviceConnectionProfile, host: str) -> ConnectionParams:
        return ConnectionParams(
            host=host,
            port=profile.ssh_port,
            platform=profile.platform,
            username=profile.username,
            password=decrypt_secret(profile.password_encrypted),
            enable_secret=(
                decrypt_secret(profile.enable_secret_encrypted)
                if profile.enable_secret_encrypted
                else None
            ),
            timeout=self._timeout,
        )

    async def backup_device(
        self,
        device: Device,
        config_type: ConfigType = ConfigType.RUNNING,
    ) -> tuple[ConfigBackup, bool]:
        """Fetch and store a config. Returns (backup, created).

        ``created`` is ``False`` when the config is unchanged since the last
        successful backup (deduplicated by content hash) — no new row is added.
        """
        profile = await self._profiles.get_by_device(device.id)
        if profile is None or not profile.is_active:
            raise BackupError(
                f"Device {device.name!r} has no active connection profile"
            )

        backend = self._backend_for(profile.method)
        try:
            content = await backend.fetch_config(
                self._params(profile, device.hostname), config_type
            )
        except Exception as exc:  # noqa: BLE001 - persist the failure
            logger.warning("Backup failed for %s: %s", device.name, exc)
            failed = ConfigBackup(
                device_id=device.id,
                config_type=config_type,
                method=profile.method,
                status=BackupStatus.FAILED,
                error=str(exc)[:2000],
            )
            return await self._backups.add(failed), True

        digest = hashlib.sha256(content.encode()).hexdigest()
        latest = await self._backups.get_latest_success(device.id, config_type)
        if latest is not None and latest.content_hash == digest:
            logger.info("Config unchanged for %s; skipping new backup", device.name)
            return latest, False

        backup = ConfigBackup(
            device_id=device.id,
            config_type=config_type,
            method=profile.method,
            status=BackupStatus.SUCCESS,
            content=content,
            content_hash=digest,
            size_bytes=len(content.encode()),
        )
        return await self._backups.add(backup), True

    async def backup_device_by_id(
        self, device_id: uuid.UUID, config_type: ConfigType = ConfigType.RUNNING
    ) -> tuple[ConfigBackup, bool]:
        device = await self._devices.get(device_id)
        if device is None:
            raise EntityNotFoundError(f"Device {device_id} not found")
        return await self.backup_device(device, config_type)

    async def backup_all(
        self, config_type: ConfigType = ConfigType.RUNNING
    ) -> list[ConfigBackup]:
        results: list[ConfigBackup] = []
        for profile in await self._profiles.list_active():
            device = await self._devices.get(profile.device_id)
            if device is None:
                continue
            try:
                backup, _created = await self.backup_device(device, config_type)
                results.append(backup)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Backup error for %s: %s", device.name, exc)
        return results

    async def get(self, backup_id: uuid.UUID) -> ConfigBackup:
        backup = await self._backups.get(backup_id)
        if backup is None:
            raise EntityNotFoundError(f"Backup {backup_id} not found")
        return backup

    async def list_for_device(
        self,
        device_id: uuid.UUID,
        *,
        config_type: ConfigType | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[ConfigBackup]:
        return await self._backups.list_for_device(
            device_id, config_type=config_type, skip=skip, limit=limit
        )

    async def diff(
        self, from_id: uuid.UUID, to_id: uuid.UUID
    ) -> tuple[uuid.UUID, uuid.UUID, bool, str]:
        source = await self.get(from_id)
        target = await self.get(to_id)
        diff_text = self._unified_diff(
            source.content or "", target.content or "", str(from_id), str(to_id)
        )
        return from_id, to_id, bool(diff_text), diff_text

    async def diff_latest(
        self, device_id: uuid.UUID, config_type: ConfigType = ConfigType.RUNNING
    ) -> tuple[uuid.UUID, uuid.UUID, bool, str]:
        backups = [
            b
            for b in await self._backups.list_for_device(
                device_id, config_type=config_type, limit=2
            )
            if b.status is BackupStatus.SUCCESS
        ]
        if len(backups) < 2:
            raise BackupError(
                "Need at least two successful backups to diff"
            )
        newer, older = backups[0], backups[1]
        diff_text = self._unified_diff(
            older.content or "", newer.content or "", str(older.id), str(newer.id)
        )
        return older.id, newer.id, bool(diff_text), diff_text

    @staticmethod
    def _unified_diff(
        old: str, new: str, from_label: str, to_label: str
    ) -> str:
        lines = difflib.unified_diff(
            old.splitlines(),
            new.splitlines(),
            fromfile=from_label,
            tofile=to_label,
            lineterm="",
        )
        return "\n".join(lines)
