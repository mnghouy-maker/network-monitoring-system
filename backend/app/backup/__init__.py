"""Configuration-backup infrastructure: pluggable SSH config backends.

Backends implement :class:`~app.backup.protocols.ConfigBackend`. The heavy
network-automation libraries (napalm, netmiko/paramiko) are imported lazily and
their blocking calls run in a worker thread, so importing the app or running the
tests never requires them.
"""

from app.backup.protocols import ConfigBackend, ConnectionParams

__all__ = ["ConfigBackend", "ConnectionParams"]
