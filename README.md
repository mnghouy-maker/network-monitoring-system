# Network Operations Platform

A self-hosted Network Operations Platform (NetOps). This repository is being
built **one phase at a time**.

> **Status: Phase 3 — Telegram Alert System ✅**
> Threshold/condition alerting engine (device offline/online, high CPU/memory/
> disk/interface-utilization, packet loss) with alert **history**,
> **acknowledgement**, **recovery** notifications, and severity-based **routing**
> to Telegram chats. A Telegram bot serves `/help /status /devices /device
> /alerts /critical`, with rate limiting, retries and logging. Built on the
> Phase 1–2 foundation.

Planned capabilities (future phases): Configuration Backup
(Netmiko/Paramiko/NAPALM), Server Health Monitoring, an AI Troubleshooting
Assistant, and a React/Tailwind dashboard.

### Phase history

| Phase | Scope | Status |
|-------|-------|--------|
| 1 | Project foundation: FastAPI, PostgreSQL, SQLAlchemy, Alembic, JWT/RBAC | ✅ |
| 2 | Device inventory + network monitoring (SNMP & Zabbix) | ✅ |
| 3 | Telegram alert system (routing, history, ack, recovery, bot commands) | ✅ |

---

## 1. Architecture

The platform uses a **clean, layered architecture** with strict separation of
concerns. Each layer depends only on the layer beneath it, and all collaborators
are wired through FastAPI's dependency-injection system.

```
                         ┌──────────────────────────────┐
   HTTP client  ──────▶  │           FastAPI app         │
   (Swagger / React /    │      app/main.py + CORS       │
    curl / Telegram)     └───────────────┬───────────────┘
                                          │
                         ┌────────────────▼────────────────────┐
                         │        API layer (routers)           │   app/api/v1
                         │  auth · users · devices · monitoring │
                         └────────────────┬─────────────────────┘
                                          │  Depends(...)  (DI)
                         ┌────────────────▼─────────────────────┐
                         │     Service layer (business logic)    │   app/services
                         │  Auth · User · Device · Monitoring    │
                         └───────┬──────────────────────┬────────┘
                                 │                      │
              ┌──────────────────▼─────────┐   ┌────────▼──────────────────┐
              │  Repository layer (data)   │   │  Monitoring collectors     │  app/monitoring
              │  User · Device · Metric    │   │  Ping · SNMP · Zabbix      │
              └──────────────────┬─────────┘   └────────┬──────────────────┘
                                 │                      │
              ┌──────────────────▼─────────┐   ┌────────▼──────────────────┐
              │        PostgreSQL 16        │   │ ICMP · SNMP agents ·       │
              │  users · devices · metrics  │   │ Zabbix API (network)       │
              └────────────────────────────┘   └────────────────────────────┘

   Cross-cutting:  app/core  →  config (env vars) · security (JWT/bcrypt) · DI
   Migrations:     alembic/  →  schema versioning
```

**Why this shape?**

| Layer | Responsibility | Benefit |
|-------|----------------|---------|
| **API** | HTTP concerns, status codes, serialization | Thin controllers, easy to read |
| **Service** | Business rules, orchestration | Framework-agnostic, unit-testable |
| **Repository** | All DB queries | Swappable persistence, mockable |
| **Collectors** | Talk to ICMP/SNMP/Zabbix (infra) | Pluggable behind `Protocol`s, fakeable |
| **Core** | Config, security, DI wiring | Single source of truth for secrets |

This boundary is what lets the unit tests run **without a database or network** —
services talk to repository and collector *interfaces*, which the tests replace
with in-memory/preset fakes.

### Monitoring design

`MonitoringService` always probes reachability with the **ping collector**, then
collects health gauges (CPU, memory, uptime) and **interface statistics** from
the requested **source** — `SNMP` (default) or `Zabbix`. Collectors implement a
common `MetricCollector` protocol so they are interchangeable. Heavy third-party
clients (`puresnmp`, `httpx`) are **imported lazily** inside the collectors, so
importing the app or running the tests never requires them. A collector failure
degrades gracefully: the snapshot is still written with `reachable` recorded and
the unavailable gauges left `null`, rather than aborting the poll.

