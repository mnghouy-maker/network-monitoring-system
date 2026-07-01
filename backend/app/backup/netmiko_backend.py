"""Netmiko-based configuration backend (built on Paramiko).

``netmiko`` is imported lazily and its blocking session runs in a worker thread.
``platform`` is a Netmiko ``device_type`` such as ``cisco_ios``, ``arista_eos``
or ``juniper_junos``.
"""

import asyncio

from app.backup.protocols import ConnectionParams
from app.models.backup import ConfigType

_SHOW_COMMANDS = {
    ConfigType.RUNNING: "show running-config",
    ConfigType.STARTUP: "show startup-config",
}


class NetmikoConfigBackend:
    """Fetch running/startup configuration via Netmiko."""

    async def fetch_config(
        self, params: ConnectionParams, config_type: ConfigType
    ) -> str:
        return await asyncio.wait_for(
            asyncio.to_thread(self._sync_fetch, params, config_type),
            timeout=params.timeout,
        )

    @staticmethod
    def _sync_fetch(
        params: ConnectionParams, config_type: ConfigType
    ) -> str:
        from netmiko import ConnectHandler

        connection = ConnectHandler(
            device_type=params.platform,
            host=params.host,
            port=params.port,
            username=params.username,
            password=params.password,
            secret=params.enable_secret or "",
            timeout=int(params.timeout),
        )
        try:
            if params.enable_secret:
                connection.enable()
            command = _SHOW_COMMANDS[config_type]
            return connection.send_command(command, read_timeout=params.timeout)
        finally:
            connection.disconnect()
