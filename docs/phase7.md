# Phase 7 integration, deployment, and validation report

Baseline: `3f7a1f865476a4717ad605d4477336e027374491`. The audit was recorded before implementation in [phase7-audit.md](phase7-audit.md). This report records executed local/cloud evidence; remote CI status is per-commit and must be checked on GitHub after push. No public-production or hostile-code isolation certification is claimed.

## Delivered integration

- **PASS:** Real dashboard analytics/provider/readiness state; functional Settings and per-conversation provider/model/tool configuration through existing APIs; consistent navigation, loading/empty/error states, deletion confirmation, and bounded history/audit pagination. No fake production analytics or model responses were introduced.
- **PASS:** Original agent turns pause as `awaiting_approval`, with server-only user/session/turn/execution bindings. Owner decisions remain expiring/content-bound/atomic. Explicit **Continue after decision** resolves that original turn once from actual outcomes, with tools disabled and original budgets retained. No code is replayed. Further tool work requires a new turn; finalization is not a hidden graph checkpoint. Duration measures active execution, excluding human waiting.
- **PASS:** Lease fencing prevents a stale request dispatch/finalizer from controlling a newer execution. Expired approval code is not returned; clearing a conversation cancels its pending requests. Consumed payload-free markers retain metadata for 120 seconds without extending approval permission.
- **PASS:** Valid session-bound CSRF reuse plus one frontend retry only for an exact pre-handler CSRF failure; no retries of timeouts, provider errors, or unrelated 403s. Safe session expiry metadata/timers, 401/logout invalidation, and protected route/API ownership remain enforced.
- **PASS:** WebSocket authentication and user isolation, bounded exponential reconnects, auth checks after opaque handshakes, terminal authorization/origin handling, reconnect snapshot synchronization, dedup/order, 45-second inactivity watchdog and cleanup. Backend limits remain 200 retained events, 50-event batches, four/user and 20 total shared leases. Client audit/event history caps at 200; there is no unbounded broker/queue.
- **PASS:** Validated exact trusted Hosts for HTTP/WebSockets, including controls/ambiguous authority rejection. Existing JWT/Argon2/CSRF/rate/provider/schema/redaction/audit controls remain.

## Deployment delivered

- **PASS:** Multi-stage Python 3.12/Node.js 24 builds; app UIDs 10001, Mongo UID 999; read-only app roots, dropped capabilities/no escalation, private backend/database networks, loopback-only frontend, actual health dependencies, bounded cache/connections, configured memory/CPU/PID/log budgets, graceful shutdown and persistence.
- **PASS:** Authenticated MongoDB 7 application user has `readWrite` only on the app database; backend receives no root password. App-account health validation blocks dependents if initialization/credentials fail.
- **PASS:** The new default `agentshield-ai-v7` project and `mongo7-data` volume do not replace the previous MongoDB 8 project's containers or files. No automatic version downgrade/migration is attempted.
- **PASS:** Exclusive-create env helper with mode 0600 preserves existing keys/files. Images exclude env/test fixtures; optional build CA trust uses temporary BuildKit mounts, not copied secrets. Native production build/start and Docker standalone modes both remain supported.
- **PASS:** Public-facing Compose backend has no Docker socket and forces sandbox off. This is an explicit limitation, not unrestricted execution fallback. Full real sandbox/Ollama demonstrations use the trusted native-host backend with separately validated Colima. See [deployment.md](deployment.md).
- **NOT VERIFIED:** Effective application-container cgroup enforcement in this cloud runtime (driver `none`), Apple Silicon resource/performance behavior, production TLS/WSS/certificates/edge policy, backup restoration drills, and a separate least-authority sandbox orchestration service.

Actual final built image/security metadata and readWrite-role checks are in [phase7-deployment.json](phase7-deployment.json). Requested resource settings are not represented as proof of kernel enforcement.

## Executed verification

