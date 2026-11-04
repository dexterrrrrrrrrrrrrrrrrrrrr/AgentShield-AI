# Phase 3 architecture and security

## Request flow

The existing Next.js App Router/TypeScript/Tailwind dashboard remains. Browser auth requests use the same-origin `/api` proxy to FastAPI. Protected Next.js layouts forward only the session cookie to `/api/auth/me` with no caching and a five-second timeout. Missing or invalid sessions redirect to login; API outages show an unavailable page rather than protected content. The backend always validates authorization independently. Profile data comes only from the verified session, never a client-provided user ID.

## MongoDB

A single PyMongo `AsyncMongoClient` is created in FastAPI lifespan. Startup pings MongoDB and creates indexes, and failure prevents serving. Shutdown awaits client closure. The pool starts empty, permits at most 10 connections by default, retires idle connections after 30 seconds, and bounds connection, selection, queue, and socket waits. Runtime database failures return a generic 503 without URIs or credentials.

Database: `agentshield_ai` (test databases have unique, enforced test prefixes).

| Collection        | Fields and indexes                                                                                |
| ----------------- | ------------------------------------------------------------------------------------------------- |
| `users`           | Random UUID ID, normalized email, full name, Argon2id hash, UTC created date; unique email index  |
| `sessions`        | Cryptographically random ID, owner user ID, UTC creation/expiry; owner index and expiry TTL index |
| `security_events` | HMAC-pseudonymized fixed-window auth counters, category, count, expiry; TTL index                 |
| `agent_configs`   | Per-owner atomic session quota; unique owner index                                                |
| `execution_logs`  | Reserved name only; no collection, model, endpoint, or operations                                 |

TTL deletion is asynchronous, so authorization explicitly checks session expiry on every request. The unique email index resolves concurrent registration races. Email normalization intentionally case-folds the local part as an application identity policy. Request models forbid extra fields and bound string lengths; queries use validated scalar values, not client-supplied query documents.

## Passwords and tokens

Argon2id uses 19 MiB, two iterations, and parallelism one, with per-password salts. Two hashing slots and offloaded work keep CPU-bound operations off the async event loop and bound active hash memory. Unknown users still verify a dummy hash; invalid credentials return one generic response. Outdated password hashes are upgraded after successful login. Passwords and confirmation values are never returned, logged, or included in validation errors.

Access JWTs use HS256 with a required randomly generated secret of at least 32 bytes. Verification fixes the algorithm and requires issuer, audience, subject, session ID, issue time, not-before time, expiration, and an access-token purpose. Default lifetime is 15 minutes, maximum 30. No token is returned in JSON or stored in localStorage. Session records store no JWTs. JWT subject and session owner must match; a deleted/expired session or missing user rejects even a cryptographically valid token. Logout deletes only the current user's current session, immediately revoking captured copies.

## Cookies and CSRF

JWT cookies are HttpOnly, host-only, SameSite=Lax, and scoped to `/`. Production mode requires HTTPS origins and sets Secure with the `__Host-` prefix (no Domain attribute). HTTP cookies are allowed only by the explicit development/test mode. CSRF cookies are HttpOnly too; JavaScript receives the CSRF token from a same-origin JSON endpoint and retains it only for the request.

All state-changing auth endpoints, including login and registration, require an exact allowed Origin and matching cookie/header CSRF token. The token is signed, expires after 30 minutes, uses a separate JWT audience/purpose, and is bound to the access token's session ID (or the anonymous state before login). Login clears the anonymous CSRF cookie. A signed token copied from another session fails. CORS uses exact origins and credentials, never a wildcard. Origin checking remains independent of CORS.

Auth responses are not cached. The API limits actual POST body size to 16 KiB even for chunked requests and returns sanitized errors. Frontend/API headers prevent framing and MIME sniffing; React escapes profile strings. There are no user-controlled redirects, execution routes, or future data APIs.

## Rate limits and resources

Atomic MongoDB counters survive backend restarts and work across workers. Defaults: 5 login attempts per normalized email and 30 per peer IP in 300 seconds, plus 10 registrations per IP per 300 seconds. Counters use HMAC identifiers rather than raw emails/IPs and expire automatically. Fixed windows can permit a burst across a boundary; this is not distributed DDoS protection. All attempts count, including successful ones, with a Retry-After response when blocked.

Do not enable trusted proxy headers blindly. The documented backend command disables them. Requests via the Next.js proxy share its peer IP and thus share the conservative IP budget; per-email limits still apply. A future public deployment needs explicit trusted proxy configuration and edge-level abuse controls. There is no Redis, Celery, refresh loop, or separate monitor. One native MongoDB process, a 256 MB storage cache, one backend worker, and one frontend process suit local development on 8 GB hardware. Browser tests use one worker.

## Limits and future work

Email validation establishes syntax, not ownership. Registration returns a generic duplicate-details message, but its status can still allow account-existence inference. No password reset, email verification, MFA, account administration, sandbox execution, or persistent future-phase data features are implemented. These require separately approved work. Local MongoDB must remain on loopback; production database credentials, TLS, backup policy, HTTPS, and deployment hardening are operator responsibilities.

## Dependency maintenance

The frontend lockfile fixes its full dependency tree. The minimatch override selects version 11.0.1 or newer for GHSA-g3hv-75wg-m249; rerun lint and audit after updates. Python direct versions are pinned while transitive versions resolve during installation. Both ecosystems are audited during validation and CI. Tests use disposable local databases and ephemeral test signing keys, never production credentials.

## Phase 3 agent engine

See README.md for the complete agent API, limits, lifecycle, providers, tools, data flow, and security limitations. `app/agents/providers.py` owns external I/O and error normalization; `engine.py` compiles the bounded StateGraph; `tools.py` defines a closed text-only registry; `api.py` applies ownership/CSRF/rate checks, execution leases, quotas, and MongoDB persistence. Existing `current_identity`, `require_csrf`, `limit_attempts`, connection pooling, and protected layouts remain the security boundaries.

`agent_sessions` and `agent_messages` use owner-prefixed indexes. A turn is persisted before provider I/O; events are persisted with the result, never raw chain-of-thought. Executions have no checkpointer service or external tracing. No paid service is selected automatically. A real Groq key and optional Ollama runtime are operator prerequisites for live checks; automated fixtures are explicitly isolated from the production entry point.

## Phase 4 sandbox

See [sandbox.md](sandbox.md) for the deterministic policy, approvals, limits, readiness gate, Docker lifecycle, isolated tests and explicit unverified security properties. The sandbox adapter is independent of authentication and safe text tools; unavailable infrastructure fails closed without preventing application startup.
