# Reproducible testing and validation

Tests are meaningful only when their actual dependencies and execution are reported. A passing mocked container test is not a passing isolation test. Historical baseline results are 183 backend passes, ten opt-in real-Docker skips, ten browser passes and GitHub Actions run #9 success. Current Phase 7 results, workload measurements and any blockers are recorded in [phase7.md](phase7.md); do not treat these historical counts as a new run.

## Test data and prerequisites

Use Python 3.12, Node.js 24 and a credential-free, loopback MongoDB 7. Backend/browser fixtures create unique `agentshield_test_*` / `agentshield_e2e_*` databases and remove them after completed runs. They refuse remote or credential-bearing test URIs. Do not point them at production or relax these guards to use the authenticated Compose database.

A test-only MongoDB can run on a separate port without touching an existing app database:

```sh
CI_MONGODB_CONTAINER=agentshield-test-mongo \
CI_MONGODB_PORT=27018 \
bash .github/scripts/mongodb.sh start
```

This trusted CI helper starts official MongoDB 7 on loopback, waits for a bounded health check and provides failure diagnostics. It does not configure the execution sandbox or mount existing database data. Keep ports 3001/8001 free for browser tests.

## Backend and security regressions

From the repository root, install dependencies in the existing virtual environment without overwriting `.env`:

```sh
backend/.venv/bin/python -m pip install -r backend/requirements-dev.txt
cd backend
TEST_MONGODB_URI=mongodb://127.0.0.1:27018 \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
.venv/bin/python -m pytest -q --tb=short
.venv/bin/python -m pip check
```

The standard suite covers auth/JWT/CSRF/ownership and rate limits, agent tools and budgets, model error mapping/redaction, audit signatures, WebSocket admission/order/replay/revocation/cleanup, sandbox policy/approvals, and mocked Docker resource/lifecycle contracts. Phase 7 adds integrated waiting-decision-resolution behavior, Host checks, session/CSRF reliability, and deployment-related regressions where implemented. Existing earlier tests remain included.

To audit backend dependency advisories separately:

```sh
cd backend
.venv/bin/python -m pip install pip-audit==2.10.1
.venv/bin/python -m pip_audit -r requirements-dev.txt
```

Advisory results describe the time and package set actually audited, not a permanent security certificate. Do not hide failing tests with skips or disable application checks to make the suite green.

## Frontend and complete browser journeys

```sh
cd frontend
npm ci
npm run lint
npm run typecheck
npm run build
npx playwright install chromium
TEST_MONGODB_URI=mongodb://127.0.0.1:27018 npm run test:e2e
npm audit --audit-level=moderate
```

Playwright builds/starts the production Next.js frontend on 3001 and an explicit test API on 8001, generates an ephemeral signing key and uses one browser worker. It uses real HTTP, cookies, CSRF, MongoDB and WebSocket connections. `scripts.browser_test_app:make_app` injects mocked model/container adapters only under `APP_ENV=test` with an isolated database prefix; the normal `app.main:app` never imports those substitutes. Real user journeys exercise registration/login/profile/logout, saved conversations, safe tools, policy/approval controls, monitoring, isolation, failures and frontend state handling. No real Groq request or submitted-code isolation is proved by this test fixture.

If Chromium is already installed, set `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` to its executable. Set `BACKEND_PYTHON` if it differs from `../backend/.venv/bin/python`. Test traces may contain synthetic cookies and form data; do not upload unredacted traces from real user accounts. Browser-test builds point the proxy at 8001; run `npm run build` again before using `npm start` with the normal API 8000.

Remove only the disposable test database container when finished:

```sh
CI_MONGODB_CONTAINER=agentshield-test-mongo \
CI_MONGODB_PORT=27018 \
bash .github/scripts/mongodb.sh stop
```

## Real provider smoke tests

These are separate, optional live integrations. Configure an available free-tier Groq key securely and submit one short task through a real account/Playground. Confirm the stored conversation and signed event history. A missing key must produce the setup message rather than a fabricated answer. Real Groq completion is NOT VERIFIED unless an actual request succeeds.

For Ollama, explicitly install/start a lightweight tool-capable model suitable for the 8 GB Mac, enable the existing loopback configuration and send a short real task. The app does not download a model, enable billing or switch providers. Record the model/runtime and actual result; mocked HTTP responses are not local inference evidence.

## Real sandbox validation on the Mac

Stop the native backend so it cannot compete with validation. With Colima running, Python 3.12 and Docker CLI installed, run from the repository root:

```sh
bash scripts/validate-phase4-colima.sh
```

The unchanged script selects a local Colima Unix endpoint, runs only the trusted readiness probe until effective cgroup/namespace/security settings pass, then executes 12 fixed harmless programs inside the verified containers. It checks real memory/PID/CPU enforcement, output/time bounds, UID/filesystem/network/privilege restrictions and cleanup. It creates a `phase4-validation-*.json` report. Keep that report as evidence tied to the tested host/runtime/commit; it does not establish immunity to escapes.

The ten separate pytest real-container cases are opt-in and still require local test MongoDB:

```sh
cd backend
RUN_SANDBOX_INTEGRATION=1 \
SANDBOX_DOCKER_URL="$(docker context inspect colima --format '{{.Endpoints.docker.Host}}')" \
TEST_MONGODB_URI=mongodb://127.0.0.1:27018 \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
.venv/bin/python -m pytest -q tests/test_sandbox_real.py --tb=short
```

An opt-in run fails closed when readiness is unavailable; it does not silently turn into a mock. A standard run skips these ten cases when `RUN_SANDBOX_INTEGRATION` is unset. Report SKIPPED/BLOCKED with the exact reason, not PASS. The earlier user-supplied 12/12 Colima report is historical local evidence; it cannot be revalidated remotely in this cloud environment.

## Compose and recovery checks

Follow [deployment.md](deployment.md) to generate a separate ignored configuration, then validate/build/start the services. Do not print expanded Compose configuration containing credentials, reuse a MongoDB 8 volume, mount Docker sockets into the public backend, or enable sandbox execution to make a deployment check pass.

A useful verification record contains Compose syntax validation, image build results, service health, a real browser register/login/logout journey through the composed frontend, backend/database private-port checks and the enforced `SANDBOX_ENABLED=false` setting. MongoDB failure/recovery tests should use a disposable stack or explicit mocked failure, never interrupt a user's production database. Record which was actually used. Resource settings in Compose alone do not prove effective cgroup enforcement.

## Evidence labels

| Status | Meaning |
| --- | --- |
| PASS | The named command/check was executed and its asserted result succeeded. State whether external provider/container behavior was mocked. |
| FAIL | An executed check failed. Preserve the failure and report the blocker/fix; do not relabel it skipped. |
| SKIPPED / BLOCKED | The check did not execute, or readiness prevented submitted code. Include the unavailable dependency/control. |
| NOT VERIFIED | A property such as external HTTPS, real provider inference, Mac performance or hostile-tenant isolation has not been demonstrated. |

Measurements must state the observed environment, workload, sample count, methodology and actual latency/resource values. Cloud results are not MacBook M2 benchmarks. The MongoDB 7/Ubuntu24.04 CI lifecycle fix remains in `.github/workflows/ci.yml` and `.github/scripts/mongodb.sh`; all configured test gates and cleanup steps must remain enabled.


## Phase 7 standalone integration checks

Run only against disposable/isolated data and a credential-free loopback test MongoDB where required:

```sh
backend/.venv/bin/python scripts/measure-local.py --mongodb-uri mongodb://127.0.0.1:27017 --samples 20
backend/.venv/bin/python scripts/validate-mongo-recovery.py
```

The measurement command creates and drops its own database and never calls a model or sandbox. It reports its hardware/methodology and is not an M2 benchmark. Recovery selects a local Unix endpoint from the Docker context (or explicit `--docker-url`), creates its own MongoDB container/volume on a free test port, stops/restarts **only that container**, checks 503 failures and session recovery, then removes it. It never stops the existing database or changes the global Docker context. Use a compatible local Docker/Colima runtime and do not pass production credentials.

With an isolated Compose stack already healthy:

```sh
python3 scripts/smoke-compose.py --base-url http://localhost:3000
COMPOSE_BASE_URL=http://localhost:3000 node scripts/browser-compose.mjs
```

The browser command requires existing frontend npm dependencies and Playwright Chromium (or `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH`). Both commands create disposable test accounts in the selected stack. The HTTP smoke check exercises the normal app and signed sandbox-denial audit. The browser check exercises real built-service UI authentication, protected routes, live WebSockets, and a missing-provider error/history when no Groq key is configured. It never invokes a configured provider. Neither test enables sandbox execution, substitutes a fake production response, or proves public TLS/cgroup/Mac isolation. Reports and exact measured outcomes are in `phase7.md`.
