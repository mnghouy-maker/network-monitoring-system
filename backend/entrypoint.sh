#!/usr/bin/env bash
# Container entrypoint: wait for the database, apply migrations, then serve.
set -euo pipefail

echo "[entrypoint] Applying database migrations..."
# Alembic retries give Postgres time to accept connections on first boot.
for attempt in 1 2 3 4 5; do
    if alembic upgrade head; then
        break
    fi
    echo "[entrypoint] Migration attempt ${attempt} failed; retrying in 3s..."
    sleep 3
done

echo "[entrypoint] Starting API server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers
