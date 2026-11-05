# AgentShield AI

A security-first AI agent playground with authenticated conversations, permission-checked tools, human approvals, isolated Python execution, live monitoring, and signed security audit history. Next.js/TypeScript/Tailwind, FastAPI/Python 3.12, MongoDB 7/PyMongo Async, LangGraph, Docker/Colima, and optional Groq/Ollama provide the existing architecture. No paid service, Redis, Celery, or hosted authentication/database is required.

The dashboard, Playground, Sandbox, Monitoring, Profile, and Settings use actual API state. New conversations select the server-enabled provider/model and a tool allowlist. Pending Python requests wait for an owner decision; **Continue after decision** finalizes the original turn from the stored result without running code again. Missing providers and unavailable sandbox runtimes report errors rather than produce fake responses.

Read [Phase 7 audit](docs/phase7-audit.md), [architecture](docs/architecture.md), [deployment](docs/deployment.md), [security](docs/security.md), [testing](docs/testing.md), and [Phase 7 validation report](docs/phase7.md).

## Choose a local launch mode

| Mode | Available functionality | Sandbox / Ollama |
| --- | --- | --- |
| Full native-host development | All application flows; frontend/API on the host, MongoDB 7 local or in Colima | Optional real sandbox after Colima validation; optional native loopback Ollama |
| Docker Compose | Non-root frontend/backend, authenticated MongoDB 7, chat through configured Groq, monitoring/audit/approvals API | Sandbox is explicitly disabled; no Docker socket in backend. Native Ollama is not made reachable by relaxing SSRF rules. |

Compose is a local deployment with explicit HTTP development cookies. Public production deployment additionally requires HTTPS/WSS, Secure production cookies, private database networking/credentials, trusted proxy/Host/origin configuration, backups, and operator hardening. It is not certified malicious multi-tenant isolation.

## Fast local Compose launch

Requirements: Git, Python3, Docker Engine/Compose; on Apple Silicon use free Colima. Allow time/disk space for dependency/image builds; on an 8 GB Mac use one backend worker and close large local models while building.

From the repository root:

```sh
python3 scripts/init-compose-env.py
docker compose --env-file .env.compose up --build -d --wait
```

The helper creates fresh generated keys/passwords in an ignored 0600 file and refuses to overwrite an existing one. It does not alter `backend/.env` or previous keys. Visit `http://localhost:3000`, register, and sign in. Add a free-tier `GROQ_API_KEY` securely to `.env.compose` and recreate the backend if desired. No model request occurs until you submit a task or continue an approved turn.

```sh
docker compose --env-file .env.compose ps
docker compose --env-file .env.compose down
```

Do not use `down -v` unless intentionally deleting that stack's data. The `agentshield-ai-v7` default project and MongoDB 7 volume are **new**: never attach an old MongoDB 8 volume or downgrade its data files. Existing MongoDB 8 data is left untouched. Compose exposes only the loopback frontend; backend/MongoDB ports remain internal. See [deployment details](docs/deployment.md) for optional native database access, HTTPS, credential lifecycle, backup/restore, health checks, and troubleshooting. Do not print/share resolved Compose configuration because it contains credentials.

## Full native-host setup (including optional sandbox)

Requirements: Node.js 24/npm, Python 3.12, MongoDB Community 7, and Colima/Docker for sandbox execution. Keep MongoDB on loopback. One MongoDB startup option is the native Homebrew package:

```sh
brew tap mongodb/brew
brew install mongodb-community@7.0
mkdir -p "$HOME/.local/share/agentshield/mongodb7"
"$(brew --prefix mongodb-community@7.0)/bin/mongod" --dbpath "$HOME/.local/share/agentshield/mongodb7" --bind_ip 127.0.0.1 --port 27017 --wiredTigerCacheSizeGB 0.25
```

Use a **new** MongoDB 7 data directory. Choose one database startup method; do not start native and container databases on the same port. If using the authenticated Compose MongoDB for native development, use the documented `compose.native.yaml` override and its app credentials instead; never expose it publicly.

From another terminal at the repository root:

```sh
python3.12 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements-dev.txt
```

Create native configuration **only for a fresh database and absent env file** (the exclusive write refuses to replace existing keys):

```sh
backend/.venv/bin/python - <<'PYENV'
import os, secrets
from pathlib import Path
text = Path(".env.example").read_text()
text = text.replace("JWT_SECRET=\n", "JWT_SECRET=" + secrets.token_urlsafe(48) + "\n")
text = text.replace("AUDIT_SIGNING_KEY=\n", "AUDIT_SIGNING_KEY=" + secrets.token_urlsafe(48) + "\n")
fd = os.open("backend/.env", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as target:
    target.write(text)
PYENV
```

