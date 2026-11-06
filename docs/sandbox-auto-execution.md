# Trusted-local Code Sandbox auto execution

`SANDBOX_POLICY=auto` changes direct, authenticated Code Sandbox requests from
request → approval → execution to request → execution. Python, C, C++, Java,
JavaScript and TypeScript all use the same existing dedicated executor and fixed
runtime registry. This setting does not grant the browser Docker access.

## Configuration and enforcement

Default remains `SANDBOX_POLICY=approval` (`REQUIRE_APPROVAL`). Automatic execution
requires **all** of the following:

- `SANDBOX_POLICY=auto`
- `SANDBOX_TRUSTED_LOCAL=true`
- `APP_ENV=development`
- All configured `CORS_ORIGINS` use `localhost`, `127.0.0.1` or `::1`.

Invalid auto configuration fails startup. The policy gate is also checked when
handling and dispatching executions. The explicit trust setting is an operator
assertion, not proof that a machine is private. Keep the frontend bound to
loopback; do not publish or tunnel a trusted-local deployment to untrusted users.
Production and untrusted deployments should retain `approval`. The pre-existing
legacy `allow` policy remains unchanged for compatibility; use the guarded `auto`
mode for this local compiler workflow.

Only direct Code Sandbox requests use auto execution. Requests associated with an
agent session or agent turn continue requiring exact, single-use approval. Agent
permissions and ownership checks remain in force. Existing pending requests are
never auto-approved or replayed. Changing policy invalidates old approval
fingerprints; submit a new request instead. Rejections remain available in
Monitoring for old pending requests.

`GET /api/sandbox/languages` returns `execution_policy` metadata. The Sandbox page
uses it to describe automatic execution and hide approval controls. The backend
alone decides whether to execute. `POST /api/sandbox/execute` still requires a
session, CSRF token, valid inputs, ownership, rate-limit and per-user quota checks.
It returns the normal persisted execution result. A running indicator is shown
while the request is pending; stdout, stderr, compiler status/output, exit code,
duration and execution history use actual API responses. A refresh after a lost
response should inspect history; execution is not automatically retried.

Policy evaluation and execution lifecycle events remain signed and persisted.
The execution record includes `execution_policy=AUTO_EXECUTE` and policy decision
`ALLOW`; no approval document or synthetic human-approval event is created.

## Existing Mac deployment

Work on `feat/multilang-google-recovery` with these source changes present. Do not
replace `.env.compose`, regenerate secrets, or delete volumes. Edit only these
non-secret settings in the **existing** `.env.compose` (replace existing entries,
do not leave duplicate keys):

```dotenv
APP_ENV=development
SANDBOX_POLICY=auto
SANDBOX_TRUSTED_LOCAL=true
```

Keep your existing loopback `CORS_ORIGINS`, image pins, Docker group, JWT/OAuth/Groq
settings and executor secret. From your Mac repository:

```sh
cd ~/Documents/GitHub/AgentShield-AI
git branch --show-current
colima status
docker context show
# The active Docker context must be your existing Colima runtime.
docker compose --env-file .env.compose -p agentshield-ai-v7 \
  -f compose.yaml -f compose.executor.yaml config --quiet

docker compose --env-file .env.compose -p agentshield-ai-v7 \
  -f compose.yaml -f compose.executor.yaml \
  up --build --no-deps -d --wait executor backend frontend

docker compose --env-file .env.compose -p agentshield-ai-v7 \
  -f compose.yaml -f compose.executor.yaml ps
```

This updates the three affected services in the same project and leaves MongoDB
running with its existing data. Do not use `down -v`. Refresh the Sandbox page at
`http://localhost:3000`, select C, and run the starter program. Readiness must pass
before Run Code is enabled. No manual approval is required for a new direct job.

Explicit harmless deployed-path validation (creates synthetic users and retained
history/audit records; never uses another user's pending approval):

```sh
for language in python c cpp java javascript typescript; do
  backend/.venv/bin/python scripts/validate-deployed-sandbox.py \
    --base-url http://localhost:3000 --policy auto --language "$language" || break
done
```

The validator asserts the expected policy before submitting, then checks actual
completion, stdout, empty stderr, exit status, retrieved history and signed audit
events. It does not prove every container restriction or cleanup; retain the
separate Colima isolation validation procedure in `sandbox-executor.md`. Respect
authentication quota windows when repeating this loop.

To restore approvals, set `SANDBOX_POLICY=approval` and
`SANDBOX_TRUSTED_LOCAL=false`, then repeat the same service update. Existing data
and secrets are preserved. Use `--policy approval` with the deployed validator.

## Security boundary and validation

The public backend still has no Docker socket. The private Unix-socket executor
retains authenticated requests, replay protection, fixed images/commands, readiness
verification, network denial, read-only rootfs, non-root UID, capability dropping,
no-new-privileges, seccomp checks, CPU/memory/PID/time/output limits, bounded
concurrency and cleanup. Unavailable isolation still produces
`SANDBOX_UNAVAILABLE`; auto mode does not alter Docker options or probes.

The trusted executor still holds broad Docker daemon authority. Ordinary
containers are not a complete boundary for hostile public code; this change is
for a trusted local application, not public multi-tenant code hosting.

Backend policy tests use real isolated MongoDB/auth and the signed executor
protocol with a mocked Docker execution manager. Browser automatic-mode tests use
real login and explicit mocked sandbox responses; existing approval browser tests
retain real auth/policy/persistence with mocked containers. Neither establishes
real runtime isolation. Live Mac validation must be run separately.

### Cloud validation evidence (2026-11-06)

- Backend: `PYTHONPATH=backend TEST_MONGODB_URI=mongodb://127.0.0.1:27018 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 backend/.venv/bin/python -m pytest backend/tests -q --tb=short` — **385 passed, 16 skipped**, one Starlette/AnyIO deprecation warning. The 16 opt-in Docker cases were not executed.
- Frontend: `npm run lint` and `npm run typecheck` — **PASS**.
- `TEST_MONGODB_URI=mongodb://127.0.0.1:27018 PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium npm --prefix frontend run test:e2e` — **26 passed**. Playwright built and started the Next.js production app before testing.
- Compose configuration for both policies — **PASS** using non-secret placeholder settings; backend socket isolation, executor network/port restrictions and frontend loopback binding checked. No Compose stack deployed.
- New tests cover six-language immediate dispatch, no approval document/replay, signed audit/history, cross-user denial, auth/CSRF, invalid requests, quotas, readiness/recovery failure, policy/session revalidation, retained agent approvals, invalid configuration, and validator policy/history/audit assertions.
- Fixed a pre-existing UI readiness stall when selecting the current language. Updated an existing approval regression test's wrapper to forward the new internal `approved` keyword, preserving its replay/retention assertions.
- Changed-file credential-pattern scan and `git diff --check` — **PASS**. The credential scan is heuristic, not a guarantee.
- Real Docker execution and Mac deployment — **BLOCKED / NOT VERIFIED** here. This cloud daemon lacks effective cgroup controllers; no isolation requirements were relaxed. No application secrets, persistent data or volumes changed. These checks do not deploy the application.
