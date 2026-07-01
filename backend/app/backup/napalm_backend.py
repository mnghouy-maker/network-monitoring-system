"""NAPALM-based configuration backend.

``napalm`` is imported lazily and its blocking session runs in a worker thread
so the event loop is never blocked. ``platform`` is a NAPALM driver name such as
``ios``, ``eos``, ``junos``, ``nxos`` or ``iosxr``.
"""

import asyncio

from app.backup.protocols import ConnectionParams
from app.models.backup import ConfigType


class NapalmConfigBackend:
    """Fetch running/startup configuration via NAPALM."""

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
        import napalm

        driver = napalm.get_network_driver(params.platform)
        optional_args = {"port": params.port}
        if params.enable_secret:
            optional_args["secret"] = params.enable_secret

        device = driver(
            hostname=params.host,
            username=params.username,
            password=params.password,
            timeout=int(params.timeout),
            optional_args=optional_args,
        )
        device.open()
        try:
            configs = device.get_config(retrieve=config_type.value)
            return configs.get(config_type.value, "") or ""
        finally:
            device.close()
