# Phase 5: monitoring, approvals, and analytics

Phase 6 preserves this protocol and adds shared connection leases, signed event verification, and additional authorization checks. See [phase6.md](phase6.md) for the current security controls and legacy audit handling; its shared connection limits supersede the per-process-only admission described below.

Phase 5 adds a user-scoped live monitor at `/monitoring`. Execution Logs and Security Monitoring in the dashboard both open it. It displays active conversations, execution counts, tool activity, security decisions, pending approvals, approval history, and completion durations. Counts come from MongoDB; an empty account shows zeros. Phase 6 is outside this implementation.

## Architecture

LangGraph model/tool nodes emit observable **status** events through an asynchronous callback while the turn is running. The agent API emits start and terminal events, and the existing sandbox service emits policy, approval, and container lifecycle events. No private reasoning is collected. The sandbox manager, cgroup verification, resource limits, and deterministic policy remain the execution boundary.

A small `Monitor` service atomically appends each event and allocates a per-user increasing sequence in MongoDB. A single document retains the latest 200 events for that user. Each event also gets a seven-day security audit record. Each open WebSocket reads only its authenticated user's feed, by default once per second. This supports separate backend processes without Redis, Celery, a hosted broker, or an always-running worker. No database polling runs when there are no monitoring connections. Delivery latency is normally about one polling interval, plus database/network time; this is status streaming, not model token streaming.

The frontend combines REST snapshots with the live feed. Snapshot refreshes are coalesced to at most one every five seconds from activity; heartbeats also refresh pending approval expiry. It keeps 100 recent events in browser memory and at most 200 loaded approval items. The active duration updates on snapshots/heartbeats. Closed views release sockets and timers. Multiple browser tabs consume separate connections; one backend process is recommended on an 8 GB Mac.

## WebSocket protocol

Connect to the **same origin** at `/api/monitor/ws?after=0` using the existing session cookie. `after` is an optional last-received per-user sequence (a nonnegative JavaScript-safe integer). Never put a JWT or CSRF token in the URL.

Server frames:

```json
{"type":"connected","protocol":1}
{"type":"event","event":{"id":"<32-hex>","seq":42,"user_id":"<32-hex>","agent_id":"<32-hex or null>","execution_id":"<32-hex or null>","timestamp":"<UTC ISO-8601>","kind":"tool_approved","category":"security","severity":"info","action":"tool_approved","tool":"python_sandbox","policy_decision":"ALLOW","execution_result":"queued","duration":null}}
{"type":"heartbeat","cursor":42}
{"type":"resync_required"}
```

The example frames are a protocol illustration, not production analytics. `agent_id` identifies the conversation. `execution_id` identifies an agent turn or a sandbox execution, depending on event kind; manual sandbox requests have a null agent ID. `duration`, when present, is seconds.

Supported event kinds:

- `agent_started`, `agent_status`, `agent_completed`, `agent_failed`
- `tool_requested`, `tool_completed`, `policy_evaluation`, `tool_rejected`
- `approval_required`, `tool_approved`
- `sandbox_started`, `sandbox_completed`, `sandbox_failed`

`agent_status` means the model operation is underway. It never contains model thoughts. Policy decisions are `ALLOW`, `DENY`, or `REQUIRE_APPROVAL`. Severity is `info` or `warning`; category is `execution` or `security`. Tool names and execution results are fixed server vocabularies. Unrecognized tool names become `unknown`.

Reply to every heartbeat with exactly `{"type":"pong"}`. Heartbeats default to 15 seconds; missing pongs close the connection after 35 seconds. Only pong input is accepted, at most one per second and 256 text characters; decisions use REST. Configure the Uvicorn transport limits below to cap frames before application parsing.

Reconnect with exponential backoff (0.5 seconds up to 30 seconds plus jitter) and the last received sequence. Events are ordered within a user's stream and delivered in batches of at most 50. Clients must deduplicate by ID/sequence. A cursor outside the retained window receives `resync_required`, then the retained feed; refresh the REST snapshots because missing events cannot be reconstructed from the replay window. Reloads start at zero and REST loads recent audit records. Reconnection is not an exactly-once delivery guarantee.

Close codes: `4401` authentication expired/revoked; `4403` disallowed/missing Origin; `1008` malformed input/cursor or missing heartbeat; `1013` capacity, slow client, database interruption, or temporary service failure. Pre-upgrade rejections may appear as HTTP 403 in a browser. The UI stops automatic retries for post-upgrade authentication/origin failures and displays connection status. Sign in again after the existing 15-minute session expiry.

