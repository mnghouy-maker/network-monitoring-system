"""Local health collector using psutil (monitors the host running the app)."""

import asyncio

from app.health.protocols import HealthSample, HealthTarget


class LocalHealthCollector:
    """Collect health of the local host via ``psutil``."""

    async def collect(self, target: HealthTarget) -> HealthSample:
        # psutil is blocking (cpu_percent samples over a short interval).
        return await asyncio.to_thread(self._sync_collect)

    @staticmethod
    def _sync_collect() -> HealthSample:
        import time

        import psutil

        load1 = load5 = load15 = None
        try:
            load1, load5, load15 = psutil.getloadavg()
        except (AttributeError, OSError):  # not available on all platforms
            pass

        uptime = None
        try:
            uptime = int(time.time() - psutil.boot_time())
        except Exception:  # noqa: BLE001
            pass

        return HealthSample(
            reachable=True,
            cpu_percent=round(psutil.cpu_percent(interval=0.2), 1),
            memory_percent=round(psutil.virtual_memory().percent, 1),
            disk_percent=round(psutil.disk_usage("/").percent, 1),
            load1=load1,
            load5=load5,
            load15=load15,
            uptime_seconds=uptime,
        )
