# AgentShield AI

Phase 2 adds local MongoDB persistence and secure accounts to the existing Next.js dashboard and FastAPI API. All components are free. No hosted database or authentication provider is required.

## Requirements

- Node.js 24, npm, and Python 3.12
- MongoDB Community Edition 8.0
- macOS Apple Silicon is supported. Native MongoDB is recommended on an 8 GB MacBook to avoid a Docker VM's memory overhead.

## 1. Install and start local MongoDB

On macOS, install the official Community Edition formula:

```sh
brew tap mongodb/brew
brew install mongodb-community@8.0
mkdir -p "$HOME/.local/share/agentshield/mongodb"
mongod --dbpath "$HOME/.local/share/agentshield/mongodb" --bind_ip 127.0.0.1 --port 27017 --wiredTigerCacheSizeGB 0.25
```

Keep that terminal running; Ctrl-C shuts MongoDB down gracefully. Do not also start a Homebrew MongoDB service on the same port. The 256 MB WiredTiger cache leaves memory for the application. Verify from another terminal:

```sh
mongosh mongodb://127.0.0.1:27017 --quiet --eval 'db.runCommand({ping:1})'
```

Alternatively, if Docker is already available, run `docker compose up -d mongo` from the repository root. The included service publishes only loopback, has a 512 MB memory cap, and retains data in a named volume. Stop it with `docker compose stop mongo`. Do not use `down -v` unless you intend to erase its database. Choose one MongoDB startup method.

Local MongoDB has no database password and must stay bound to loopback. For remote deployments use MongoDB authentication, TLS, private networking, and a credential-bearing URI stored securely outside Git.

## 2. Configure and start the backend

From the repository root:

```sh
python -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements-dev.txt
cp .env.example backend/.env
backend/.venv/bin/python - <<'PYGEN'
from pathlib import Path
import secrets
p = Path("backend/.env")
p.write_text(p.read_text().replace("JWT_SECRET=\n", "JWT_SECRET=" + secrets.token_urlsafe(48) + "\n"))
p.chmod(0o600)
PYGEN
cd backend
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

Do not overwrite an existing populated `.env`; preserve its signing key and settings. `pydantic-settings` loads `backend/.env` regardless of the command's working directory. Process environment variables override the file. Startup requires a valid signing key, MongoDB ping, and successful index creation; it fails closed otherwise. Ctrl-C closes the async MongoDB client gracefully.

Database defaults to `agentshield_ai`. Only `users`, `sessions`, and `security_events` are initialized. The latter contains expiring authentication rate counters, not a monitoring system. `agent_configs` and `execution_logs` are reserved for future phases.

## 3. Start the frontend

In another terminal:

```sh
cd frontend
npm ci
npm run dev
```

Open the frontend on port 3000. The server proxies browser requests under `/api` to FastAPI, keeping auth cookies on the same origin. Health status also uses this proxy by default. Optional `frontend/.env.local` settings:

```dotenv
API_INTERNAL_URL=http://127.0.0.1:8000
# Optional browser-reachable health API override, never a credential:
NEXT_PUBLIC_API_URL=
```

`API_INTERNAL_URL` is server-only. Set it before building; Next.js rewrites are generated at build time. If the frontend port or public origin changes, set the backend's `CORS_ORIGINS` to that exact origin. Do not mix `localhost` and `127.0.0.1` in the browser. The default configuration needs no frontend env file.

For a production frontend, use `npm run build` followed by `npm start`. Production deployments must use HTTPS and backend `APP_ENV=production` with HTTPS `CORS_ORIGINS`. That enables Secure, host-only `__Host-` cookies. Keep the backend behind the same-origin frontend/reverse proxy. These development commands are not an Internet deployment configuration.

## Account workflow

1. Visit `/register`; enter full name, email, password, and confirmation. Passwords must be 12–128 characters and cannot consist only of whitespace. Long, unique passphrases are recommended.
2. Registration normalizes email case and whitespace and stores only an Argon2id hash. It does not automatically authenticate you.
3. Sign in at `/login`. Success opens the protected dashboard. Invalid passwords and unknown users return the same error.
4. Open Profile to view full name, email, creation date (UTC), and authentication status.
5. Sign out to revoke that session immediately. Other sessions remain valid. Sessions expire after 15 minutes by default; sign in again. There are no refresh tokens or localStorage tokens.

The original sidebar sections, overview, API health/retry behavior, and responsive layout are retained. Agent Playground, Sandbox, Execution Logs, Security Monitoring, and Settings remain placeholders. There is no AI agent or command execution functionality.

## API

| Method | Endpoint             | Purpose                                                           |
| ------ | -------------------- | ----------------------------------------------------------------- |
| GET    | `/health`            | Public liveness and version                                       |
| GET    | `/ready`             | Live database readiness (503 on failure)                          |
| GET    | `/api/auth/csrf`     | Issue a signed, session-bound CSRF token and HttpOnly CSRF cookie |
| POST   | `/api/auth/register` | Validate and register an account                                  |
| POST   | `/api/auth/login`    | Create a tracked session and set HttpOnly JWT cookie              |
| GET    | `/api/auth/me`       | Return the authenticated user's safe profile                      |
| POST   | `/api/auth/logout`   | Revoke the current session and clear cookies                      |

State-changing auth requests require an allowed `Origin`, the CSRF cookie, and the token from `/api/auth/csrf` in `X-CSRF-Token`. Fetch a new token after login. The frontend does this automatically. Auth responses use `Cache-Control: no-store`. API documentation is at backend `/docs`.

## Tests and dependency audits

Tests require a live **credential-free local MongoDB**, never production credentials. They create unique `agentshield_test_*` or `agentshield_e2e_*` databases and remove them after each completed run. They fail if MongoDB is unavailable; there is no mock fallback. A forcibly interrupted run may leave a disposable test database. Both normal and browser tests refuse remote/credential-bearing test URIs.

```sh
cd backend
.venv/bin/python -m pip check
.venv/bin/python -m pytest -q
.venv/bin/python -m pip install pip-audit==2.10.1
.venv/bin/python -m pip_audit -r requirements-dev.txt
```

```sh
cd frontend
npm run lint
npm run typecheck
npm run build
npm audit --audit-level=moderate
npx playwright install chromium
npm run test:e2e
```

The Playwright configuration builds and starts the production frontend on 3001 and a test backend on 8001, generates an ephemeral signing key, and shuts down both processes. It uses one browser worker to keep memory modest. If Chromium is already installed, set `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` to its executable path instead of downloading another browser. Set `BACKEND_PYTHON` if your backend Python executable differs from `../backend/.venv/bin/python`. `TEST_MONGODB_URI` may select another credential-free loopback MongoDB port. Browser-test ports 3001 and 8001 must be free. The browser test build points to its test API on 8001; run `npm run build` again before using `npm start` for normal development on API port 8000.

Backend tests cover registration, duplicate races, input validation, password hashing, generic login errors, JWT claims/signatures/expiration, session expiration and ownership, logout revocation, cross-user isolation, rate limits, CSRF, body limits, indexes, secure production cookies, and database failures. Browser tests cover account forms, password visibility, route protection, profile, logout, separate users, API errors, and Phase 1 dashboard regressions. GitHub Actions runs both suites with MongoDB services and dependency audits.

## Security and resource decisions

See [architecture and security](docs/architecture.md). The backend remains the authorization boundary; frontend redirects are an additional UI safeguard. Email syntax is validated, but email ownership verification, password reset, MFA, refresh tokens, and production deployment are outside Phase 2. No paid services, Redis, Celery, heavy monitoring, or AI integrations are introduced. Phase 3 requires approval.
