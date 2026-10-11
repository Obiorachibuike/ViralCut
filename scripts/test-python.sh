#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../apps/api"
if [ -f .venv/bin/activate ]; then
  source .venv/bin/activate
fi
exec python3 -m pytest -q "$@"
