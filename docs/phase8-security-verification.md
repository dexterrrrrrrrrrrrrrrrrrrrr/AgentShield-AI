# Phase 8 verification — 2026-11-07

## Scope and findings

Existing authentication, CSRF, session ownership, tool allowlists, quotas, immutable
runtime identities, sandbox controls and Compose configuration remain unchanged.
The reviewed approval service checks expiry and ownership, validates the exact
source/stdin/language/runtime/limits fingerprint, atomically consumes the pending
record, then validates the consumed payload again. Rejections and consumed records
cannot authorize another execution. Existing tests cover expiry, changed policies,
concurrent decisions, cross-user access, rejection, and agent continuation.

Added a real MongoDB/auth regression that creates a pending approval, constructs a
new FastAPI application against the same database, verifies the request remains
pending without execution, rejects a wrong fingerprint, approves once, and rejects
replay from both application instances. Docker execution is explicitly mocked;
this is application restart/state verification, not a daemon crash recovery test.

Fixed a timeline presentation gap: approval resolution now persists explicit
`status`, `approved` and `duration` fields derived from the stored execution. The
frontend displays those fields rather than requiring users to interpret the
embedded result JSON. Older records remain compatible. Added backend assertions
for the persisted outcome fields. Users still select **Continue after decision**;
this does not automatically poll or rerun a tool.

Existing error handling distinguishes Groq credentials, rate limits, model and
transport failures; authorization and policy failures remain safe errors. Session
expiry dispatches the shared sign-out event. Unknown execution/network outcomes
are not automatically replayed. No speculative provider or authentication changes
were necessary. Failure messages and prior security regressions were exercised by
the existing suites.

## Evidence

- Backend: 406 passed, 16 skipped; one dependency deprecation warning.
- Browser suite: 28 passed.
- ESLint and TypeScript: passed.
- Production build: executed by Playwright before serving the frontend.
- Compose base + executor overlay: `config --quiet` passed with synthetic
  placeholder variables; no service deployed or environment file overwritten.
- Cloud runtime inspection: cgroup v2, cgroup driver `none`. Real isolation tests
  are BLOCKED; no untrusted sandbox code was executed for this verification.
- Provider and sandbox I/O in automated tests are mocked. MongoDB persistence,
  FastAPI authentication, browser navigation and WebSocket transport are real.
- Live Groq, Google login, Mac executor path and public deployment: NOT VERIFIED.

## Manual Mac verification

Use the existing Colima context and deployment; preserve all volumes and secrets.
From the repository root, run:

```sh
bash scripts/validate-phase4-colima.sh
backend/.venv/bin/python backend/scripts/validate_multilanguage.py --help
backend/.venv/bin/python scripts/validate-deployed-sandbox.py --base-url http://localhost:3000 --language python --policy auto
```

Use `--policy approval` instead if the existing direct Sandbox deployment requires
approval. The deployed validator creates a synthetic account and retained audit
records; it runs only a fixed harmless program after readiness passes. Follow the
multi-language guide for configured immutable images and repeat for c, cpp, java,
javascript and typescript within quotas. Do not equate direct Sandbox auto mode
with agent approval: separately request `execute_code` in Playground, verify no
execution before approval, reject one request, approve another, continue the turn,
and reload to inspect status, duration and history. Test restart while pending
without changing keys/configuration. No cloud test establishes Mac runtime safety.

Production readiness remains conditional: HTTPS/WSS, trusted proxy configuration,
Secure cookies, private database, protected executor credentials, backups and
restore drills are operator responsibilities. Docker daemon authority is a major
executor trust boundary; ordinary containers do not guarantee escape resistance.
This is a portfolio-demo verification, not a production security certification.
