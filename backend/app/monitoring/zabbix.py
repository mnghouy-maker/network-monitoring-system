"""Zabbix metric collector.

Reads the latest item values for a device's mapped Zabbix host via the Zabbix
JSON-RPC API. ``httpx`` is imported lazily. Item-key matching is best-effort:
Zabbix templates differ between environments, so we match on common key
prefixes and fall back to ``None`` when a metric is not templated.
"""

import asyncio
import logging
from typing import Any

from app.models.device import Device
from app.monitoring.exceptions import (
    CollectorConfigurationError,
    CollectorError,
)
from app.monitoring.types import InterfaceSample, MetricSample

logger = logging.getLogger(__name__)


class ZabbixApiError(CollectorError):
    """Raised when the Zabbix API returns an error response."""


class ZabbixNotConfiguredError(CollectorConfigurationError):
    """Raised when a Zabbix poll is attempted without required configuration.

    This is a caller/configuration error (e.g. the device has no
    ``zabbix_host_id``) and surfaces to the API as a 400, not a silent degrade.
    """


class ZabbixMetricCollector:
    """Collect device metrics from the Zabbix API.

    Authentication uses ``user.login`` to obtain a session token, which is
    cached for the lifetime of the collector instance.
    """

    def __init__(
        self,
        url: str | None,
        user: str | None,
        password: str | None,
        *,
        verify_tls: bool = True,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._url = url.rstrip("/") + "/api_jsonrpc.php" if url else None
        self._user = user
        self._password = password
        self._verify = verify_tls
        self._timeout = timeout_seconds
        self._auth_token: str | None = None
        self._request_id = 0
        # Guards token (re)authentication: the collector is a process-wide
        # singleton, so concurrent polls must not race on login.
        self._auth_lock = asyncio.Lock()

    @property
    def is_configured(self) -> bool:
        return bool(self._url and self._user and self._password)

    async def collect(self, device: Device) -> MetricSample:
        if not self.is_configured:
            raise ZabbixNotConfiguredError("Zabbix API is not configured")
        if not device.zabbix_host_id:
            raise ZabbixNotConfiguredError(
                f"Device {device.name!r} has no zabbix_host_id"
            )

        items = await self._get_items(device.zabbix_host_id)
        return self._map_items(items)

    # --- JSON-RPC plumbing ------------------------------------------------
    async def _call(self, method: str, params: Any, *, auth: bool) -> Any:
        import httpx

        self._request_id += 1
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": self._request_id,
        }
        # Zabbix <6.4 expects "auth"; newer accepts a Bearer header too. The
        # "auth" field is widely compatible, so we use it for login-based auth.
        if auth and self._auth_token:
            payload["auth"] = self._auth_token

        async with httpx.AsyncClient(
            verify=self._verify, timeout=self._timeout
        ) as client:
            response = await client.post(
                self._url,  # type: ignore[arg-type]
                json=payload,
                headers={"Content-Type": "application/json-rpc"},
            )
            response.raise_for_status()
            body = response.json()

        if "error" in body:
            raise ZabbixApiError(str(body["error"]))
        return body["result"]

    async def _ensure_auth(self, *, force: bool = False) -> None:
        """Acquire a session token, re-using a cached one unless ``force``."""
        async with self._auth_lock:
            if self._auth_token and not force:
                return
            self._auth_token = await self._call(
                "user.login",
                {"username": self._user, "password": self._password},
                auth=False,
            )

    async def _get_items(self, host_id: str) -> list[dict[str, Any]]:
        params = {
            "output": ["key_", "lastvalue", "name"],
            "hostids": [host_id],
        }
        await self._ensure_auth()
        try:
            return await self._call("item.get", params, auth=True)
        except ZabbixApiError:
            # The cached token may have expired; re-authenticate once and retry.
            await self._ensure_auth(force=True)
            return await self._call("item.get", params, auth=True)

    # --- mapping ----------------------------------------------------------
    def _map_items(self, items: list[dict[str, Any]]) -> MetricSample:
        cpu = mem = uptime = None
        interfaces_in: dict[str, int] = {}
        interfaces_out: dict[str, int] = {}

        for item in items:
            key = item.get("key_", "")
            raw = item.get("lastvalue")
            value = self._to_float(raw)
            if value is None:
                continue

            if key.startswith("system.cpu.util") and cpu is None:
                cpu = round(value, 2)
            elif "vm.memory.util" in key and mem is None:
                mem = round(value, 2)
            elif key.startswith("system.uptime") and uptime is None:
                uptime = int(value)
            elif key.startswith("net.if.in"):
                interfaces_in[self._iface_name(key)] = int(value)
            elif key.startswith("net.if.out"):
                interfaces_out[self._iface_name(key)] = int(value)

        interfaces = [
            InterfaceSample(
                name=name,
                in_octets=interfaces_in.get(name),
                out_octets=interfaces_out.get(name),
            )
            for name in sorted(set(interfaces_in) | set(interfaces_out))
        ]
        return MetricSample(
            cpu_load_percent=cpu,
            memory_used_percent=mem,
            uptime_seconds=uptime,
            interfaces=interfaces,
        )

    @staticmethod
    def _iface_name(key: str) -> str:
        # net.if.in[eth0] -> eth0
        if "[" in key and key.endswith("]"):
            return key[key.index("[") + 1 : -1].split(",")[0]
        return key

    @staticmethod
    def _to_float(raw: Any) -> float | None:
        if raw is None or raw == "":
            return None
        try:
            return float(raw)
        except (ValueError, TypeError):
            return None
