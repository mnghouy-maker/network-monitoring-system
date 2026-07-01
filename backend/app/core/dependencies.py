"""FastAPI dependency-injection wiring.

This is the composition root: it assembles repositories and services from a
request-scoped database session, and provides the auth guards used to protect
endpoints. Endpoints depend on these factories rather than constructing their
own collaborators, which keeps them thin and testable.
"""

import uuid
from collections.abc import Awaitable, Callable
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.backup.napalm_backend import NapalmConfigBackend
from app.backup.netmiko_backend import NetmikoConfigBackend
from app.backup.protocols import ConfigBackend
from app.core.config import settings
from app.core.security import ACCESS_TOKEN_TYPE, decode_token
from app.db.session import get_session
from app.health.local import LocalHealthCollector
from app.health.protocols import HealthCollector
from app.health.ssh import SshHealthCollector
from app.models.alert import AlertType
from app.models.user import User, UserRole
from app.monitoring.ping import SubprocessPingCollector
from app.monitoring.protocols import MetricCollector, PingCollector
from app.monitoring.snmp import SnmpMetricCollector
from app.monitoring.zabbix import ZabbixMetricCollector
from app.repositories.alert import (
    AlertAcknowledgementRepository,
    AlertHistoryRepository,
    AlertRuleRepository,
)
from app.repositories.backup import (
    ConfigBackupRepository,
    ConnectionProfileRepository,
)
from app.repositories.device import DeviceRepository
from app.repositories.metric import MetricRepository
from app.repositories.server import ServerHealthRepository, ServerRepository
from app.repositories.telegram import (
    TelegramChatRepository,
    TelegramUserRepository,
)
from app.repositories.user import UserRepository
from app.services.alerting import AlertingService
from app.services.auth import AuthService
from app.services.backup import ConfigBackupService, ConnectionProfileService
from app.services.device import DeviceService
from app.services.monitoring import MonitoringService
from app.services.notifier import AlertNotifier
from app.services.server_health import (
    HealthThresholds,
    ServerHealthService,
    ServerService,
)
from app.services.telegram_bot import (
    TelegramAdminService,
    TelegramCommandService,
    TelegramUpdateDispatcher,
)
from app.services.user import UserService
from app.telegram.client import TelegramClient
from app.telegram.protocols import TelegramSender
from app.telegram.rate_limit import RateLimiter

# tokenUrl is used by Swagger UI's "Authorize" button.
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_PREFIX}/auth/login"
)

# --- Session ------------------------------------------------------------------
DbSession = Annotated[AsyncSession, Depends(get_session)]


# --- Repositories -------------------------------------------------------------
def get_user_repository(session: DbSession) -> UserRepository:
    return UserRepository(session)


def get_device_repository(session: DbSession) -> DeviceRepository:
    return DeviceRepository(session)


def get_metric_repository(session: DbSession) -> MetricRepository:
    return MetricRepository(session)


def get_alert_rule_repository(session: DbSession) -> AlertRuleRepository:
    return AlertRuleRepository(session)


def get_alert_history_repository(session: DbSession) -> AlertHistoryRepository:
    return AlertHistoryRepository(session)


def get_alert_ack_repository(
    session: DbSession,
) -> AlertAcknowledgementRepository:
    return AlertAcknowledgementRepository(session)


def get_telegram_user_repository(session: DbSession) -> TelegramUserRepository:
    return TelegramUserRepository(session)


def get_telegram_chat_repository(session: DbSession) -> TelegramChatRepository:
    return TelegramChatRepository(session)


def get_connection_profile_repository(
    session: DbSession,
) -> ConnectionProfileRepository:
    return ConnectionProfileRepository(session)


def get_config_backup_repository(session: DbSession) -> ConfigBackupRepository:
    return ConfigBackupRepository(session)


def get_server_repository(session: DbSession) -> ServerRepository:
    return ServerRepository(session)


def get_server_health_repository(session: DbSession) -> ServerHealthRepository:
    return ServerHealthRepository(session)


UserRepo = Annotated[UserRepository, Depends(get_user_repository)]
DeviceRepo = Annotated[DeviceRepository, Depends(get_device_repository)]
MetricRepo = Annotated[MetricRepository, Depends(get_metric_repository)]
AlertRuleRepo = Annotated[
    AlertRuleRepository, Depends(get_alert_rule_repository)
]
AlertHistoryRepo = Annotated[
    AlertHistoryRepository, Depends(get_alert_history_repository)
]
AlertAckRepo = Annotated[
    AlertAcknowledgementRepository, Depends(get_alert_ack_repository)
]
TelegramUserRepo = Annotated[
    TelegramUserRepository, Depends(get_telegram_user_repository)
]
TelegramChatRepo = Annotated[
    TelegramChatRepository, Depends(get_telegram_chat_repository)
]
ConnectionProfileRepo = Annotated[
    ConnectionProfileRepository, Depends(get_connection_profile_repository)
]
ConfigBackupRepo = Annotated[
    ConfigBackupRepository, Depends(get_config_backup_repository)
]
ServerRepo = Annotated[ServerRepository, Depends(get_server_repository)]
ServerHealthRepo = Annotated[
    ServerHealthRepository, Depends(get_server_health_repository)
]


