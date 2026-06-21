"""ICMP ping collector backed by the system ``ping`` binary.

Using the OS ``ping`` avoids requiring raw-socket (root) privileges that a
pure-Python ICMP implementation would need. Output is parsed defensively so a
non-zero exit (host down) is reported as ``reachable=False`` rather than an
exception.
"""

import asyncio
import re

from app.monitoring.types import PingResult

# Matches "time=1.23 ms" in ping output.
_LATENCY_RE = re.compile(r"time[=<]([\d.]+)\s*ms")
# Matches "20% packet loss".
_LOSS_RE = re.compile(r"([\d.]+)%\s*packet loss")


class SubprocessPingCollector:
    """Run ``ping`` and parse reachability/latency from its output."""

    def __init__(self, count: int = 3, timeout_seconds: float = 2.0) -> None:
        self._count = count
        self._timeout = timeout_seconds

    async def ping(self, host: str) -> PingResult:
        # -c count, -w deadline (whole run), -W per-packet timeout (Linux).
        deadline = max(1, int(self._count * self._timeout))
        cmd = [
            "ping",
            "-c",
            str(self._count),
            "-w",
            str(deadline),
            "-W",
            str(int(self._timeout)),
            host,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(
                proc.communicate(), timeout=deadline + 2
            )
        except (TimeoutError, FileNotFoundError):
            return PingResult(reachable=False, packet_loss_percent=100.0)

        output = stdout.decode(errors="ignore")
        loss = self._parse_loss(output)
        latency = self._parse_avg_latency(output)
        reachable = proc.returncode == 0 and (loss is None or loss < 100.0)
        return PingResult(
            reachable=reachable,
            latency_ms=latency if reachable else None,
            packet_loss_percent=loss,
        )

    @staticmethod
    def _parse_loss(output: str) -> float | None:
        match = _LOSS_RE.search(output)
        return float(match.group(1)) if match else None

    @staticmethod
    def _parse_avg_latency(output: str) -> float | None:
        latencies = [float(m) for m in _LATENCY_RE.findall(output)]
        if not latencies:
            return None
        return round(sum(latencies) / len(latencies), 3)
