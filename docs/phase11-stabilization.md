# Phase 11 — stabilization and local release candidate

Date: 2026-11-07. Base: latest main (`cd4a084`). Branch: `phase11/stabilization`.
This is application stabilization evidence, not production certification or a
v1.0.0 tag. No deployment, secrets, approval policies or user data were changed.

## Monitoring investigation

`GET /api/monitor/summary` groups the authenticated user's stored `agent_messages`
by status. One record is one submitted turn, not one tool invocation, API request,
container execution, or conversation. Success means completed; failed includes
failed and interrupted. Those can represent provider errors, invalid/denied tools,
timeouts, interrupted work, or rejected/expired approval continuation. Therefore
failed does not mean a Docker/backend outage. Pending agent turns can be awaiting
approval **or continuation after a decision**, independently of live pending
approval documents.

Totals include historical attempts still retained in the database. They are not
a current error rate or a new session's score. Blocked tool requests count retained
signed `tool_rejected` events and include human rejection; they are a separate
metric, not extra executions to add to totals. Approval counters and sandbox
counters describe different record types and must not be summed into agent totals.

The reported 43 total / 10 successful / 26 failed implies seven turns in other
statuses. This cannot identify their actual statuses or diagnose those 26 failures.
The cloud workspace cannot inspect the user's Mac database. Investigate the
owned summary's `by_status`, then corresponding stored turns and signed events on
that deployment. Do not delete records to make the numbers look healthier.

## Confirmed defects and minimal fixes

1. The UI omitted the existing agent status breakdown, making total look
   inconsistent with success/failure. Monitoring now shows all stored statuses,
   including pending approval/continuation, with explicit historical-scope text.
2. Expired approval requests remained in the raw `pending_approval` sandbox bucket.
   Read-time Mongo aggregation now classifies overdue pending approval records as
   expired without rewriting the execution. It also recognizes persisted
   `APPROVAL_EXPIRED` outcomes after continuation, preserving their expired
   classification instead of showing them as generic rejection.
3. Expired approval counting now uses that same classification, so it cannot
   disappear solely because continuation updates the raw execution status.

Completed, failed, pending, rejected and expired records remain distinct. Blocked
requests remain a clearly described separate rejection-event count. No new events,
private prompts or source payloads are added to monitoring. Historical data, signed
records, ownership filters and retention rules are preserved. Aggregation remains
server-side and bounded by known statuses; no full collection is loaded into the
frontend. No performance tuning or infrastructure was introduced without evidence.
Statistics across collections are not a transactional snapshot during concurrent
execution; a refresh can observe transitions between reads.

## Tests and verification

- Full backend suite: **410 passed, 16 skipped**, 0 failures on final rerun.
- Initial run: 409 passed, 1 failure in the new fixture because it omitted the
  existing unique session/turn fields. The fixture was corrected; no production
  index or test requirement was weakened.
- Full browser suite: **30 passed**. Covers continuation, one-time approval,
  rejection, stored outcomes, reload, authentication, monitoring and painted caret.
- Targeted monitoring browser rerun after adding explicit label assertions: **2 passed**.
- ESLint, TypeScript and production build: **PASS**.
- Python requirements audit: **no known vulnerabilities**; npm full audit:
  **0 vulnerabilities**; pip compatibility: **no broken requirements**.
- Compose base/executor configuration: **PASS**, using placeholders without
  overwriting environment files; backend still has no Docker socket mount.
- Real sandbox validator: **BLOCKED**, exit 2, CGROUP_V2_UNAVAILABLE, tests: [].
  No code ran; 16 opt-in real sandbox pytest cases remain skipped, not passed.
- Live Groq: **NOT VERIFIED**, no credential configured in this cloud backend.
- The user's six-language Colima success is operator-reported evidence, not a
  real-Docker result from this cloud run.

New real-Mongo regression checks totals against status sums, historical mixed
states, expired-before/after-continuation classification, owner isolation and that
read-only summary requests leave stored statuses unchanged. Explicit browser
assertions check the new agent breakdown empty state and historical-scope message.
Existing suites verify JWT/cookies/CSRF/rate limits, exact code/language/stdin/
runtime/resource approval fingerprints, restart persistence, audit signatures,
executor authentication and safe runtime configuration contracts.

Authentication, MongoDB, LangGraph orchestration and browser/WebSocket paths are
real in automated integration tests; external Groq/Google/container I/O is mocked.
Approval continuation executes no code again, and finalization is tool-disabled.
Tests check its input reflects actual stored results. An actual LLM's narrative
accuracy remains a live acceptance item; mocks cannot establish it.

## Remaining limits and RC assessment

No new execution/security defect was identified by the final regressions. This
branch is suitable for local RC acceptance review, subject to Mac validation.
The causes of the reported historical failures remain unverified; no unsupported
claim that the deployed backend is failure-free is made. Docker containers do not
certify escape resistance. The private executor's daemon authority, HTTPS/WSS,
proxy/cookie configuration, protected keys, backups and recovery drills remain
operator responsibilities. No destructive recovery test ran against user data.

## Exact Mac validation commands

Use the existing checkout and Colima profile. Preserve keys, volumes and project
name; do not run `down -v`. After reviewing this branch:

```sh
git fetch origin
git switch phase11/stabilization
colima status
docker context show
docker compose --env-file .env.compose -p agentshield-ai-v7 \
 -f compose.yaml -f compose.executor.yaml config --quiet
docker compose --env-file .env.compose -p agentshield-ai-v7 \
 -f compose.yaml -f compose.executor.yaml up --build --no-deps -d --wait backend frontend
bash scripts/validate-phase4-colima.sh
PYTHONPATH=backend backend/.venv/bin/python backend/scripts/validate_multilanguage.py \
 --docker-url "unix://${HOME}/.colima/default/docker.sock"
```

Adjust project/profile only to match the existing deployment. With its configured
immutable runtime identities and passing readiness, validate each deployed path:

```sh
for language in python c cpp java javascript typescript; do
 backend/.venv/bin/python scripts/validate-deployed-sandbox.py \
  --base-url http://localhost:3000 --language "$language" --policy auto || break
done
```

Use `--policy approval` if direct-user approval mode is configured. These commands
create synthetic accounts and retained audit rows. Never change policy just to
satisfy the validator. On Monitoring, inspect Agent turns and sandbox statistics;
confirm totals equal their status breakdown and expired approvals are not live
pending approvals. Review the actual failed-turn safe messages locally, without
sharing credentials, HARs or private source. Submit a new Groq task, explicitly
approve its exact code, continue, then reload: verify one execution ID/result and
no repeated code execution. Repeat rejection and expiry. Perform a backup/restore
rehearsal on disposable infrastructure before calling this a release candidate.

Recommended next step: operator-assisted Mac acceptance and analysis of retained
failure categories, followed by a local demo. No tag or automatic merge.
