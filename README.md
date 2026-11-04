# AgentShield AI

Phase 3 adds a LangGraph agent playground on top of local MongoDB persistence and secure accounts to the existing Next.js dashboard and FastAPI API. All components are free. No hosted database or authentication provider is required.

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

Database defaults to `agentshield_ai`. Authentication uses `users`, `sessions`, and `security_events` (expiring rate counters). Phase 3 also initializes `agent_sessions`, `agent_messages`, and `agent_configs`. Only `execution_logs` remains reserved for a future phase.

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

The original overview, API health/retry behavior, and responsive layout are retained. Agent Playground is now functional at `/playground`; Sandbox, Execution Logs, Security Monitoring, and Settings remain placeholders. There is no shell, generated-code execution, or Docker sandbox functionality.

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

See [architecture and security](docs/architecture.md). The backend remains the authorization boundary; frontend redirects are an additional UI safeguard. Email syntax is validated, but email ownership verification, password reset, MFA, refresh tokens, and production deployment are outside this phase. No paid services, Redis, Celery, heavy monitoring, or sandbox execution are introduced. Phase 4 requires approval.

## Phase 3: provider configuration

Add `GROQ_API_KEY` to the backend process environment or the ignored `backend/.env`, then restart the backend. Never paste a real key into source, chat, browser storage, frontend variables, screenshots, or test fixtures. Groq is the primary provider; no key is needed to start the application or run automated tests. In a restricted cloud environment, allow HTTPS to `api.groq.com` through environment settings. No environment is published automatically by this code.

`GROQ_MODEL` defaults to `llama-3.1-8b-instant`. Availability is checked using the official Groq SDK before each completion. Models change over time; configure an available Llama model with tool support in your Groq account. The playground offers only the server-configured model for each provider. The application does not select a paid provider, purchase credits, switch providers, or retry provider calls automatically. **Use a free-tier account without billing enabled** to maintain a ₹0 budget; model availability checks and completions consume provider quota. A free API is not unlimited. Authentication errors, unavailable models, timeouts, quota errors, and outages return safe, actionable errors.

### Optional local Ollama

Ollama is disabled by default. To opt in, install Ollama separately and explicitly download a small model such as `qwen2.5:1.5b` (roughly 1 GB quantized; allow additional runtime memory). Run `ollama serve` and, only if you choose to download it, `ollama pull qwen2.5:1.5b`. Then set `OLLAMA_ENABLED=true` and `OLLAMA_MODEL=qwen2.5:1.5b`. `OLLAMA_URL` must be a loopback HTTP origin (default port 11434). Never point it at a remote service. The app checks installed models but **never downloads models**. Model tool support is provider/model dependent; unsupported requests produce errors rather than unsafe fallbacks. No real Ollama runtime is required by tests.

For an 8 GB M2, prefer Groq to avoid local-model RAM usage. If using Ollama, run only one small model, keep the default 4096-token context, and close it when finished. The app requests a one-minute model keep-alive. Native macOS/M2 runtime performance must be evaluated locally; cloud validation runs on Linux.

## Agent lifecycle and tools

Open Agent Playground after login. Choose the provider/model, enter a task, and send it. A conversation locks its provider/model; choose **New conversation** to use another selection. Saved conversations reload from MongoDB, with paginated session lists. Up to 50 sessions per user and 50 turns per session are permitted. Clear conversation deletes the selected session and its messages. Retry is an explicit new turn and may consume provider quota.

LangGraph runs `START → model → permission-checked tools → model → END`. Observable events describe model requests, tool requests, tool responses, denials, completion, and failure. They are not private chain-of-thought, and raw provider reasoning fields/system prompts are never returned. Automatic LangSmith tracing is disabled for executions; no tracing account or hosted LangGraph service is used.

The registry allows only:

- `calculator`: AST-interpreted arithmetic (`+ - * /` and parentheses), finite numbers bounded to ±10¹²; no eval, function calls, exponentiation, or imports.
- `summarize_text`: local extractive summary, taking the first three sentences (not an extra LLM call).
- `format_json`: parse and pretty-print JSON; reject invalid JSON and non-finite constants.