### Alerting & Telegram design (Phase 3)

```
   metrics (Phase 2)                         inbound updates (Telegram)
        │                                     webhook  ┐        ┌ long-poll
        ▼                                              ▼        ▼
 ┌──────────────┐    fire/resolve   ┌─────────────────────────────────┐
 │AlertEvaluator│──►│ AlertingService│──►│ AlertNotifier │─► Telegram   │
 │ (pure logic) │   │ dedup+lifecycle│   │ (severity route)│  chats     │
 └──────────────┘   └───────┬────────┘   └────────────────┘            │
                            │  persist                TelegramUpdateDispatcher
                    alert_history / acks     ┌────────┴─────────┐
                                             │ CommandService   │ /help /status …
                                             │ (ack via button) │
                                             └──────────────────┘
   Telegram client: rate limiting + retries + logging (app/telegram/client.py)
```

* **Evaluation** — `AlertEvaluator` is pure logic: given a device, its latest
  metric (and the previous one for interface-utilization rate), it decides if a
  rule's condition is met. `AlertingService` persists transitions, **dedupes**
  (one open alert per device+type), emits **recovery** on clear, and handles
  **acknowledgement**.
* **Routing** — severity-based: an alert goes to every active chat whose
  `min_severity` is at or below the alert's severity.
* **Bot** — one `TelegramUpdateDispatcher` handles both webhook and long-poll
  updates: it runs commands and processes inline **Acknowledge** buttons.
  Unknown Telegram users are auto-registered *inactive* (an allowlist on top of
  the bot token); an admin enables them via the API.
* **Reliability** — the `TelegramClient` paces sends (global + per-chat rate
  limits), retries on `429`/`5xx`/network errors with backoff (honouring
  `retry_after`), and logs. The token comes from `TELEGRAM_BOT_TOKEN`; when
  unset, delivery is a no-op and the rest of the platform is unaffected.