For an existing database, retain its original JWT/audit keys and credentials. Never create replacement keys casually. Configure the database URI, `CORS_ORIGINS=http://localhost:3000` and `TRUSTED_HOSTS=localhost,127.0.0.1`. The app loads that file regardless of working directory. Do not replace existing keys: changing the effective audit key invalidates signatures. See [key migration guidance](docs/security.md).

```sh
bash scripts/run-backend.sh
```

In another terminal:

```sh
cd frontend
npm ci
npm run dev
```

The frontend proxies HTTP and WebSocket requests under `/api` to the backend. `API_INTERNAL_URL` is server-only and defaults to `http://127.0.0.1:8000`. Production build rewrites bind this target at build time; rebuild after changing it. Never put keys in `NEXT_PUBLIC_*`, browser storage, source, or chat.

### Providers

Groq is optional and primary. Set a free-tier `GROQ_API_KEY` on the backend; `GROQ_MODEL` defaults to `llama-3.1-8b-instant`. Model support/free quotas change; the app checks availability, handles failures, and never purchases credit or switches providers automatically. Keep billing disabled to maintain a zero-cost budget. Automated tests use explicitly identified mocks; they do not prove live inference.

Ollama is optional and disabled by default. On the native host, explicitly install/start it and choose a lightweight model suitable for 8 GB RAM, e.g. `qwen2.5:1.5b`. `ollama pull qwen2.5:1.5b` is an operator-initiated download, never an application action. Set `OLLAMA_ENABLED=true`, `OLLAMA_MODEL=qwen2.5:1.5b`, and the loopback URL. Its tool support must be checked locally; errors do not grant other capabilities. Prefer Groq when local memory is constrained.

### Real sandbox validation

The sandbox is disabled by default. Install Colima/Docker, use the Colima context, and run the unchanged operator validator:

```sh
bash scripts/validate-phase4-colima.sh
```

Do not enable submitted-code execution if readiness fails. Inspect the actual Docker context endpoint and set the native backend's `SANDBOX_DOCKER_URL` to that Unix socket; preserve the reviewed digest and all limits. Only after real checks pass set `SANDBOX_ENABLED=true` and retain `SANDBOX_POLICY=approval` for demonstrations. No socket is mounted into execution containers or the Compose public backend. Containers are not immunity against kernel/runtime escape vulnerabilities. See [sandbox details](docs/sandbox.md).

The user's earlier Colima 12/12 result is separate from cloud/CI evidence. Ten real-sandbox pytest cases remain opt-in; skipped cases are never counted as passes.

## User workflow

1. Register a full name/email/password confirmation; passwords require 12–128 characters and cannot be entirely whitespace. Sign in to obtain the HttpOnly session cookie.
2. Open Playground, choose an enabled provider/model and allowed tools, create/send a task, and restore saved conversation history.
3. Review tool events and failures. A sensitive Python tool request pauses the original turn; open its exact request in Sandbox/Monitoring.
4. Approve or reject as the owner. Authorization, fingerprint, expiry, quotas, and real readiness are rechecked; duplicate/foreign decisions fail.
5. Return to the original conversation and select **Continue after decision**. Resolution is single-use, uses the stored result, and has no tool permissions. A new tool task requires a new user turn.
6. Monitor live activity, signed security events, pending decisions, real stored analytics, and paginated audit history. Profile shows account/session information; Settings shows real provider/readiness configuration.
7. Sign out to revoke the session and stop private monitoring. Expired sessions require login again; database/network outages remain recoverable errors.

## Verification

With a credential-free **test** MongoDB 7 on loopback (never production credentials):

```sh
cd backend
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q --tb=short
.venv/bin/python -m pip check
```

```sh
cd frontend
npm run lint
npm run typecheck
npm run build
npx playwright install chromium
npm run test:e2e
```

Tests create unique disposable databases and ephemeral signing keys. The existing CI MongoDB 7/Ubuntu24.04 startup/readiness/diagnostics fix is retained. Browser tests build the production frontend and use real local MongoDB/WebSockets with explicit test-only model/container adapters. The normal app and production images never enable those fixtures. Use `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` for an installed browser and `BACKEND_PYTHON` for another Python path. Ports 3001/8001 must be free; rerun the normal frontend build after browser tests before `npm start`.

Additional reproducible checks:

```sh
backend/.venv/bin/python scripts/measure-local.py --mongodb-uri mongodb://127.0.0.1:27017
backend/.venv/bin/python scripts/validate-mongo-recovery.py
backend/.venv/bin/python scripts/smoke-compose.py --base-url http://localhost:3000
# Optional real browser against an isolated Compose stack (frontend npm ci + Chromium required):
COMPOSE_BASE_URL=http://localhost:3000 node scripts/browser-compose.mjs
```

See [testing.md](docs/testing.md) for database requirements, real versus mocked boundaries, dependency audits, isolated outage/recovery behavior, and exact sandbox commands. [phase7.md](docs/phase7.md) records measured results and unverified properties; no production-readiness claim is based on a skipped test.
