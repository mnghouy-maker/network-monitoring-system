# Network Operations Platform

A self-hosted Network Operations Platform (NetOps). This repository is being
built **one phase at a time**.

> **Status: Phase 1 — Project Foundation ✅**
> FastAPI backend, PostgreSQL integration, SQLAlchemy models, Alembic
> migrations, and JWT authentication with role-based access control
> (Admin / Operator / Viewer).

Planned capabilities (future phases): Network Monitoring (Zabbix + SNMP),
Telegram Alert Bot, Configuration Backup (Netmiko/Paramiko/NAPALM), Server
Health Monitoring, an AI Troubleshooting Assistant, and a React/Tailwind
dashboard.

---

## 1. Architecture

Phase 1 establishes a **clean, layered architecture** with strict separation of
concerns. Each layer depends only on the layer beneath it, and all collaborators
are wired through FastAPI's dependency-injection system.

```
                         ┌──────────────────────────────┐
   HTTP client  ──────▶  │           FastAPI app         │
   (Swagger / React /    │      app/main.py + CORS       │
    curl / Telegram)     └───────────────┬───────────────┘
                                          │
                         ┌────────────────▼────────────────┐
                         │        API layer (routers)        │   app/api/v1
                         │  auth · users · health/ready      │
                         └────────────────┬──────────────────┘
                                          │  Depends(...)  (DI)
                         ┌────────────────▼──────────────────┐
                         │     Service layer (business logic) │   app/services
                         │  AuthService · UserService         │
                         └────────────────┬──────────────────┘
                                          │
                         ┌────────────────▼──────────────────┐
                         │   Repository layer (data access)   │   app/repositories
                         │  UserRepository (SQLAlchemy)       │
                         └────────────────┬──────────────────┘
                                          │  async session (unit of work)
                         ┌────────────────▼──────────────────┐
                         │           PostgreSQL 16            │
                         └────────────────────────────────────┘

   Cross-cutting:  app/core  →  config (env vars) · security (JWT/bcrypt) · DI
   Migrations:     alembic/  →  schema versioning
```

**Why this shape?**

| Layer | Responsibility | Benefit |
|-------|----------------|---------|
| **API** | HTTP concerns, status codes, serialization | Thin controllers, easy to read |
| **Service** | Business rules, orchestration | Framework-agnostic, unit-testable |
| **Repository** | All DB queries | Swappable persistence, mockable |
| **Core** | Config, security, DI wiring | Single source of truth for secrets |

This boundary is what lets the unit tests run **without a database** — services
talk to a `UserRepository` interface, which the tests replace with an in-memory
fake.

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
    │       └── 0001_create_users_table.py
    ├── app/
    │   ├── main.py             # app factory, lifespan, admin bootstrap
    │   ├── core/
    │   │   ├── config.py       # pydantic-settings (env vars)
    │   │   ├── security.py     # bcrypt + JWT
    │   │   └── dependencies.py # DI: sessions, services, auth guards
    │   ├── db/
    │   │   ├── base.py         # DeclarativeBase + TimestampMixin
    │   │   └── session.py      # async engine + unit-of-work session
    │   ├── models/
    │   │   └── user.py         # User model + UserRole enum
    │   ├── schemas/
    │   │   ├── user.py         # request/response contracts
    │   │   └── token.py
    │   ├── repositories/
    │   │   └── user.py
    │   ├── services/
    │   │   ├── auth.py
    │   │   ├── user.py
    │   │   └── exceptions.py   # framework-agnostic domain errors
    │   └── api/
    │       └── v1/
    │           ├── router.py
    │           └── endpoints/
    │               ├── auth.py    # /login /refresh /me
    │               ├── users.py   # admin-only CRUD
    │               └── health.py  # /health /ready
    └── tests/
        ├── conftest.py            # in-memory fake repository
        ├── test_security.py
        ├── test_user_service.py
        └── test_auth_service.py
```

---

## 3. Database Schema

Phase 1 contains a single table: **`users`**.

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

---

## 4. API Endpoints (Phase 1)

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

pytest            # unit tests (no database required)
ruff check .      # lint
mypy app          # static type checks
```

The unit tests cover password hashing, JWT creation/verification, user-service
business rules (uniqueness, role/password updates, admin bootstrap), and the
authentication flow (login by username/email, inactive accounts, token refresh,
and rejecting an access token at the refresh endpoint).

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

---

## 8. Next Steps

Phase 1 is complete. **Awaiting approval before starting Phase 2** (Network
Monitoring with Zabbix + SNMP).