| Check | Status | Evidence / boundary |
| --- | --- | --- |
| Required plugin-autoload-disabled backend suite | **PASS** | `TEST_MONGODB_URI=mongodb://127.0.0.1:27018 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 backend/.venv/bin/python -m pytest -q --tb=short backend/tests`: **219 passed, 10 skipped**; real disposable MongoDB 7, mocked provider/container interfaces where required. |
| Original Phase 1–6 regressions | **PASS** | Preserved; 18 new workflow/auth/lease tests plus 18 Host/origin tests increase 183 to 219. Expectations changed only for corrected waiting/configuration/confirmation semantics, not test removal. |
| Frontend ESLint and TypeScript | **PASS** | Actual configured `npm run lint`, `npm run typecheck`; no errors. |
| Host production build | **PASS** | `npm run build`; standard `next start` remains supported. Docker alone opts into standalone output. |
| Browser suite | **PASS** | **18 passed** in 47.3 seconds, MongoDB 7/system Chromium/production Next.js/real WebSockets. External model and sandbox adapters are explicit test-only fixtures; original 10 journeys retained. |
| Backend/frontend dependency audits | **PASS** | pip-audit/npm audit report no known vulnerabilities; `pip check` passes. This is time-bound known-vulnerability evidence, not an absence-of-bugs proof. |
| Compose configuration and final image builds | **PASS** | `config --quiet`, final backend/frontend Docker builds and all 3 service health checks executed with isolated ephemeral credentials/project/volume. |
| Real built-stack HTTP journey | **PASS** | `scripts/smoke-compose.py`: normal backend/provider implementation, auth, dashboard, persisted session, fail-closed sandbox denial, signed owner audit, monitoring and logout; no inference/code requested. |
| Real built-stack browser journey | **PASS** | [phase7-compose-browser.json](phase7-compose-browser.json): UI register/login/protection/logout, real WebSocket, actual missing-provider failure/history; no production mocks. |
| Actual database outage/recovery | **PASS** | [phase7-recovery.json](phase7-recovery.json): isolated owned MongoDB stop/start; readiness/profile 503 during outage, profile 200 after restore, same session preserved; measured recovery 0.817 seconds in this run. |
| Env safety/setup and workflow validation | **PASS** | Exclusive creation, 0600 mode, no overwrite, generated separate keys/origin; YAML/test/cleanup checks and shell syntax. Existing Ubuntu24/Mongo7 CI helper remains byte-for-byte unchanged. |
| Credential-pattern/source review | **PASS** | Recognizable token/private-key/environment-file scan; no values disclosed. Preserved sandbox manager/policy/readiness/validator byte-for-byte. Pattern scanning is not complete DLP. |
| Real sandbox pytest cases | **SKIPPED** | Existing 10 opt-in cases require compatible effective controllers. They are not passes. |
| Actual managed sandbox readiness | **PASS** (fail-closed behavior only) | Unchanged operator CLI returned `SANDBOX_UNAVAILABLE`, exit 2, before any submitted program. Required daemon cgroup driver is unavailable. |
| New real sandbox isolation / current Mac validation | **NOT VERIFIED** | No untrusted sandbox programs ran here. User-reported earlier 12/12 Colima report is separate evidence; not immunity from escapes. |
| Live Groq/Ollama inference | **NOT VERIFIED** | Deterministic tests use mocked HTTP/provider interfaces; real Compose missing-key behavior is tested without provider traffic. No paid API or automatic download was used. |
| Remote CI for final pushed commit | **NOT VERIFIED in this static local report** | Workflow includes backend/security tests, frontend lint/types/production browser build and a new free-runner Compose build/smoke job. Check the exact pushed commit's Actions run; final delivery reports its observed status separately. |

Upstream Starlette/AnyIO and Uvicorn legacy-WebSocket deprecation warnings remain. They do not represent suppressed failures. A future transport migration must separately preserve its frame/queue/backpressure behavior.

## Measured API workload

The reproducible script is `scripts/measure-local.py`; raw results and limitations are in [phase7-performance.json](phase7-performance.json). Hardware reported **Linux x86_64, 5 logical CPUs, Python 3.12.14, 35,743,748,096 host-visible memory bytes**. This is a shared cloud environment, not an 8 GB M2 benchmark or an enforced container budget.

Workload: one disposable user/conversation, 50 persisted turns, 200 signed audit events, concurrency 1. Three warmups then 20 sequential samples per endpoint. Times are in-process TestClient request roundtrips including live local MongoDB, auth and serialization, excluding TCP/TLS/browser/model/sandbox latency. App/tooling source is commit `abc1efb184e273ff51870503a91089d78268c3fb`; documentation was still pending, hence the honest dirty-worktree marker. Background service activity/shared scheduling can affect results. No before/after speedup or throughput/SLA claim is made.

| Endpoint workload | Samples | Median ms | p95 ms | Max ms |
| --- | --- | --- | --- | --- |
| session_page_20 | 20 | 3.900 | 4.748 | 4.908 |
| history_page_20 | 20 | 5.042 | 5.881 | 6.137 |
| audit_page_50 | 20 | 7.086 | 15.424 | 16.733 |
| analytics_summary | 20 | 8.739 | 12.858 | 15.583 |