* **Triggering** — evaluation is exposed as `POST /alerts/evaluate[/{id}]`
  (Phase 2's polling is left untouched); a scheduler can call it periodically.

---

## 2. Folder Structure

```
network-monitoring-system/
├── docker-compose.yml          # Postgres + backend stack
├── .env.example                # Copy to .env and edit
├── .gitignore
├── README.md
└── backend/
    ├── Dockerfile
    ├── .dockerignore
    ├── entrypoint.sh           # runs migrations, then uvicorn
    ├── requirements.txt        # runtime deps
    ├── requirements-dev.txt    # + test/lint deps
    ├── pyproject.toml          # pytest / ruff / mypy config
    ├── alembic.ini
    ├── alembic/
    │   ├── env.py              # reads DB URL + metadata from the app
    │   ├── script.py.mako
    │   └── versions/
    │       ├── 0001_create_users_table.py
    │       └── 0002_devices_and_metrics.py     # Phase 2
    ├── app/
    │   ├── main.py             # app factory, lifespan, admin bootstrap
    │   ├── core/
    │   │   ├── config.py       # pydantic-settings (env vars)
    │   │   ├── security.py     # bcrypt + JWT
    │   │   └── dependencies.py # DI: sessions, repos, services, collectors
    │   ├── db/
    │   │   ├── base.py         # DeclarativeBase + TimestampMixin
    │   │   └── session.py      # async engine + unit-of-work session
    │   ├── models/
    │   │   ├── user.py · device.py · metric.py
    │   │   ├── alert.py        # AlertRule/History/Ack + enums         (Phase 3)
    │   │   └── telegram.py     # TelegramUser / TelegramChat           (Phase 3)
    │   ├── schemas/
    │   │   ├── user.py · token.py · device.py · metric.py
    │   │   ├── alert.py         # rule/history/ack contracts           (Phase 3)
    │   │   └── telegram.py      # user/chat contracts                  (Phase 3)
    │   ├── repositories/
    │   │   ├── user.py · device.py · metric.py
    │   │   ├── alert.py         # rule/history/ack repos               (Phase 3)
    │   │   └── telegram.py      # user/chat repos                      (Phase 3)
    │   ├── services/
    │   │   ├── auth.py · user.py · device.py · monitoring.py · exceptions.py
    │   │   ├── alerting.py      # AlertEvaluator + AlertingService     (Phase 3)
    │   │   ├── notifier.py      # severity-based alert routing         (Phase 3)
    │   │   └── telegram_bot.py  # commands + dispatcher + admin        (Phase 3)
    │   ├── monitoring/          # collector infrastructure            (Phase 2)
    │   │   ├── protocols.py · types.py · ping.py · snmp.py · zabbix.py
    │   ├── telegram/            # Telegram infrastructure              (Phase 3)
    │   │   ├── protocols.py     # TelegramSender protocol
    │   │   ├── client.py        # Bot API client (rate limit + retry)
    │   │   ├── rate_limit.py    # global + per-chat limiter
    │   │   ├── formatting.py    # HTML alert/recovery formatting
    │   │   └── poller.py        # long-polling worker (python -m ...)
    │   └── api/
    │       └── v1/
    │           ├── router.py
    │           └── endpoints/
    │               ├── auth.py · users.py · health.py
    │               ├── devices.py · monitoring.py                     (Phase 2)
    │               ├── alerts.py      # rules/history/ack/evaluate    (Phase 3)
    │               └── telegram.py    # webhook + users/chats admin   (Phase 3)
    └── tests/
        ├── conftest.py            # in-memory repo/collector/sender fakes
        ├── test_*.py              # Phases 1–2 (security, services, api, …)
        ├── test_alert_evaluator.py · test_alerting_service.py         # (Phase 3)
        ├── test_telegram_command.py · test_telegram_dispatcher.py     # (Phase 3)
        ├── test_telegram_client.py · test_rate_limiter.py            # (Phase 3)
        ├── test_telegram_formatting.py · test_alerts_api.py           # (Phase 3)
```

---

## 3. Database Schema

Tables: **`users`** (Phase 1), **`devices`**, **`device_metrics`**,
**`interface_stats`** (Phase 2).

```
 users                devices ──1:N──► device_metrics ──1:N──► interface_stats
 (auth/RBAC)          (inventory)      (poll snapshots)        (per-interface)
```

Both monitoring foreign keys are `ON DELETE CASCADE`, so deleting a device
removes its metrics, and removing a metric snapshot removes its interface rows.

### `users`

| Column            | Type                        | Constraints                       |
|-------------------|-----------------------------|-----------------------------------|
| `id`              | `UUID`                      | PK, default `uuid4()`             |
| `email`           | `VARCHAR(255)`              | NOT NULL, UNIQUE, indexed         |
| `username`        | `VARCHAR(100)`              | NOT NULL, UNIQUE, indexed         |
| `hashed_password` | `VARCHAR(255)`              | NOT NULL (bcrypt)                 |
| `full_name`       | `VARCHAR(255)`              | NULL                              |
| `role`            | `user_role` (ENUM)          | NOT NULL, default `viewer`        |
| `is_active`       | `BOOLEAN`                   | NOT NULL, default `true`          |
| `is_superuser`    | `BOOLEAN`                   | NOT NULL, default `false`         |
| `created_at`      | `TIMESTAMPTZ`               | NOT NULL, default `now()`         |
| `updated_at`      | `TIMESTAMPTZ`               | NOT NULL, default `now()`, on update |

`user_role` is a native PostgreSQL `ENUM('admin', 'operator', 'viewer')`.

### Roles & permissions (Phase 1)

| Role       | Capabilities                                                        |
|------------|---------------------------------------------------------------------|
| **Admin**  | Full user CRUD (`/api/v1/users`), plus everything below.            |
| **Operator** | Authenticated access; will run network operations in later phases. |
| **Viewer** | Authenticated read-only access (dashboards/monitoring later).      |

`is_superuser` always bypasses role checks. The bootstrap admin created on first
startup is an Admin **and** a superuser.

### `devices`

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | `UUID` | PK, default `uuid4()` |
| `name` | `VARCHAR(255)` | NOT NULL, UNIQUE, indexed |
| `hostname` | `VARCHAR(255)` | NOT NULL (IP or DNS) |
| `category` | `device_category` (ENUM) | NOT NULL, default `other`, indexed |
| `vendor` | `VARCHAR(100)` | NULL |
| `model` | `VARCHAR(100)` | NULL |
| `location` | `VARCHAR(255)` | NULL |
| `description` | `TEXT` | NULL |
| `snmp_community` | `VARCHAR(255)` | NOT NULL, default `public` (write-only) |
| `snmp_version` | `snmp_version` (ENUM) | NOT NULL, default `v2c` |
| `snmp_port` | `INTEGER` | NOT NULL, default `161` |
| `zabbix_host_id` | `VARCHAR(64)` | NULL (maps to a Zabbix host) |
| `is_active` | `BOOLEAN` | NOT NULL, default `true` |
| `created_at` / `updated_at` | `TIMESTAMPTZ` | NOT NULL, managed |

`device_category` = `router·switch·firewall·server·access_point·load_balancer·other`;
`snmp_version` = `v1·v2c·v3`. The SNMP community is accepted on create/update but
**excluded from responses** so the secret is not leaked in listings.

### `device_metrics` (one row per poll)

| Column | Type | Notes |
|--------|------|-------|
| `id` | `UUID` | PK |
| `device_id` | `UUID` | FK → `devices.id`, CASCADE, indexed |
| `collected_at` | `TIMESTAMPTZ` | indexed, default `now()` |
| `source` | `metric_source` (ENUM) | `snmp` or `zabbix` |
| `reachable` | `BOOLEAN` | from ICMP ping |
| `latency_ms` / `packet_loss_percent` | `FLOAT` | ping results |
| `cpu_load_percent` / `memory_used_percent` | `FLOAT` | nullable gauges |
| `uptime_seconds` | `BIGINT` | nullable |

### `interface_stats` (per interface, per poll)

| Column | Type | Notes |
|--------|------|-------|
| `id` | `UUID` | PK |
| `metric_id` | `UUID` | FK → `device_metrics.id`, CASCADE, indexed |
| `if_index` | `INTEGER` | SNMP ifIndex |
| `name` | `VARCHAR(255)` | interface name/descr |
| `oper_status` | `VARCHAR(32)` | up/down/… |
| `speed_bps` | `BIGINT` | link speed |
| `in_octets` / `out_octets` | `BIGINT` | HC counters |
| `in_errors` / `out_errors` | `BIGINT` | error counters |

### Phase 3 tables

Migration `0003` adds five tables and four enums
(`alert_type`, `alert_severity`, `alert_status`, `chat_type`):

```
 alert_rules ──1:N──► alert_history ──1:N──► alert_acknowledgements
 (thresholds)         (fired alerts)         (who acked)     ▲
 device_id?─►devices  device_id─►devices     telegram_user_id┘─► telegram_users
                                                             telegram_chats (routing)
```

* **`alert_rules`** — `name`, `alert_type`, `severity` (default `warning`),
  `threshold` (nullable → falls back to a config default), `device_id`
  (nullable = all devices, FK CASCADE), `is_enabled`.
* **`alert_history`** — `device_id` (FK CASCADE), `rule_id` (FK SET NULL),
  `alert_type`, `severity`, `status` (`firing`/`acknowledged`/`resolved`),
  `message`, `value`, `threshold`, `triggered_at`, `resolved_at`. Indexed on
  `(device_id, alert_type)`, `status`, `triggered_at`.
* **`alert_acknowledgements`** — `alert_id` (FK CASCADE), `telegram_user_id`
  (FK SET NULL), `note`, `acknowledged_at`.
* **`telegram_users`** — `telegram_user_id` (BIGINT, unique), `username`,
  `is_active` (authorization allowlist, default `false`), optional
  `platform_user_id`.
* **`telegram_chats`** — `chat_id` (BIGINT, unique), `chat_type`, `is_active`,
  `min_severity` (routing floor).

`alert_severity` (`info·warning·critical`) is a single shared enum used by
rules, history, and chats.

---

## 4. API Endpoints

### Phase 1 — auth & users

| Method | Path                     | Auth          | Description                     |
|--------|--------------------------|---------------|---------------------------------|
| GET    | `/`                      | —             | Service banner                  |
| GET    | `/api/v1/health`         | —             | Liveness probe                  |
| GET    | `/api/v1/ready`          | —             | Readiness (checks DB)           |
| POST   | `/api/v1/auth/login`     | —             | OAuth2 password → JWT pair      |
| POST   | `/api/v1/auth/refresh`   | refresh token | Rotate tokens                   |
| GET    | `/api/v1/auth/me`        | access token  | Current user profile            |
| GET    | `/api/v1/users`          | Admin         | List users                      |
| POST   | `/api/v1/users`          | Admin         | Create user                     |
| GET    | `/api/v1/users/{id}`     | Admin         | Get user                        |
| PATCH  | `/api/v1/users/{id}`     | Admin         | Update user                     |
| DELETE | `/api/v1/users/{id}`     | Admin         | Delete user                     |

### Phase 2 — device inventory & monitoring

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET    | `/api/v1/devices` | any user | List devices (filter `?category=`, `?is_active=`) |
| POST   | `/api/v1/devices` | Admin/Operator | Add a device |
| GET    | `/api/v1/devices/{id}` | any user | Get a device |
| PATCH  | `/api/v1/devices/{id}` | Admin/Operator | Edit a device |
| DELETE | `/api/v1/devices/{id}` | Admin/Operator | Delete a device |
| POST   | `/api/v1/monitoring/devices/{id}/poll` | Admin/Operator | Poll now (`?source=snmp\|zabbix`) |
| GET    | `/api/v1/monitoring/devices/{id}/latest` | any user | Latest metric snapshot |
| GET    | `/api/v1/monitoring/devices/{id}/history` | any user | Metric history |

"any user" = any authenticated, active user (Viewer included). Polling and
inventory writes are operational actions restricted to Admin/Operator.

### Phase 3 — alerts & Telegram

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET    | `/api/v1/alerts` | any user | Active alerts (filter `?severity=`) |
| GET    | `/api/v1/alerts/critical` | any user | Active critical alerts |
| GET    | `/api/v1/alerts/history` | any user | Alert history (filter `?device_id=`) |
| POST   | `/api/v1/alerts/{id}/ack` | Admin/Operator | Acknowledge an alert |
| POST   | `/api/v1/alerts/evaluate` | Admin/Operator | Evaluate all active devices |
| POST   | `/api/v1/alerts/evaluate/{device_id}` | Admin/Operator | Evaluate one device |
| GET/POST | `/api/v1/alerts/rules` | read: any / write: Admin/Operator | List / create rules |
| GET/PATCH/DELETE | `/api/v1/alerts/rules/{id}` | read: any / write: Admin/Operator | Rule CRUD |
| POST   | `/api/v1/telegram/webhook/{secret}` | secret-gated | Inbound Telegram updates |
| GET    | `/api/v1/telegram/users` | Admin | List Telegram users |
| PATCH  | `/api/v1/telegram/users/{id}` | Admin | Authorize/deactivate a user |
| GET/POST | `/api/v1/telegram/chats` | Admin | List / register alert chats |
| PATCH/DELETE | `/api/v1/telegram/chats/{id}` | Admin | Manage alert chats |

Interactive docs are served at **`/docs`** (Swagger UI) and **`/redoc`**.

---

## 5. Setup Instructions

### Option A — Docker Compose (recommended)

Prerequisites: Docker + Docker Compose.

```bash
# 1. Configure environment
cp .env.example .env
# Edit .env — at minimum set a strong SECRET_KEY and admin credentials:
#   openssl rand -hex 32

# 2. Build and start the stack
docker compose up --build

# 3. Verify
curl http://localhost:8000/api/v1/health        # {"status":"ok"}
open http://localhost:8000/docs                  # Swagger UI
```

On first boot the backend container automatically:
1. waits for Postgres to be healthy,
2. runs `alembic upgrade head`, and
3. creates the bootstrap admin from `FIRST_ADMIN_*`.

#### Optional: bundled Zabbix stack

The Zabbix server, web UI and its database are behind the `monitoring` compose
profile so the core stack stays light:

```bash
docker compose --profile monitoring up --build
```

Zabbix web is published on `http://localhost:8080` (default login `Admin` /
`zabbix`). To let the backend poll via Zabbix, set in `.env`:
`ZABBIX_URL=http://zabbix-web:8080`, `ZABBIX_USER=Admin`, `ZABBIX_PASSWORD=...`,
then poll a device with `?source=zabbix`. Without these, monitoring works via
direct **SNMP** (the default source) and ICMP ping out of the box.

#### Optional: Telegram alerting

1. Create a bot with **@BotFather** and put its token in `.env`
   (`TELEGRAM_BOT_TOKEN=...`). With no token, alerting still runs but delivery
   is a no-op.
2. Choose how the bot receives commands:
   * **Webhook** — set `TELEGRAM_WEBHOOK_SECRET` (e.g. `openssl rand -hex 16`)
     and register it with Telegram:
     `https://api.telegram.org/bot<token>/setWebhook?url=https://<host>/api/v1/telegram/webhook/<secret>`
   * **Long-polling** — no public URL needed; run the worker:
     `docker compose --profile telegram up -d telegram-poller`
3. Message the bot `/start`; it replies with your Telegram ID. An admin enables
   it: `PATCH /api/v1/telegram/users/{id}` with `{"is_active": true}`.
4. Register a delivery chat: `POST /api/v1/telegram/chats`
   `{"chat_id": <id>, "chat_type": "group", "min_severity": "warning"}`.
5. Create rules (`POST /api/v1/alerts/rules`) and trigger evaluation
   (`POST /api/v1/alerts/evaluate`, e.g. from cron after each poll). Firing
   alerts are delivered with an **Acknowledge** button; recoveries notify when
   the condition clears.

### Option B — Local development (without Docker)

Prerequisites: Python 3.12 and a reachable PostgreSQL instance.

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

cp ../.env.example ../.env          # set SECRET_KEY, POSTGRES_SERVER=localhost
export $(grep -v '^#' ../.env | xargs)   # or use a dotenv loader

alembic upgrade head                 # apply migrations
uvicorn app.main:app --reload        # serve on http://localhost:8000
```

### Get a token

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin@example.com&password=<FIRST_ADMIN_PASSWORD>"
```

Use the returned `access_token` as `Authorization: Bearer <token>` on protected
endpoints.

---

## 6. Running Tests & Quality Checks

```bash
cd backend
pip install -r requirements-dev.txt

pytest            # unit tests (no database or network required)
ruff check .      # lint
mypy app          # static type checks
```

The unit tests cover:
* **Auth/users (Phase 1):** password hashing, JWT creation/verification,
  user-service rules (uniqueness, role/password updates, admin bootstrap), and
  the login flow (username/email, inactive accounts, refresh rotation, and
  rejecting an access token at the refresh endpoint).
* **Inventory (Phase 2):** device create/update/delete, name-uniqueness
  conflicts, category filtering.
* **Monitoring (Phase 2):** poll orchestration and persistence, SNMP-vs-Zabbix
  source selection, the "Zabbix requested but unconfigured" error, graceful
  degradation when a collector fails, and the ping output parser.
* **Alerting (Phase 3):** evaluator logic for every alert type (offline, CPU,
  memory, packet loss, two-snapshot interface utilization, inert disk, default
  thresholds); service firing/**dedup**/**recovery**/**ack** and severity
  routing; alerts REST API + RBAC.
* **Telegram (Phase 3):** command replies and authorization, the update
  dispatcher (auto-register, enable, callback ack), the client's retry/backoff
  on `429`/`5xx`/network, the rate limiter (fake clock), HTML formatting, and
  the secret-gated webhook.

Repositories, collectors and the Telegram sender are swapped for
in-memory/preset fakes, so the whole **112-test** suite runs without Postgres,
an SNMP agent, a Zabbix server, or the Telegram network.

---

## 7. Key Design Decisions

1. **Layered / clean architecture.** API → Service → Repository → DB. Business
   logic never imports FastAPI or SQLAlchemy query APIs, so it stays portable
   and trivially testable.
2. **Dependency injection everywhere.** `app/core/dependencies.py` is the single
   composition root. Endpoints declare what they need (`UserSvc`, `AuthSvc`,
   `ActiveUser`, `require_roles(...)`) and never construct collaborators.
3. **Configuration via `pydantic-settings`.** All secrets come from environment
   variables and are validated at startup, so misconfiguration fails fast.
   `SECRET_KEY` has no insecure default in production usage.
4. **Async all the way down.** SQLAlchemy 2.0 async engine + `asyncpg` for
   throughput; Alembic runs synchronously via `psycopg` to keep migrations
   simple.
5. **Unit-of-work session.** `get_session` commits on success and rolls back on
   error, so endpoints/services don't manage transactions by hand.
6. **Stateless JWT auth with typed tokens.** Separate `access`/`refresh` token
   types prevent a refresh token being used as an access token (and vice-versa);
   roles are embedded as a claim for fast authorization.
7. **bcrypt password hashing** via `passlib` — adaptive, salted, industry
   standard.
8. **UUID primary keys** to avoid enumerable integer IDs and ease future
   multi-service / sharding scenarios.
9. **Repository pattern** lets the unit tests swap a real DB for an in-memory
   fake, keeping the suite fast and hermetic.
10. **App factory + lifespan bootstrap** so the platform is reachable
    immediately after a clean deploy (no manual first-user step).

### Phase 2 additions

11. **Pluggable collectors behind `Protocol`s.** Ping, SNMP and Zabbix
    collectors share interfaces (`PingCollector`, `MetricCollector`), so the
    monitoring service treats SNMP and Zabbix interchangeably and tests inject
    fakes. No collector knows about HTTP or the database.
12. **Lazy third-party imports.** `puresnmp` and `httpx` are imported *inside*
    collector methods, so importing the app (and the test suite) never requires
    the heavy/optional clients — only an actual poll does.
13. **Graceful degradation.** A failed metric collection still records a
    snapshot with reachability and null gauges, so a flapping device never
    breaks a poll cycle (`poll_all_active` also isolates per-device failures).
14. **Snapshot-per-poll time series.** `device_metrics` + `interface_stats`
    store history (not just "latest"), enabling future dashboards/trends without
    a schema change. Indexed on `device_id` and `collected_at`.
15. **Secret hygiene for devices.** The SNMP community is writable but excluded
    from API responses, matching how `hashed_password` is never serialized.
16. **OS `ping` over raw sockets.** Reachability uses the system `ping` binary
    (granted `cap_net_raw` in the image) so the app needs no root and no extra
    Python ICMP stack.
17. **Optional Zabbix via compose profile.** The Zabbix stack is opt-in
    (`--profile monitoring`); the platform is fully functional with SNMP alone.

### Phase 3 additions

18. **Pure evaluation core.** `AlertEvaluator` has no I/O, so every alert
    type's threshold/condition logic is exhaustively unit-tested; `AlertingService`
    handles persistence, dedup, recovery and routing around it.
19. **Idempotent alert lifecycle.** One open alert per device+type (dedup),
    automatic **recovery** on clear, and acknowledgement — so a persistent
    condition notifies once, not on every evaluation.
20. **One dispatcher, two transports.** Webhook and long-poller share a single
    `TelegramUpdateDispatcher`, so command/ack behaviour is identical and tested
    once. Long-polling is an opt-in compose profile.
21. **Resilient delivery.** The client enforces global + per-chat **rate limits**
    and **retries** on `429` (honouring `retry_after`), `5xx`, and network errors
    with exponential backoff; clock/sleep/HTTP are injectable for deterministic
    tests.
22. **Allowlist on top of the token.** Unknown Telegram users auto-register as
    *inactive*; an admin enables them, so a leaked bot link can't run commands or
    acknowledge alerts.
23. **Non-invasive integration.** Phase 3 reads Phase 2 metrics via the existing
    repositories and exposes `evaluate` endpoints rather than modifying the
    monitoring service — the poll path is untouched.
24. **Honest metric coverage.** CPU/memory/packet-loss/offline map to single
    snapshots; interface utilization is derived from two snapshots; disk is a
    defined type left inert (no disk metric is collected yet) rather than faked.

---

## 8. Next Steps

Phase 3 is complete. **Awaiting approval before starting Phase 4** (Configuration
Backup with Netmiko/Paramiko/NAPALM). Deferred follow-ups (until requested):
a scheduler to run polling + evaluation automatically, per-rule flap dampening
(consecutive breaches), disk metric collection, and per-chat/per-rule routing.
