# Groq calculator invocation investigation

## Evidence and limits

The reported answer `45290990.571428575` is the calculator's result for
`(987654 * 321) / 7`. The answer alone does **not** prove tool invocation.
This cloud workspace has no configured Groq credential and no access to the
affected Mac deployment's MongoDB or captured Groq response. The cause of that
specific turn remains **NOT VERIFIED**. No live Groq request was performed.

Code inspection and regression tests found no broken calculator dispatch,
persistence, or timeline path. No speculative provider or policy change was made.

1. `Providers.complete` supplies the saved conversation's permitted tool schemas
   to the official SDK. `tool_choice` is omitted: Groq's automatic selection
   permits either a direct answer or tool calls. Ordinary conversations are never
   forced through a tool. A user's instruction to use a tool is not a guarantee
   that the provider returns one.
2. Calculator uses `{"text": "(987654 * 321) / 7"}` with a required `text` field
   and additional properties forbidden. A saved session can exclude calculator;
   permission changes for a new conversation do not rewrite existing sessions.
3. `reply_from` parses `message.tool_calls[].function.arguments` as bounded JSON.
   The engine validates the entire batch, rechecks live authentication, session
   ownership/lease and allowed tools, then executes the bounded calculator.
4. Actual invocation emits `tool_request` and `tool_response` into the turn, and
   `tool_requested`, `policy_evaluation: ALLOW`, `tool_completed` into signed
   monitoring records. The tool result is sent back to Groq before the final answer.
5. The authenticated response and `agent_messages.events` contain the same
   workflow events. History and events endpoints enforce ownership. The Playground
   renders those stored events, including tool inputs and outputs, after reload.
6. Direct answers contain `model_request` and `completed`, without calculator
   events. The UI now explicitly says no tool request was recorded for such a
   completed turn. It never invents execution evidence from assistant text.

No private reasoning, raw provider responses, credentials, or extra production
logging were added. Sensitive tools retain sandbox readiness and human approval.

## Verify the affected turn on the Mac

Use the existing deployment and logged-in browser; do not create a second stack
or change secrets. Open the affected saved Playground conversation.

1. Expand **Provider, model & tool permissions**. Confirm the saved model is
   `openai/gpt-oss-20b` and calculator is enabled. If disabled, create a new
   conversation with calculator enabled; do not bypass authorization.
2. In browser developer tools, select **Network**, reload/select the conversation,
   and inspect the authenticated `/api/agent/sessions/<id>/messages` response.
   Find the reported turn's `events` array. The ownership-protected
   `/api/agent/sessions/<id>/events` endpoint returns the same stored evidence.
3. `tool_request` plus `tool_response` for `calculator`, with the exact expression
   and result, confirms dispatch and completion. Only `model_request` and
   `completed` indicates the engine recorded a direct model answer. Missing or
   unexpected records require investigation; do not infer success from the number.
4. In Monitoring or `/api/monitor/events`, correlate `execution_id` with the turn's
   `id`: expect `tool_requested`, `policy_evaluation` with `ALLOW`, and
   `tool_completed`. These records omit prompts and tool payloads.
5. For a fresh live smoke test, send: **Use the calculator tool to evaluate
   (987654 * 321) / 7.** Inspect the POST response's `events`, then expand
   **Tool execution timeline**. Expect the request and response with
   `Output: 45290990.571428575`; reload and confirm they persist.
6. If the model answers directly again, report **no tool invocation**, not a
   successful tool test. A calculator request with no response, or events in the
   API but absent in the UI, points to a different failure requiring its evidence.

Do not share cookies, authorization headers, HAR files containing credentials,
or full private conversations. Turn IDs, event kinds, model identifier, permitted
tool names and this harmless arithmetic input/output are sufficient for this
diagnosis. Do not enable raw Groq request/response logging to collect evidence.

## Reproducible regressions

Run against an isolated local test MongoDB (never a production URI):

```sh
PYTHONPATH=backend TEST_MONGODB_URI=mongodb://127.0.0.1:27018 \
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 backend/.venv/bin/python -m pytest backend/tests -q --tb=short
npm --prefix frontend run lint
npm --prefix frontend run typecheck
TEST_MONGODB_URI=mongodb://127.0.0.1:27018 npm --prefix frontend run test:e2e
```

Use your isolated test MongoDB port instead of `27018` when different. Install
Playwright Chromium if needed. Browser tests build and serve the production frontend.

`test_groq_request_path.py` exercises the real official SDK serialization, FastAPI
authentication, LangGraph, calculator, MongoDB persistence and signed audit records
with **mocked Groq HTTP**. Two tests intentionally return the identical numeric
answer with and without `tool_calls`, verifying different API/database/audit
evidence. Additional tests reject unpermitted tools and invalid arguments. The
browser test uses the explicit test-only provider and verifies both paths, tool
input/output rendering, and persistence after reload. Neither suite establishes
that a live model will choose to call calculator.

## Executed validation (2026-11-06, cloud)

- Full backend suite: **405 passed, 16 skipped**, one Starlette/AnyIO deprecation
  warning. The skipped tests require opt-in real sandbox validation. No Docker
  isolation claim is made; the managed daemon reports cgroup driver `none`.
- Groq SDK/request-path file: **20 passed**, using mocked HTTP and real local
  MongoDB. Calculator arithmetic and signed audit verification were real.
- Full browser run: **27 passed, 1 failed** in the newly added test's selector.
  Its exact-text selector omitted the input/output text inside each timeline row.
  Corrected it to check the row and exact arithmetic input/output; reran all
  Playground cases: **3 passed**, including the new case. All 28 distinct browser
  cases have therefore passed, but not in one final full-suite run.
- An earlier targeted browser run also caught an incorrect test expectation that
  Send would be enabled with an empty composer. The test now waits for the input
  to become editable. No production behavior was changed for either test fix.
- Frontend ESLint, TypeScript, and Next.js production build: **PASS**. Playwright
  builds and starts the production frontend before testing.
- Initial restricted-shell pytest attempt could not reach test MongoDB and was
  terminated; the reported passing backend runs used approved localhost access.
- Live Groq selection and the original Mac turn: **NOT VERIFIED** (no configured
  cloud Groq credential or access to the affected deployment's records).
- No sandbox, approval, authentication, authorization, rate-limit, or provider
  production code changed. No Mac deployment was updated.
