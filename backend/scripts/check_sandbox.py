"""Operator-only readiness CLI. Runs only the fixed trusted probe, never user code."""

import json

from app.config import Settings
from app.sandbox.manager import DockerAdapter

if __name__ == "__main__":
    result = DockerAdapter(Settings()).readiness()
    print(json.dumps(result))
    raise SystemExit(0 if result["ready"] else 2)
