"""SNMP metric collector.

Polls standard MIBs (HOST-RESOURCES, UCD-SNMP, IF-MIB) for CPU, memory, uptime
and per-interface counters. ``puresnmp`` is imported lazily so importing this
module never requires the dependency; only an actual ``collect()`` call does.

Every SNMP operation is bounded by the configured timeout and retried up to
``retries`` times, so an unreachable or filtered host cannot hang a poll for the
length of puresnmp's own (much longer) internal defaults.

The collector is intentionally tolerant: a failure reading any single metric
leaves that field ``None`` instead of aborting the whole poll, so a device that
exposes only some MIBs still yields useful data.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.models.device import Device, SNMPVersion
from app.monitoring.exceptions import CollectorConfigurationError
from app.monitoring.types import InterfaceSample, MetricSample

logger = logging.getLogger(__name__)

T = TypeVar("T")

# --- OIDs --------------------------------------------------------------------
_OID_SYS_UPTIME = "1.3.6.1.2.1.1.3.0"  # sysUpTime (timeticks, 1/100 s)
_OID_HR_PROCESSOR_LOAD = "1.3.6.1.2.1.25.3.3.1.2"  # per-CPU load %
_OID_UCD_MEM_TOTAL = "1.3.6.1.4.1.2021.4.5.0"  # memTotalReal (KB)
_OID_UCD_MEM_AVAIL = "1.3.6.1.4.1.2021.4.6.0"  # memAvailReal (KB)
_OID_IF_DESCR = "1.3.6.1.2.1.2.2.1.2"
_OID_IF_OPER_STATUS = "1.3.6.1.2.1.2.2.1.8"
_OID_IF_HIGH_SPEED = "1.3.6.1.2.1.31.1.1.1.15"  # Mbps
_OID_IF_HC_IN_OCTETS = "1.3.6.1.2.1.31.1.1.1.6"
_OID_IF_HC_OUT_OCTETS = "1.3.6.1.2.1.31.1.1.1.10"
_OID_IF_IN_ERRORS = "1.3.6.1.2.1.2.2.1.14"
_OID_IF_OUT_ERRORS = "1.3.6.1.2.1.2.2.1.20"

_IF_OPER_STATUS = {
    1: "up",
    2: "down",
    3: "testing",
    4: "unknown",
    5: "dormant",
    6: "notPresent",
    7: "lowerLayerDown",
}


class SnmpMetricCollector:
    """Collect device metrics over SNMP using ``puresnmp``.

    ``client_factory`` is an injection seam for tests: when provided it is used
    instead of constructing a real ``puresnmp`` client, so the mapping/retry
    logic can be exercised without a live SNMP agent or the dependency.
    """

    def __init__(
        self,
        timeout_seconds: float = 2.0,
        retries: int = 1,
        client_factory: Callable[[Device], object] | None = None,
    ) -> None:
        self._timeout = timeout_seconds
        self._retries = max(0, retries)
        self._client_factory = client_factory

    def _client(self, device: Device):  # noqa: ANN202 - lazy third-party type
        # Honour the configured SNMP version. v3 needs user/auth/priv
        # credentials that the inventory does not model yet, so reject it
        # explicitly rather than silently polling as v2c.
        if device.snmp_version is SNMPVersion.V3:
            raise CollectorConfigurationError(
                "SNMPv3 polling is not supported yet (no v3 credentials "
                "configured for this device)"
            )

        if self._client_factory is not None:
            return self._client_factory(device)

        from puresnmp import V1, V2C, Client, PyWrapper

        credentials = (
            V1(device.snmp_community)
            if device.snmp_version is SNMPVersion.V1
            else V2C(device.snmp_community)
        )
        return PyWrapper(
            Client(device.hostname, credentials, port=device.snmp_port)
        )

    async def collect(self, device: Device) -> MetricSample:
        client = self._client(device)
        return MetricSample(
            cpu_load_percent=await self._cpu(client),
            memory_used_percent=await self._memory(client),
            uptime_seconds=await self._uptime(client),
            interfaces=await self._interfaces(client),
        )

    # --- metric readers ---------------------------------------------------
    async def _cpu(self, client) -> float | None:  # noqa: ANN001
        rows = await self._safe_walk(client, _OID_HR_PROCESSOR_LOAD)
        loads = [self._opt_int(v) for v in rows.values()]
        loads = [v for v in loads if v is not None]
        if not loads:
            return None
        return round(sum(loads) / len(loads), 2)

    async def _memory(self, client) -> float | None:  # noqa: ANN001
        try:
            total = self._opt_int(
                await self._run(lambda: client.get(_OID_UCD_MEM_TOTAL))
            )
            avail = self._opt_int(
                await self._run(lambda: client.get(_OID_UCD_MEM_AVAIL))
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("SNMP memory read failed: %s", exc)
            return None
        if not total or total <= 0 or avail is None:
            return None
        return round((total - avail) / total * 100, 2)

    async def _uptime(self, client) -> int | None:  # noqa: ANN001
        try:
            ticks = self._opt_int(
                await self._run(lambda: client.get(_OID_SYS_UPTIME))
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("SNMP uptime read failed: %s", exc)
            return None
        return ticks // 100 if ticks is not None else None

    async def _interfaces(self, client) -> list[InterfaceSample]:  # noqa: ANN001
        descrs = await self._safe_walk(client, _OID_IF_DESCR)
        if not descrs:
            return []

        statuses = await self._safe_walk(client, _OID_IF_OPER_STATUS)
        speeds = await self._safe_walk(client, _OID_IF_HIGH_SPEED)
        in_oct = await self._safe_walk(client, _OID_IF_HC_IN_OCTETS)
        out_oct = await self._safe_walk(client, _OID_IF_HC_OUT_OCTETS)
        in_err = await self._safe_walk(client, _OID_IF_IN_ERRORS)
        out_err = await self._safe_walk(client, _OID_IF_OUT_ERRORS)

        samples: list[InterfaceSample] = []
        for idx, raw_name in descrs.items():
            status_code = self._opt_int(statuses.get(idx))
            speed_mbps = self._opt_int(speeds.get(idx))
            samples.append(
                InterfaceSample(
                    name=self._to_str(raw_name),
                    if_index=idx,
                    oper_status=_IF_OPER_STATUS.get(status_code)
                    if status_code is not None
                    else None,
                    speed_bps=speed_mbps * 1_000_000
                    if speed_mbps is not None
                    else None,
                    in_octets=self._opt_int(in_oct.get(idx)),
                    out_octets=self._opt_int(out_oct.get(idx)),
                    in_errors=self._opt_int(in_err.get(idx)),
                    out_errors=self._opt_int(out_err.get(idx)),
                )
            )
        return samples

    # --- low-level helpers ------------------------------------------------
    async def _run(self, op: Callable[[], Awaitable[T]]) -> T:
        """Run an SNMP awaitable bounded by the timeout, retrying on failure."""
        last_exc: Exception | None = None
        for _ in range(self._retries + 1):
            try:
                return await asyncio.wait_for(op(), self._timeout)
            except Exception as exc:  # noqa: BLE001 - retried; re-raised below
                last_exc = exc
        assert last_exc is not None
        raise last_exc

    async def _safe_walk(self, client, base_oid: str) -> dict[int, object]:  # noqa: ANN001
        """Walk a table column into ``{if_index: value}``; ``{}`` on failure."""

        async def _consume() -> dict[int, object]:
            return {
                index: value
                async for index, value in self._walk(client, base_oid)
            }

        try:
            return await self._run(_consume)
        except Exception as exc:  # noqa: BLE001
            logger.debug("SNMP walk %s failed: %s", base_oid, exc)
            return {}

    async def _walk(self, client, base_oid: str):  # noqa: ANN001, ANN202
        """Yield ``(if_index, value)`` pairs for a table column walk."""
        async for varbind in client.walk(base_oid):
            oid = str(varbind.oid)
            try:
                index = int(oid.rsplit(".", 1)[-1])
            except ValueError:
                continue
            yield index, varbind.value

    @staticmethod
    def _to_str(value: object) -> str:
        if isinstance(value, bytes):
            return value.decode(errors="ignore")
        return str(value)

    @staticmethod
    def _opt_int(value: object) -> int | None:
        if value is None:
            return None
        try:
            return int(value)  # type: ignore[arg-type]
        except (ValueError, TypeError):
            return None
