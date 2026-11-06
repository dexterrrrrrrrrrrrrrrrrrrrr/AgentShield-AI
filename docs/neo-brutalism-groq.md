# Dark Neo-Brutalist workspace and Groq request-path repair

## Implemented interface

All eight existing pages share the black/charcoal/electric-blue identity. Global
Tailwind tokens keep retained functional controls consistent: #09090B background,
#111115 navigation, #18181F cards, #22222B elevated surfaces, #34343F borders and
#3B82F6 primary actions. Primary surfaces have 2px borders, sharp corners and hard
shadows. Space Grotesk and JetBrains Mono are bundled locally with their SIL OFL
licenses; no remote font request or UI library is required. Body text retains the
existing sans-serif stack. Status colors convey success, warning or failure.

- One protected application shell replaces the dashboard-only sidebar and repeated
  page navigation. Current-page links, user sign-out, skip link and mobile native
  dialog drawer preserve authentication. The drawer supports Escape, focus return
  and native modal focus containment.
- Dashboard: real stored metrics, bounded recent events, backend connectivity,
  provider configuration and workspace actions. Configuration is not presented as
  proof of a successful provider call. No invented analytics or charts.
- Playground: saved conversations, distinct user/assistant panels, collapsible
  provider/model/tool controls, retained retry/approval/resolution flows, composer
  counter and safe Markdown subset. Fenced code is copyable; HTML and links remain
  escaped text. Raw HTML, image loading and model-controlled navigation are not
  supported. Existing sessions visibly retain their saved model when the deployment
  default changes.
- Sandbox: six-language selector and runtime/auto-policy status, highlighted editor
  with line-number gutter and horizontal scrolling, terminal-style result display,
  compile diagnostics and retained history/approval controls.
- Monitoring: real status badges, stronger metric/event surfaces and existing
  bounded WebSocket activity, approval history and audit views.
- Settings/profile: consistent provider cards and identity grid, existing Google
  connection workflow and no fake configuration controls.
- Login/register: bordered dark authentication panel, blue hard shadow, existing
  validation/password visibility and Google sign-in behavior.

Shared components are in `components/ui.tsx`; `workspace-nav.tsx` owns the shell
navigation. Layout behavior lives in `globals.css`. Responsive tests cover all
pages at 375, 768, 1024 and 1440 pixels, including mobile drawer keyboard behavior.
Animations respect reduced motion. Basic status and form labels remain accessible.

## Groq investigation: findings versus live verification

The traced path is Playground `send` → same-origin `agentApi`/`protectedApi` →
Next.js `/api/:path*` rewrite → authenticated FastAPI agent routes → saved session
provider/model → LangGraph → `Providers.complete` → official Groq SDK → bounded
JSON parsing → redacted stored turn → frontend.

**Confirmed code-level defects:**

1. Every chat request previously required an additional `models.retrieve(model)`
   request to succeed. A failed model-detail lookup stopped execution before chat
   completion, even if chat supported the same identifier. A direct SDK completion
   does not make that lookup. Namespaced models such as `openai/gpt-oss-20b` must not
   be rejected solely on this extra endpoint's response.
2. Every `groq.NotFoundError`, including endpoint/resource lookup errors, was mapped
   to “The selected Groq model is unavailable. Check GROQ_MODEL.” This was not
   evidence that the configured model was unavailable.

**Fix:** completion itself is the authoritative availability check. Removed the
extra lookup, kept the selected model and scoped tool definitions, and retained
bounded responses, timeouts, no automatic retries/fallback and redirect denial.
The fixed origin remains `https://api.groq.com`. The installed official SDK adds
`/openai/v1` in its resource routes; adding it to the base would be incorrect.
A regression test asserts the actual final URL is exactly
`https://api.groq.com/openai/v1/chat/completions`.

Errors now distinguish credentials, permission denial, explicit model-not-found/
decommissioned codes, unknown API endpoint 404s, invalid parameters, failed tool
call generation, rate limits, transport failures, timeouts, service failures and
invalid responses. No provider message, failed generation, key, prompt or request
body is exposed through the mapping. Private `reasoning` fields are ignored.

Tests reproduce a model lookup returning 404 while completion succeeds. They also
exercise the authenticated API, real SDK serialization, actual LangGraph calculator
workflow, MongoDB conversation persistence and recovery after a provider error.
These use mocked Groq HTTP responses. **The exact cause on the user's Mac remains
unconfirmed without its live request evidence.** No cloud Groq credential was
configured; no live Groq response is claimed. The user's working model/key were not
changed. Saved conversations are not migrated or silently reassigned.

## Security and performance

No authentication, CSRF, JWT, OAuth, ownership, rate-limit, signed-audit, MongoDB
schema, sandbox-policy or Docker execution implementation changed. The backend
still has no Docker socket; the dedicated executor remains mandatory. Production
screens consume real APIs; provider mocks exist only in explicit test fixtures.
The small Markdown renderer relies on React text escaping, with bounded provider
content. Font loading is local. Removing the model lookup eliminates one provider
HTTP round-trip per model step; no latency benchmark is claimed. Dashboard activity
fetches six records, on load/refresh rather than polling.

