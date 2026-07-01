"""Server health collection infrastructure.

Collectors implement :class:`~app.health.protocols.HealthCollector`. The local
collector uses ``psutil`` (lazily imported); the SSH collector runs a small
shell snippet over Paramiko (lazily imported) and parses it. Both keep heavy
libraries out of module import so the app and tests load without them.
"""

from app.health.protocols import HealthCollector, HealthSample

__all__ = ["HealthCollector", "HealthSample"]