# --- Collectors (process-wide singletons, configured from settings) ----------
@lru_cache
def get_ping_collector() -> PingCollector:
    return SubprocessPingCollector(
        count=settings.PING_COUNT,
        timeout_seconds=settings.PING_TIMEOUT_SECONDS,
    )


@lru_cache
def get_snmp_collector() -> MetricCollector:
    return SnmpMetricCollector(
        timeout_seconds=settings.SNMP_TIMEOUT_SECONDS,
        retries=settings.SNMP_RETRIES,
    )


@lru_cache
def get_zabbix_collector() -> ZabbixMetricCollector:
    return ZabbixMetricCollector(
        url=settings.ZABBIX_URL,
        user=settings.ZABBIX_USER,
        password=settings.ZABBIX_PASSWORD,
        verify_tls=settings.ZABBIX_VERIFY_TLS,
        timeout_seconds=settings.ZABBIX_TIMEOUT_SECONDS,
    )


# --- Telegram client (process-wide singleton; holds rate-limiter state) ------
@lru_cache
def get_telegram_client() -> TelegramClient:
    rate_limiter = RateLimiter(
        settings.TELEGRAM_RATE_LIMIT_PER_SECOND,
        settings.TELEGRAM_PER_CHAT_INTERVAL_SECONDS,
    )
    return TelegramClient(
        settings.TELEGRAM_BOT_TOKEN,
        base_url=settings.TELEGRAM_API_BASE_URL,
        rate_limiter=rate_limiter,
        max_retries=settings.TELEGRAM_MAX_RETRIES,
        backoff_seconds=settings.TELEGRAM_RETRY_BACKOFF_SECONDS,
        timeout_seconds=settings.TELEGRAM_TIMEOUT_SECONDS,
    )


# --- Config-backup backends (stateless singletons) ---------------------------
@lru_cache
def get_napalm_backend() -> ConfigBackend:
    return NapalmConfigBackend()


@lru_cache
def get_netmiko_backend() -> ConfigBackend:
    return NetmikoConfigBackend()


# --- Server health collectors (stateless singletons) -------------------------
@lru_cache
def get_local_health_collector() -> HealthCollector:
    return LocalHealthCollector()


@lru_cache
def get_ssh_health_collector() -> HealthCollector:
    return SshHealthCollector()


def _health_thresholds() -> HealthThresholds:
    return HealthThresholds(
        cpu_warn=settings.SERVER_CPU_WARN,
        cpu_crit=settings.SERVER_CPU_CRIT,
        memory_warn=settings.SERVER_MEMORY_WARN,
        memory_crit=settings.SERVER_MEMORY_CRIT,
        disk_warn=settings.SERVER_DISK_WARN,
        disk_crit=settings.SERVER_DISK_CRIT,
    )


def _alert_default_thresholds() -> dict[AlertType, float]:
    return {
        AlertType.HIGH_CPU: settings.ALERT_CPU_THRESHOLD,
        AlertType.HIGH_MEMORY: settings.ALERT_MEMORY_THRESHOLD,
        AlertType.HIGH_DISK: settings.ALERT_DISK_THRESHOLD,
        AlertType.HIGH_INTERFACE_UTIL: settings.ALERT_INTERFACE_UTIL_THRESHOLD,
        AlertType.PACKET_LOSS: settings.ALERT_PACKET_LOSS_THRESHOLD,
    }


# --- Services -----------------------------------------------------------------
def get_user_service(repo: UserRepo) -> UserService:
    return UserService(repo)


def get_auth_service(repo: UserRepo) -> AuthService:
    return AuthService(repo)


def get_device_service(repo: DeviceRepo) -> DeviceService:
    return DeviceService(repo)


def get_monitoring_service(
    device_repo: DeviceRepo, metric_repo: MetricRepo
) -> MonitoringService:
    zabbix = get_zabbix_collector()
    return MonitoringService(
        device_repo=device_repo,
        metric_repo=metric_repo,
        ping_collector=get_ping_collector(),
        snmp_collector=get_snmp_collector(),
        zabbix_collector=zabbix if zabbix.is_configured else None,
    )


def get_alert_notifier(
    chat_repo: TelegramChatRepo,
) -> AlertNotifier:
    return AlertNotifier(get_telegram_client(), chat_repo)


