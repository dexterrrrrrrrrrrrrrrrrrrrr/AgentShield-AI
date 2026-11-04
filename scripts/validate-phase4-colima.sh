#!/usr/bin/env bash
set -euo pipefail
# Trusted local setup only; Python test programs run solely via the Docker SDK.
root_dir="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$root_dir"
command -v docker >/dev/null || { echo 'Install Docker CLI: brew install docker colima' >&2; exit 2; }
command -v python3.12 >/dev/null || { echo 'Install Python 3.12: brew install python@3.12' >&2; exit 2; }
context="${COLIMA_CONTEXT:-colima}"
endpoint="$(docker context inspect "$context" --format '{{.Endpoints.docker.Host}}')"
case "$endpoint" in unix:///*) ;; *) echo 'Refusing a non-local Docker endpoint' >&2; exit 2;; esac
if [ ! -x backend/.venv/bin/python ]; then python3.12 -m venv backend/.venv; fi
backend/.venv/bin/python -m pip install -r backend/requirements-dev.txt
cd backend
.venv/bin/python -m scripts.validate_sandbox --docker-url "$endpoint" --report-dir "$root_dir"
