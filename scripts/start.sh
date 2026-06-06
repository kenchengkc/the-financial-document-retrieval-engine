#!/usr/bin/env sh
# Container start command: apply DB migrations, then launch the API.
# Honors $PORT (injected by Railway/Render/Fly); falls back to 8000 locally.
set -e

echo "[start] Running database migrations (alembic upgrade head)..."
alembic upgrade head

echo "[start] Launching API on port ${PORT:-8000}..."
exec uvicorn apps.api.app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