Resource-oriented improvements are enforced bounds: feed polling only while monitoring sockets are open, single expiry/watchdog timers, coalesced snapshots, bounded client state, paginated reads, six-turn provider context, small pools/cache, single API worker and no Redis/Celery/heavy local model requirement. Measurements establish a diagnostic baseline only; repeat on the actual Mac before setting latency/capacity expectations.

## Remaining limits and release assessment

**PASS:** local launch/demonstration baseline, with actual accounts/conversations/permissions/monitoring/audit and an explicitly safe Compose mode. Full approved sandbox-to-final-response journeys are automated against real APIs/MongoDB/WebSockets with mocked external runtime/provider boundaries, not forged production data.

**NOT VERIFIED:** public production deployment, a secure remote sandbox control plane, effective cloud cgroups, current Mac end-to-end/resource behavior, live provider availability/free quotas, and restore drills. Docker containers alone are not complete malicious-code isolation. Prompt injection can influence prose; it cannot grant tools or override the server guards. Signed records detect modification under key trust, not arbitrary administrator deletion/rollback or compromised keys. Legacy unsigned audits remain labeled. Standalone Mongo multi-document interruption can leave conservative quotas/incomplete/orphan records; used approvals are not restored and uncertain code is never automatically replayed. Finalization failure is terminal for that turn; actual results remain in execution history.

Use the exact [testing](testing.md) and [deployment](deployment.md) commands, preserve your existing secrets/data, and run `bash scripts/validate-phase4-colima.sh` on the real Colima host before enabling native sandbox execution.

## File manifest

Relative to the audited baseline; the pre-existing `phase5.patch` is excluded and preserved.

### Created (29)

- `backend/.dockerignore`
- `backend/Dockerfile`
- `backend/app/hosts.py`
- `backend/tests/test_hosts.py`
- `backend/tests/test_monitor_origin.py`
- `backend/tests/test_phase7_workflow.py`
- `compose.native.yaml`
- `deploy/mongo-init.js`
- `docs/deployment.md`
- `docs/phase7-audit.md`
- `docs/phase7-compose-browser.json`
- `docs/phase7-deployment.json`
- `docs/phase7-performance.json`
- `docs/phase7-recovery.json`
- `docs/phase7.md`
- `docs/security.md`
- `docs/testing.md`
- `frontend/.dockerignore`
- `frontend/Dockerfile`
- `frontend/src/app/(protected)/settings/page.tsx`
- `frontend/src/components/settings.tsx`
- `frontend/src/components/workspace-nav.tsx`
- `frontend/src/lib/protected-api.ts`
- `frontend/tests/phase7.spec.ts`
- `scripts/browser-compose.mjs`
- `scripts/init-compose-env.py`
- `scripts/measure-local.py`
- `scripts/smoke-compose.py`
- `scripts/validate-mongo-recovery.py`

### Modified (35)

- `.env.example`
- `.github/workflows/ci.yml`
- `.gitignore`
- `README.md`
- `backend/app/agents/api.py`
- `backend/app/agents/engine.py`
- `backend/app/auth.py`
- `backend/app/config.py`
- `backend/app/database.py`
- `backend/app/main.py`
- `backend/app/monitoring/api.py`
- `backend/app/sandbox/api.py`
- `backend/app/sandbox/service.py`
- `backend/app/schemas.py`
- `backend/scripts/browser_test_app.py`
- `backend/tests/conftest.py`
- `backend/tests/test_auth.py`
- `backend/tests/test_sandbox.py`
- `compose.yaml`
- `docs/architecture.md`
- `frontend/next.config.ts`
- `frontend/playwright.config.ts`
- `frontend/src/app/(protected)/profile/page.tsx`
- `frontend/src/app/layout.tsx`
- `frontend/src/components/dashboard.tsx`
- `frontend/src/components/monitoring.tsx`
- `frontend/src/components/playground.tsx`
- `frontend/src/components/sandbox.tsx`
- `frontend/src/components/session.tsx`
- `frontend/src/lib/agent-client.ts`
- `frontend/src/lib/auth-client.ts`
- `frontend/src/lib/monitor-client.ts`
- `frontend/tests/auth.spec.ts`
- `frontend/tests/monitoring.spec.ts`
- `frontend/tests/playground.spec.ts`
