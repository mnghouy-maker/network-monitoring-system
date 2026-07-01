"""Connection parameters and the config-backend protocol."""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.models.backup import ConfigType


@dataclass(slots=True)
class ConnectionParams:
    """Resolved (decrypted) SSH connection parameters for one device."""

    host: str
    port: int
    platform: str
    username: str
    password: str
    enable_secret: str | None = None
    timeout: float = 30.0


@runtime_checkable
class ConfigBackend(Protocol):
    """Retrieves a device's configuration text over SSH."""

    async def fetch_config(
        self, params: ConnectionParams, config_type: ConfigType
    ) -> str: ...