Each tool accepts only a bounded `text` string. Session allowlists can restrict these tools but cannot add tools. Unknown/disallowed names or malformed inputs fail closed. All tool requests/responses are recorded as redacted workflow events. Future sandbox tools must enter through this registry and authorization interface; Phase 3 implements none.

Defaults: 4 model iterations, 3 tool calls, 15 seconds per provider operation and 45 seconds total execution, 4000 input characters, 1024 output tokens, and the most recent 6 completed turns (each context message clipped to 2000 characters). Two active executions per backend process are admitted; the database lease prevents concurrent turns/deletion within a running conversation. An expired lease can be recovered after 120 seconds. There are no background workers, Redis, Celery, or event-polling loops.

## Agent API and persistence

All `/api/agent` endpoints require the existing JWT/session authentication. Writes require the existing Origin and CSRF checks. Database queries always include the authenticated owner; foreign/missing sessions return the same 404.

| Method | Path                                                  | Purpose                                                     |
| ------ | ----------------------------------------------------- | ----------------------------------------------------------- |
| GET    | `/api/agent/providers`                                | Enabled provider/model metadata, no keys                    |
| POST   | `/api/agent/sessions`                                 | Create a conversation with provider/model/tool allowlist    |
| GET    | `/api/agent/sessions?offset=0&limit=20`               | Paginated owned sessions                                    |
| GET    | `/api/agent/sessions/{id}/messages?offset=0&limit=20` | Owned conversation history                                  |
| POST   | `/api/agent/sessions/{id}/messages`                   | Persist input, run the bounded graph, persist result/events |
| GET    | `/api/agent/sessions/{id}/events?offset=0&limit=20`   | Paginated execution statuses and events                     |
| DELETE | `/api/agent/sessions/{id}`                            | Clear/delete owned conversation (409 while running)         |

Collections: `agent_sessions` holds owner, provider/model, allowlist, UTC timestamps, execution lease/status, and turn count; `agent_messages` holds owned user/assistant turn pairs, status, timestamps, and events; `agent_configs` holds the owner's atomic session quota. Owner/time indexes and a unique owner/session/turn index support bounded queries. `execution_logs` remains deferred. No API keys, system prompts, or raw provider exception bodies are stored in conversation documents.

Agent requests are limited to 10 per user per 300-second rate window by default, using existing MongoDB counters; session creation has its own limit. Auth and agent request bodies are capped at 16 KiB. Known key patterns, configured Groq/JWT keys, and common credential assignments are redacted before persistence and in tool events. Redaction is best effort, not a data-loss-prevention guarantee: do not send confidential data. Groq receives the task, bounded conversation history, and necessary tool results. Tool/model outputs are untrusted plain text and are never rendered as HTML or executed. A malicious model can still produce incorrect or inappropriate text; this is not a complete prompt-injection defense.

Multi-document writes use standalone MongoDB without transactions. A database/process interruption can leave an incomplete turn or conservative quota count. The UI labels incomplete executions; retry creates a new turn. Failures never confer another user's access. Back up the local database and do not use this development configuration as a production deployment.

## Phase 3 validation

Run the backend and frontend commands above. Provider tests use the official Groq SDK with mocked HTTP responses; graph/API tests use injected providers and **real local MongoDB**. The test suite reuses a disposable database's collection files within one run and clears documents between tests, then drops the database at the end to avoid delayed WiredTiger file cleanup exhausting descriptors. Browser tests explicitly launch `scripts.browser_test_app:make_app` in an isolated test database; the normal `app.main:app` entry point never enables a fake provider. Browser tests cover a tool run, persisted/reloaded history, loading indicators, errors/retry, clearing, route protection, mobile layout, and auth regressions.

A real Groq smoke test is separate: after securely configuring a free-tier key and network access, sign in and send one short task with Groq in the playground. A mocked provider test is not evidence of a real Groq request. Ollama availability/model behavior must also be tested separately on a machine where it is installed. Phase 4 remains unimplemented and requires approval.
