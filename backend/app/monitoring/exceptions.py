"""Collector-layer exceptions.

These live in the monitoring (infrastructure) layer so collectors do not depend
on the service layer above them. The service layer translates
``CollectorConfigurationError`` into a domain ``MonitoringError`` (→ HTTP 400),
while transient ``CollectorError`` failures are caught and degraded gracefully.
"""


class CollectorError(Exception):
    """Base class for collector failures."""


class CollectorConfigurationError(CollectorError):
    """A poll cannot proceed because of a configuration problem.

    Examples: SNMPv3 requested without v3 credentials, or a Zabbix poll for a
    device that has no ``zabbix_host_id``. These are *caller* errors and should
    surface to the API as a 4xx rather than being silently degraded.
    """
