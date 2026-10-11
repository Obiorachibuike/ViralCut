#!/usr/bin/env bash
# Development launcher for the Python FastAPI media backend.
set -euo pipefail
cd "$(dirname "$0")/../apps/api"
if [ -f .venv/bin/activate ]; then
  source .venv/bin/activate
fi
exec uvicorn app.main:app --host 0.0.0.0 --port "${FASTAPI_PORT:-8000}" --reload
