"""Application configuration.

All configuration is sourced from environment variables (or a local ``.env``
file during development) via ``pydantic-settings``. Secrets must never be
hard-coded; this module is the single place where the environment is read.
"""

from functools import lru_cache
from typing import Any

from pydantic import PostgresDsn, field_validator
from pydantic_core.core_schema import ValidationInfo
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed application settings.

    Values are validated at startup, so a misconfigured deployment fails fast
    instead of failing later at request time.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # --- Project metadata -------------------------------------------------
    PROJECT_NAME: str = "Network Operations Platform"
    API_V1_PREFIX: str = "/api/v1"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False

    # --- Security / JWT ---------------------------------------------------
    # SECRET_KEY MUST be provided by the environment in any real deployment.
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # --- First administrator (bootstrap) ----------------------------------
    FIRST_ADMIN_EMAIL: str = "admin@example.com"
    FIRST_ADMIN_PASSWORD: str = "changeme"
    FIRST_ADMIN_USERNAME: str = "admin"

    # --- CORS -------------------------------------------------------------
    BACKEND_CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def _assemble_cors_origins(cls, value: Any) -> Any:
        """Allow CORS origins to be supplied as a comma-separated string."""
        if isinstance(value, str) and not value.startswith("["):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    # --- Monitoring: SNMP defaults ----------------------------------------
    # Per-device values override these; they are sensible fallbacks only.
    SNMP_DEFAULT_COMMUNITY: str = "public"
    SNMP_DEFAULT_PORT: int = 161
    SNMP_TIMEOUT_SECONDS: float = 2.0
    SNMP_RETRIES: int = 1

    # --- Monitoring: ICMP ping --------------------------------------------
    PING_COUNT: int = 3
    PING_TIMEOUT_SECONDS: float = 2.0

    # --- Monitoring: Zabbix API -------------------------------------------
    # Optional. When configured, devices can be polled via the Zabbix API.
    ZABBIX_URL: str | None = None
    ZABBIX_USER: str | None = None
    ZABBIX_PASSWORD: str | None = None
    ZABBIX_VERIFY_TLS: bool = True
    ZABBIX_TIMEOUT_SECONDS: float = 10.0

    # --- Telegram bot -----------------------------------------------------
    # Leave TELEGRAM_BOT_TOKEN empty to disable Telegram delivery entirely.
    TELEGRAM_BOT_TOKEN: str | None = None
    TELEGRAM_API_BASE_URL: str = "https://api.telegram.org"
    # Shared secret for the inbound webhook path/header. If empty the webhook
    # endpoint is disabled (use long-polling instead).
    TELEGRAM_WEBHOOK_SECRET: str | None = None
    TELEGRAM_MAX_RETRIES: int = 3
    TELEGRAM_RETRY_BACKOFF_SECONDS: float = 0.5
    TELEGRAM_TIMEOUT_SECONDS: float = 10.0
    # Rate limiting: Telegram allows ~30 msg/s globally and ~1 msg/s per chat.
    TELEGRAM_RATE_LIMIT_PER_SECOND: float = 25.0
    TELEGRAM_PER_CHAT_INTERVAL_SECONDS: float = 1.0
    TELEGRAM_POLL_INTERVAL_SECONDS: float = 2.0

    # --- Alerting thresholds (fallbacks when a rule has no threshold) ------
    ALERT_CPU_THRESHOLD: float = 90.0
    ALERT_MEMORY_THRESHOLD: float = 90.0
    ALERT_DISK_THRESHOLD: float = 90.0
    ALERT_INTERFACE_UTIL_THRESHOLD: float = 90.0
    ALERT_PACKET_LOSS_THRESHOLD: float = 20.0

    # --- Configuration backup (Phase 4) -----------------------------------
    # Fernet key (44-char urlsafe base64) used to encrypt device SSH secrets
    # at rest. If empty, a key is derived from SECRET_KEY (fine for dev, but
    # rotating SECRET_KEY then makes stored secrets undecryptable — set a
    # dedicated key in production: `python -c "from cryptography.fernet import
    # Fernet; print(Fernet.generate_key().decode())"`).
    BACKUP_ENCRYPTION_KEY: str | None = None
    # Per-operation timeout (seconds) for an SSH config fetch.
    BACKUP_SSH_TIMEOUT_SECONDS: float = 30.0

    # --- Database ---------------------------------------------------------
    POSTGRES_SERVER: str = "db"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "netops"
    POSTGRES_PASSWORD: str = "netops"
    POSTGRES_DB: str = "netops"
    # Populated by the validator below; never set this directly.
    DATABASE_URI: PostgresDsn | None = None

    @field_validator("DATABASE_URI", mode="before")
    @classmethod
    def _assemble_db_uri(cls, value: Any, info: ValidationInfo) -> Any:
        """Build the async SQLAlchemy DSN from the discrete POSTGRES_* parts."""
        if isinstance(value, str) and value:
            return value
        data = info.data
        return PostgresDsn.build(
            scheme="postgresql+asyncpg",
            username=data.get("POSTGRES_USER"),
            password=data.get("POSTGRES_PASSWORD"),
            host=data.get("POSTGRES_SERVER"),
            port=data.get("POSTGRES_PORT"),
            path=data.get("POSTGRES_DB") or "",
        )

    @property
    def sync_database_uri(self) -> str:
        """Synchronous DSN used by Alembic migrations (psycopg driver)."""
        return str(self.DATABASE_URI).replace(
            "postgresql+asyncpg", "postgresql+psycopg"
        )


@lru_cache
def get_settings() -> Settings:
    """Return a cached ``Settings`` instance.

    Caching ensures the environment is parsed exactly once and gives us a
    single object to override in tests via dependency injection.
    """
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