## Authentication, authorization, and data minimization

- Handshakes require an exact configured `CORS_ORIGINS` Origin and the existing verified JWT HttpOnly cookie plus a live server-side session. The cookie remains SameSite Lax, Secure in production HTTPS, and never enters localStorage. A cross-origin attacker cannot open an authorized monitoring stream.
- Authentication and revocation are checked again before each batch; logout closes an existing connection on its next poll. Database failure closes delivery safely.
- Every feed, audit, summary, history, and approval query includes the authenticated user ID. Clients cannot select another owner. Handshakes are limited to 60 per authenticated user per existing rate window (five minutes by default), with shared MongoDB counters. Admission is four connections per user and twenty total **per backend process**. Use a reverse proxy for deployment-wide connection/handshake controls if scaling beyond local use.
- Slow send operations time out after three seconds; sender and receiver tasks are cancelled and awaited on disconnect. Mongo feed size, batches, browser state, transport queue, and connection admission are bounded. There is no unbounded event queue.
- All three monitoring REST reads share a 360-request/user window (300 seconds by default). Approval/rejection retains the existing lower sandbox rate limit and quota. REST state changes retain authentication, exact Origin, signed session-bound CSRF, request/body validation, and no-store responses.
- Monitoring accepts only validated identifiers, enums, timestamps, and bounded durations. It never receives code, prompts, user messages, tool arguments/results, system instructions, provider exceptions, API keys, or credentials. Metadata minimization is stronger than trying to redact arbitrary event payloads. Existing conversation/sandbox redaction and output limits still apply.
- The monitor page fetches exact code only through the existing owner-authorized sandbox detail API when **Review request** is selected. Code is plain text, never HTML. Do not submit confidential content. Monitoring metadata is private account data and should be protected in database backups too.

## Approval workflow

1. A sandbox request passes the unchanged independent policy/readiness checks. `REQUIRE_APPROVAL` creates the existing immutable, expiring approval and emits a notification.
2. Open **Review request** to inspect the exact code, agent/execution IDs, resource limits, and SHA-256 request fingerprint.
3. **Approve exact request** calls the existing approval endpoint. It revalidates owner, pending state, expiry, code/policy fingerprint, session ownership, and sandbox readiness, then atomically consumes the request before execution.
4. **Reject request** atomically claims the same owner/hash/pending/expiry conditions, removes the stored code, marks the execution rejected, and never invokes Docker.
5. Concurrent approve/reject or duplicate decisions have one winner; others return 409. Another user's decision cannot claim the request. Decisions and execution status appear in the live timeline and history. Expiry never grants permission.

Approval notifications do not automatically resume a completed agent turn. An approved sandbox execution finishes through the existing sandbox manager; its result appears in sandbox history, and the user may send another agent turn. Docker unavailability remains `SANDBOX_UNAVAILABLE`; authentication, safe tools, and monitoring remain usable. No monitoring setting enables or relaxes the sandbox.

## MongoDB collections and analytics scope

- New `monitor_streams`: `_id`/`user_id`, sequence, last 200 sanitized events, `updated_at`. Unique owner index. The bounded feed is retained until account/database removal; it has no TTL to avoid sequence reset/replay ambiguity.
- Existing `security_events`: records with `kind=monitor_event`, owner, nested event, and `expires_at`. The existing TTL index expires these after seven days (MongoDB TTL deletion is asynchronous). An owner/kind/sequence index supports history. Existing rate-limit counters share the collection but are excluded from monitoring queries.
- Existing `agent_sessions` and `agent_messages`: active leases, start time, turn status, and terminal duration. An owner/status/lease index supports active views.
- Existing `execution_logs`: actual sandbox outcomes plus `approval_status`, `approval_expires_at`, and `decision_at`; owner/approval/decision index for history.
- Existing `sandbox_approvals`: immutable pending requests; owner/state/expiry index for pending views. Existing TTL removes expired approval payloads.

Agent totals are counts of currently stored turns (including running turns), successful is `completed`, and failed is `failed` plus `interrupted`. Clearing a conversation removes its turns and changes those totals. Sandbox counts include all current execution-log statuses, including denied/unavailable/pending requests; they are **requests**, not a claim of completed Docker executions. Approval pending counts exclude expiry immediately; expired counts derive from still-stored pending execution logs. Approved/rejected history records begin with Phase 5 decisions; older records are not backfilled or fabricated. Sandbox logs retain the configured Phase 4 retention. Blocked tool counts derive from retained `tool_rejected` audit events. Statistics therefore have the scope shown in the UI, not all-time production metrics. Expired or missing records reduce counts.