def get_alerting_service(
    rule_repo: AlertRuleRepo,
    history_repo: AlertHistoryRepo,
    ack_repo: AlertAckRepo,
    device_repo: DeviceRepo,
    metric_repo: MetricRepo,
    notifier: Annotated[AlertNotifier, Depends(get_alert_notifier)],
) -> AlertingService:
    return AlertingService(
        rule_repo=rule_repo,
        history_repo=history_repo,
        ack_repo=ack_repo,
        device_repo=device_repo,
        metric_repo=metric_repo,
        notifier=notifier,
        default_thresholds=_alert_default_thresholds(),
    )


def get_telegram_command_service(
    device_repo: DeviceRepo,
    metric_repo: MetricRepo,
    history_repo: AlertHistoryRepo,
) -> TelegramCommandService:
    return TelegramCommandService(device_repo, metric_repo, history_repo)


def get_telegram_dispatcher(
    command_service: Annotated[
        TelegramCommandService, Depends(get_telegram_command_service)
    ],
    alerting_service: Annotated[
        AlertingService, Depends(get_alerting_service)
    ],
    tg_user_repo: TelegramUserRepo,
) -> TelegramUpdateDispatcher:
    return TelegramUpdateDispatcher(
        sender=get_telegram_client(),
        command_service=command_service,
        alerting_service=alerting_service,
        telegram_user_repo=tg_user_repo,
    )


def get_telegram_admin_service(
    user_repo: TelegramUserRepo, chat_repo: TelegramChatRepo
) -> TelegramAdminService:
    return TelegramAdminService(user_repo, chat_repo)


def get_connection_profile_service(
    profile_repo: ConnectionProfileRepo, device_repo: DeviceRepo
) -> ConnectionProfileService:
    return ConnectionProfileService(profile_repo, device_repo)


def get_config_backup_service(
    backup_repo: ConfigBackupRepo,
    profile_repo: ConnectionProfileRepo,
    device_repo: DeviceRepo,
) -> ConfigBackupService:
    return ConfigBackupService(
        backup_repo=backup_repo,
        profile_repo=profile_repo,
        device_repo=device_repo,
        napalm_backend=get_napalm_backend(),
        netmiko_backend=get_netmiko_backend(),
        ssh_timeout=settings.BACKUP_SSH_TIMEOUT_SECONDS,
    )


def get_server_service(repo: ServerRepo) -> ServerService:
    return ServerService(repo)


def get_server_health_service(
    server_repo: ServerRepo, health_repo: ServerHealthRepo
) -> ServerHealthService:
    return ServerHealthService(
        server_repo=server_repo,
        health_repo=health_repo,
        local_collector=get_local_health_collector(),
        ssh_collector=get_ssh_health_collector(),
        thresholds=_health_thresholds(),
        ssh_timeout=settings.HEALTH_SSH_TIMEOUT_SECONDS,
    )


UserSvc = Annotated[UserService, Depends(get_user_service)]
AuthSvc = Annotated[AuthService, Depends(get_auth_service)]
DeviceSvc = Annotated[DeviceService, Depends(get_device_service)]
MonitoringSvc = Annotated[
    MonitoringService, Depends(get_monitoring_service)
]
AlertingSvc = Annotated[AlertingService, Depends(get_alerting_service)]
TelegramDispatcher = Annotated[
    TelegramUpdateDispatcher, Depends(get_telegram_dispatcher)
]
TelegramAdminSvc = Annotated[
    TelegramAdminService, Depends(get_telegram_admin_service)
]
TelegramClientDep = Annotated[TelegramSender, Depends(get_telegram_client)]
ConnectionProfileSvc = Annotated[
    ConnectionProfileService, Depends(get_connection_profile_service)
]
ConfigBackupSvc = Annotated[
    ConfigBackupService, Depends(get_config_backup_service)
]
ServerSvc = Annotated[ServerService, Depends(get_server_service)]
ServerHealthSvc = Annotated[
    ServerHealthService, Depends(get_server_health_service)
]


# --- Current user / auth guards ----------------------------------------------
_credentials_exc = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    repo: UserRepo,
) -> User:
    """Resolve the authenticated user from a bearer access token."""
    claims = decode_token(token)
    if claims is None or claims.get("type") != ACCESS_TOKEN_TYPE:
        raise _credentials_exc

    try:
        user_id = uuid.UUID(str(claims.get("sub")))
    except (ValueError, TypeError):
        raise _credentials_exc from None

    user = await repo.get(user_id)
    if user is None:
        raise _credentials_exc
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_current_active_user(current_user: CurrentUser) -> User:
    """Like :func:`get_current_user` but rejects disabled accounts."""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user"
        )
    return current_user


ActiveUser = Annotated[User, Depends(get_current_active_user)]


def require_roles(*allowed: UserRole) -> Callable[[User], Awaitable[User]]:
    """Build a dependency that authorizes only the given roles.

    Superusers always pass. Usage::

        @router.get(..., dependencies=[Depends(require_roles(UserRole.ADMIN))])
    """

    async def _guard(current_user: ActiveUser) -> User:
        if current_user.is_superuser or current_user.role in allowed:
            return current_user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions for this operation",
        )

    return _guard
