# Phase 9 integration verification — 2026-11-07

## Architecture and methodology

The existing Next.js frontend calls authenticated FastAPI routes. LangGraph sends
only permitted tool schemas to Groq/Ollama; validated tool requests enter either
the bounded local calculator/summarizer/JSON formatter or the sandbox policy
service. MongoDB stores sessions, immutable approvals and execution results.
The private authenticated executor owns Docker access, not the public backend.
Signed, user-scoped audit events feed Monitoring/WebSockets. No UI redesign,
Compose changes, dependency additions or user-data migrations were made.

Unit tests exercise parsing, policy, response bounds and runtime contracts.
Integration tests use disposable real MongoDB databases and real authentication,
LangGraph, audit signatures and SDK serialization, with mocked external provider
and Docker responses. Browser tests run a production Next.js build and actual
FastAPI/MongoDB/WebSockets, with the explicitly test-only provider/executor.
Mocks establish application behavior, not live model selection or kernel isolation.

## Confirmed defect and correction

`policy_mode` previously protected agent requests in trusted-local `auto` mode,
but returned legacy `allow` unchanged. An operator selecting that legacy policy
could therefore permit agent-associated code without approval. Agent requests
now map `allow` to `approval`. Direct user requests retain existing behavior;
`deny` and invalid trusted-local auto configuration remain fail-closed. Existing
fingerprints, quotas, ownership checks, single-use claims and execution isolation
are unchanged. The regression test now covers approval, auto and legacy allow
through authenticated API calls and the actual remote-executor protocol with a
mock runtime: zero dispatch before approval, then exactly one execution.

## Verified coverage

- Calculator, summarizer and JSON formatter: real bounded implementations,
  schema rejection, unknown/unpermitted tools, provider response parsing.
- Python and language-aware agent tools: approval pause, ownership, exact request,
  reject/expire/replay protection, recorded continuation and restart persistence.
- Six-language registry and both direct-user policies: request validation,
  immutable runtime settings, result persistence, mocked runtime/compile failures,
  output/time limits and cleanup contracts. Real language execution is BLOCKED.
- Groq errors: mocked timeout, rate limits, invalid response and permission errors.
  A final answer is never treated as proof of a tool call; stored request/response
  events and signed policy/completion records are checked separately.
- Browser loading/error/empty states, saved timelines, approval controls, session
  expiry, WebSocket reconnection and isolation retain existing regression coverage.
- Audit records retain fixed metadata and signatures; bounded redacted tool
  inputs/results reside in owned conversation/execution records. Ordinary audit
  logs intentionally omit arbitrary source and arguments to minimize exposure.
- Database/executor/provider failure paths remain fail-closed. Unknown execution
  outcomes are not automatically replayed.

## Live verification and limitations

No Groq key is configured in this cloud backend: all five live Groq tool tests
remain PENDING. The real Docker validator returned exit 2, status BLOCKED,
`SANDBOX_UNAVAILABLE`, diagnostic `CGROUP_V2_UNAVAILABLE`, and `tests: []`.
The daemon reports cgroup v2 with driver `none`. No code program was executed;
CPU/memory/PID enforcement and real six-language compilation are not verified.
No application Compose stack was launched. Base + executor overlay configuration
was validated with placeholder variables, without touching environment files.
The isolated test MongoDB service was started only for testing.

Docker containers are not an escape-proof boundary. Executor daemon authority,
HTTPS/WSS, Secure cookies, proxy restrictions, protected secrets, database backups
and restore drills remain deployment responsibilities. Live Google authentication
and actual Mac executor health were not verified. Dependency deprecation warnings
remain; no dependencies were changed to suppress them. Production readiness is
NOT established by these mocked integration tests.

## Manual Mac checklist and recommended next phase

Keep the existing Compose project, volumes and secrets. Do not create another stack.

1. Run `bash scripts/validate-phase4-colima.sh` with the intended Colima context.
2. With immutable runtime identities configured in backend/.env, run
   `PYTHONPATH=backend backend/.venv/bin/python backend/scripts/validate_multilanguage.py --docker-url "unix://${HOME}/.colima/default/docker.sock"`.
   Adjust only the operator-selected socket for another Colima profile.
3. Against the existing application, run
   `backend/.venv/bin/python scripts/validate-deployed-sandbox.py --base-url http://localhost:3000 --language python --policy auto`.
   Use `--policy approval` if that is the configured direct-user policy. Repeat
   for c, cpp, java, javascript and typescript within quotas. This creates a test
   account and retained audit/history records; it submits only fixed harmless code.
4. Exercise each tool with live Groq in Playground. Verify actual tool_request and
   tool_response records, not the model's answer. For code, inspect exact source,
   language and stdin before approving. Reject another request and let another
   expire; verify neither executes. Reload and inspect the original turn/history.
5. For each language verify harmless syntax/runtime failures, timeout, bounded
   output, and effective isolation using the existing runtime test instructions.
   The six-language hello-world validator alone is not comprehensive isolation proof.
6. Restart the backend with a pending request, preserving keys/configuration, then
   check that explicit approval is still required and replay remains rejected.
7. Record runtime versions, commit, timestamps and test outputs without cookies,
   API keys, raw provider logs or private source. Do not upload credential-bearing HARs.

Recommended next phase: operator-assisted live Mac/provider acceptance testing and
backup/restore rehearsal, followed by a portfolio demo recording. No further
feature expansion or production certification until those checks have evidence.

## Executed results

| Check | Result |
| --- | --- |
| Full backend pytest | 408 passed, 16 skipped, 0 failed (51.61 s) |
| Full browser suite | 28 passed, 0 failed (1.1 min) |
| ESLint | PASS |
| TypeScript | PASS |
| Next.js production build | PASS, built by Playwright webServer |
| Compose base + executor overlay | PASS, placeholder-only configuration validation |
| Live Groq | PENDING, no credential configured |
| Real Docker language validator | BLOCKED, exit 2; no programs executed |
| Mac deployed application health | NOT VERIFIED |

Commands used: `PYTHONPATH=backend TEST_MONGODB_URI=mongodb://127.0.0.1:27018
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 backend/.venv/bin/python -m pytest backend/tests
-q --tb=short`; `npm --prefix frontend run lint`; `npm --prefix frontend run
typecheck`; `TEST_MONGODB_URI=mongodb://127.0.0.1:27018
PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium npm --prefix frontend run
test:e2e`. Test databases are disposable; no application MongoDB data was changed.

Changed files: `backend/app/sandbox/policy.py`,
`backend/tests/test_sandbox_auto.py`, and this document. No commit or push performed.