## Safe deployment to the existing Mac project

First bring these source changes into `feat/multilang-google-recovery` on the Mac.
Do not replace or print `.env.compose`, modify credentials, recreate MongoDB, remove
volumes, or omit the executor overlay. With Colima running and selected:

```sh
cd ~/Documents/GitHub/AgentShield-AI
git status --short
git branch --show-current
docker compose --env-file .env.compose -p agentshield-ai-v7 \
  -f compose.yaml -f compose.executor.yaml config --quiet

docker compose --env-file .env.compose -p agentshield-ai-v7 \
  -f compose.yaml -f compose.executor.yaml \
  up --build --no-deps -d --wait backend frontend

docker compose --env-file .env.compose -p agentshield-ai-v7 \
  -f compose.yaml -f compose.executor.yaml ps
```

Only backend/frontend need rebuilding for this change. MongoDB and the executor
remain running; do not create another Compose project. Reload the browser. In
Playground create a **new** Groq conversation and confirm the Model control shows
`openai/gpt-oss-20b` when that is your configured default. Existing conversations
retain their original model by design.

Verify these prompts in that conversation:

1. `Hello! Reply with one sentence.`
2. `What is 12 + 8?`
3. `Calculate (12 + 8) / 2 using the calculator.` (calculator enabled)
4. `Why should tools have least privilege?`

Inspect the calculator timeline, reload the saved conversation, and verify the
messages persist. Report safe user-facing error text/status if a request fails;
never paste keys, cookies, OAuth query strings or raw provider request bodies.
A live Google callback/linking flow remains a separate manual check. Keep the
existing Colima isolation validators for real sandbox checks; mock tests do not
prove runtime isolation.

## Reproducible automated checks

Use only the dedicated test MongoDB, never the application's database:

```sh
docker start agentshield-mongo-tests
PYTHONPATH=backend TEST_MONGODB_URI=mongodb://127.0.0.1:27018 \
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 backend/.venv/bin/python \
  -m pytest backend/tests -q --tb=short
npm --prefix frontend run lint
npm --prefix frontend run typecheck
TEST_MONGODB_URI=mongodb://127.0.0.1:27018 \
  npm --prefix frontend run test:e2e
docker stop agentshield-mongo-tests
```

Playwright runs the Next.js production build before browser testing. Its app uses
real isolated MongoDB/authentication and explicitly mocked model/container execution.
The cloud run uses `/usr/bin/chromium` via `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH`.
Responsive screenshots are generated under `frontend/test-results/design-*` and
are ignored by Git. They depict synthetic test accounts, not production analytics.

## Final verification (2026-11-06)

| Check | Result | Scope |
| --- | --- | --- |
| Backend suite | **401 passed, 16 skipped** | Real isolated MongoDB/auth/security; mocked Groq and container execution where required |
| Frontend ESLint | **PASS** | Zero lint warnings |
| TypeScript checks | **PASS** | Next route generation and `tsc --noEmit` |
| Next.js production build | **PASS** | Built and served by Playwright's configured web server |
| Browser suite | **27 passed** | Includes authentication, Google UI/link fixtures, tools, approvals, auto execution, WebSockets, all-page responsive checks and escaped Markdown |
| Viewports | **PASS** | 375, 768, 1024, 1440; no document horizontal overflow; mobile Escape/focus return |
| Compose configuration | **PASS** | Placeholder configuration only; backend has no Docker socket; executor has no TCP exposure |
| Credential-pattern scan | **PASS** | Changed-source heuristic scan; not a guarantee |
| Real sandbox validator | **BLOCKED** | Cloud `CGROUP_V2_UNAVAILABLE`; zero submitted programs executed |
| Live Groq | **NOT VERIFIED** | Cloud has no configured Groq key or access to the Mac deployment |
| Live Google OAuth callback | **NOT VERIFIED** | Mocked protocol/UI tests are not live consent/callback validation |
| Mac deployment | **NOT UPDATED** | No second Compose stack, secret rotation, volume deletion or application database change |

The retained 16 real-Docker pytest cases were skipped, not passed. Existing
Starlette/AnyIO and Uvicorn WebSocket deprecation warnings remain. No dependencies
were added; font assets and licenses are included. The isolated cloud test MongoDB
was stopped after verification. Git changes were not committed or pushed during
this task.

Important changed files: `backend/app/agents/providers.py`,
`backend/tests/test_groq_request_path.py`, `backend/scripts/browser_test_app.py`,
protected/root frontend layouts, `globals.css`, the eight page components,
`workspace-nav.tsx`, `ui.tsx`, `safe-markdown.tsx`, `code-editor.tsx`, local fonts,
updated navigation regression selectors, `frontend/tests/design.spec.ts`, README
and this guide. Existing authentication, database and sandbox backend modules and
both Compose files are unchanged.