Standalone MongoDB uses no multi-document transactions. The bounded feed append is atomic, but audit insertion and execution/approval metadata updates are separate writes. An interruption can leave a feed event without its audit row or a consumed approval with incomplete history. Replays preserve order of the committed feed, not distributed transaction semantics. Failures do not restore used approvals or bypass execution authorization; check execution history before retrying. There is no process-crash recovery worker, external durable broker, alert delivery, or indefinite audit archive in this phase.

## API endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| WS | `/api/monitor/ws?after=0` | Authenticated, owner-scoped status feed |
| GET | `/api/monitor/summary` | Stored execution and approval statistics, active agents |
| GET | `/api/monitor/events?offset=0&limit=50` | Audit events, newest sequence first; max 100/page |
| GET | `/api/monitor/approvals?offset=0&limit=20` | Pending and decided history; max 50/page |
| GET | `/api/sandbox/executions/{id}` | Existing owner-authorized exact approval review |
| POST | `/api/sandbox/approvals/{id}` | Existing exact-request approval |
| POST | `/api/sandbox/approvals/{id}/reject` | Reject with `{"reject":true,"request_hash":"<64-hex>"}` |

Offsets are capped at 10,000. Monitoring writes have no public event-ingestion endpoint: model output cannot publish arbitrary metadata or change a policy.

## Local setup on an 8 GB Mac

Keep the existing `.env`, signing key, MongoDB, and Colima settings. Install updated backend dependencies; no new database service or paid account is required. From the repository root:

```sh
backend/.venv/bin/python -m pip install -r backend/requirements-dev.txt
cd backend
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers --ws websockets --ws-max-size 1024 --ws-max-queue 8
```

In another terminal:

```sh
cd frontend
npm ci
npm run dev
```

Use the same browser origin as `CORS_ORIGINS`, normally `http://localhost:3000`. Sign in and open `/monitoring`; run a Playground task in another tab. An optional sandbox request appears only if your existing sandbox configuration and real readiness check permit it. No API key is required to view monitoring, but real provider tasks require the existing Groq/Ollama configuration. Keep a single Uvicorn process; there is no extra monitoring worker or local model download.

The Next.js `/api` rewrite forwards HTTP and WebSocket upgrades to server-only `API_INTERNAL_URL`. If using another reverse proxy, forward WebSocket Upgrade/Connection headers and allow an idle timeout greater than the heartbeat interval; use HTTPS/WSS for production. Do not expose a Docker API or put keys into frontend variables. `websockets` is an explicit backend dependency so clean installs support upgrades.

Optional server settings (validated, defaults shown):

```dotenv
MONITOR_POLL_SECONDS=1
MONITOR_SEND_TIMEOUT=3
MONITOR_HEARTBEAT_SECONDS=15
MONITOR_PONG_SECONDS=35
```

Keep the pong timeout greater than the heartbeat interval plus the polling interval. These affect transport behavior only; no sandbox limits change.

## Testing and verification

A credential-free loopback MongoDB must be running. Tests create/drop isolated test databases; never use a production database URI.

```sh
cd backend
.venv/bin/python -m pip check
.venv/bin/python -m pytest -q
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

`pip-audit` installation and Chromium/system-browser selection follow the README. Browser tests start a production Next.js build and an explicitly test-only API on ports 3001/8001, with real WebSockets and real local MongoDB. They inject mocked Groq and sandbox providers, never execute submitted Python on the host, and exercise live events, persisted replay, analytics, approval review/rejection, cross-user isolation, error recovery, mobile layout, and previous auth/playground/sandbox behavior. Backend tests also cover Origin/cookie failures, revoked sessions, ordering/concurrent emission, replay gaps, connection admission, slow clients, missing heartbeat, malformed input, database failure, approval race/replay prevention, stored analytics, and status events before a provider response. Existing Phases 1–4 regressions remain included.

Real container isolation is a separate opt-in test. On the already validated Mac/Colima runtime, rerun from the repository root:

```sh
bash scripts/validate-phase4-colima.sh
```

Cloud mocked Docker tests are not evidence of real Docker isolation. This implementation does not revalidate your Mac remotely; Phase 4's user-reported 12/12 pass at `c9a6acd` remains a separate local result. No real Groq request or local Ollama inference is implied by mocked browser/provider tests. No Phase 6 functionality is implemented.
