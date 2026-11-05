#!/usr/bin/env bash
# Local launcher with bounded WebSocket frames/queues and HTTP connection admission.
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
python_exec="${AGENTSHIELD_PYTHON:-$repo_root/backend/.venv/bin/python}"
exec "$python_exec" -m uvicorn app.main:app --app-dir "$repo_root/backend" \
  --host 127.0.0.1 --port 8000 --no-proxy-headers \
  --ws websockets --ws-max-size 1024 --ws-max-queue 8 \
  --limit-concurrency 64 --timeout-keep-alive 5
