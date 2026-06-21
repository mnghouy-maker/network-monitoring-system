"""SNMP metric collector.

Polls standard MIBs (HOST-RESOURCES, UCD-SNMP, IF-MIB) for CPU, memory, uptime
and per-interface counters. ``puresnmp`` is imported lazily so importing this
module never requires the dependency; only an actual ``collect()`` call does.

The collector is intentionally tolerant: a failure reading any single metric
leaves that field ``None`` instead of aborting the whole poll, so a device that
exposes only some MIBs still yields useful data.
"""

import logging

from app.models.device import Device
from app.monitoring.types import InterfaceSample, MetricSample

logger = logging.getLogger(__name__)

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
    """Collect device metrics over SNMP using ``puresnmp``."""

    def __init__(self, timeout_seconds: float = 2.0, retries: int = 1) -> None:
        self._timeout = timeout_seconds
        self._retries = retries

    def _client(self, device: Device):  # noqa: ANN202 - lazy third-party type
        from puresnmp import V2C, Client, PyWrapper

        return PyWrapper(
            Client(
                device.hostname,
                V2C(device.snmp_community),
                port=device.snmp_port,
            )
        )

    async def collect(self, device: Device) -> MetricSample:
        client = self._client(device)
        return MetricSample(
            cpu_load_percent=await self._cpu(client),
            memory_used_percent=await self._memory(client),
            uptime_seconds=await self._uptime(client),
            interfaces=await self._interfaces(client),
        )

    async def _cpu(self, client) -> float | None:  # noqa: ANN001
        try:
            loads = [
                int(v)
                async for _, v in self._walk(client, _OID_HR_PROCESSOR_LOAD)
            ]
        except Exception as exc:  # noqa: BLE001
            logger.debug("SNMP CPU read failed: %s", exc)
            return None
        if not loads:
            return None
        return round(sum(loads) / len(loads), 2)

    async def _memory(self, client) -> float | None:  # noqa: ANN001
        try:
            total = int(await client.get(_OID_UCD_MEM_TOTAL))
            avail = int(await client.get(_OID_UCD_MEM_AVAIL))
        except Exception as exc:  # noqa: BLE001
            logger.debug("SNMP memory read failed: %s", exc)
            return None
        if total <= 0:
            return None
        return round((total - avail) / total * 100, 2)

    async def _uptime(self, client) -> int | None:  # noqa: ANN001
        try:
            ticks = int(await client.get(_OID_SYS_UPTIME))
        except Exception as exc:  # noqa: BLE001
            logger.debug("SNMP uptime read failed: %s", exc)
            return None
        return ticks // 100  # timeticks are hundredths of a second

    async def _interfaces(self, client) -> list[InterfaceSample]:  # noqa: ANN001
        try:
            descrs = {
                idx: self._to_str(val)
                async for idx, val in self._walk(client, _OID_IF_DESCR)
            }
        except Exception as exc:  # noqa: BLE001
            logger.debug("SNMP interface table read failed: %s", exc)
            return []

        statuses = await self._walk_map(client, _OID_IF_OPER_STATUS)
        speeds = await self._walk_map(client, _OID_IF_HIGH_SPEED)
        in_oct = await self._walk_map(client, _OID_IF_HC_IN_OCTETS)
        out_oct = await self._walk_map(client, _OID_IF_HC_OUT_OCTETS)
        in_err = await self._walk_map(client, _OID_IF_IN_ERRORS)
        out_err = await self._walk_map(client, _OID_IF_OUT_ERRORS)

        samples: list[InterfaceSample] = []
        for idx, name in descrs.items():
            status_code = statuses.get(idx)
            speed_mbps = speeds.get(idx)
            samples.append(
                InterfaceSample(
                    name=name,
                    if_index=idx,
                    oper_status=_IF_OPER_STATUS.get(
                        int(status_code) if status_code is not None else -1
                    ),
                    speed_bps=int(speed_mbps) * 1_000_000
                    if speed_mbps is not None
                    else None,
                    in_octets=self._opt_int(in_oct.get(idx)),
                    out_octets=self._opt_int(out_oct.get(idx)),
                    in_errors=self._opt_int(in_err.get(idx)),
                    out_errors=self._opt_int(out_err.get(idx)),
                )
            )
        return samples

    # --- low-level walk helpers ------------------------------------------
    async def _walk(self, client, base_oid: str):  # noqa: ANN001, ANN202
        """Yield ``(if_index, value)`` pairs for a table column walk."""
        async for varbind in client.walk(base_oid):
            oid = str(varbind.oid)
            try:
                index = int(oid.rsplit(".", 1)[-1])
            except ValueError:
                continue
            yield index, varbind.value

    async def _walk_map(self, client, base_oid: str) -> dict[int, object]:  # noqa: ANN001
        try:
            return {idx: val async for idx, val in self._walk(client, base_oid)}
        except Exception as exc:  # noqa: BLE001
            logger.debug("SNMP walk %s failed: %s", base_oid, exc)
            return {}

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
