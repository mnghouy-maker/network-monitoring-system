"""SSH health collector: runs a small shell snippet and parses key=value lines.

Paramiko is imported lazily and the blocking session runs in a worker thread.
The output parser is a pure function, so it is unit-tested without any network.
"""

import asyncio

from app.health.protocols import HealthSample, HealthTarget

# Emits: cpu=<pct> mem=<total used> disk=<total used> load=<l1 l5 l15> uptime=<s>
_SNIPPET = (
    "echo cpu=$(awk '/^cpu /{t=0;for(i=2;i<=NF;i++)t+=$i;"
    "print 100-($5*100/t)}' /proc/stat); "
    "echo mem=$(free -b | awk '/^Mem:/{print $2\" \"$3}'); "
    "echo disk=$(df -kP / | awk 'NR==2{print $2\" \"$3}'); "
    "echo load=$(cat /proc/loadavg | awk '{print $1\" \"$2\" \"$3}'); "
    "echo uptime=$(awk '{print $1}' /proc/uptime)"
)


class SshHealthCollector:
    """Collect health of a remote host over SSH."""

    async def collect(self, target: HealthTarget) -> HealthSample:
        try:
            output = await asyncio.wait_for(
                asyncio.to_thread(self._sync_run, target),
                timeout=target.timeout,
            )
        except Exception:  # noqa: BLE001 - unreachable host
            return HealthSample(reachable=False)
        return self.parse_output(output)

    @staticmethod
    def _sync_run(target: HealthTarget) -> str:
        import paramiko

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=target.hostname,
            port=target.ssh_port,
            username=target.ssh_username,
            password=target.ssh_password,
            timeout=target.timeout,
            allow_agent=False,
            look_for_keys=False,
        )
        try:
            _stdin, stdout, _stderr = client.exec_command(
                _SNIPPET, timeout=target.timeout
            )
            return stdout.read().decode(errors="ignore")
        finally:
            client.close()

    @staticmethod
    def parse_output(output: str) -> HealthSample:
        fields: dict[str, str] = {}
        for line in output.splitlines():
            if "=" in line:
                key, _, value = line.partition("=")
                fields[key.strip()] = value.strip()

        sample = HealthSample(reachable=True)
        sample.cpu_percent = _round_float(fields.get("cpu"))
        sample.memory_percent = _percent_from_pair(fields.get("mem"))
        sample.disk_percent = _percent_from_pair(fields.get("disk"))

        load = (fields.get("load") or "").split()
        if len(load) == 3:
            sample.load1 = _to_float(load[0])
            sample.load5 = _to_float(load[1])
            sample.load15 = _to_float(load[2])

        uptime = _to_float(fields.get("uptime"))
        sample.uptime_seconds = int(uptime) if uptime is not None else None
        return sample


def _to_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _round_float(value: str | None) -> float | None:
    parsed = _to_float(value)
    return round(parsed, 1) if parsed is not None else None


def _percent_from_pair(pair: str | None) -> float | None:
    """Compute ``used/total*100`` from a ``"<total> <used>"`` string."""
    if not pair:
        return None
    parts = pair.split()
    if len(parts) != 2:
        return None
    total = _to_float(parts[0])
    used = _to_float(parts[1])
    if not total or total <= 0 or used is None:
        return None
    return round(used / total * 100, 1)
