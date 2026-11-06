# Phase 8 implementation and recovery report

## Release status

**IMPLEMENTED / TESTED with external verification blocked.** Work was recovered from the original workspace, not regenerated. The baseline remains `c9cfdd40b6df725d5a55cceb6efb7a64914e2e6e`. No previous upgrade commit existed. Changes are on `feat/multilang-google-recovery`; do not merge to main until real runtime validation and review are satisfactory.

Remote main was fetched and found at `0b3d5cc18aa87da875615133017b72a979de3ab0` with an unrelated Groq provider edit. That change is not overwritten or silently incorporated. Reconcile it and rerun regression tests before merging. GitHub Actions status for the pushed feature commit is reported separately; this static report records local evidence.

## Implemented

- Fixed registry for Python 3.12.16, GCC/G++ 14.2.0, OpenJDK 21.0.13, Debian-maintained Node 20.19.2 and TypeScript 5.9.3. Separate native, Java and Node image builds with immutable operator pins, no request-selected images/flags, no automatic downloads.
- Isolated compilation/execution with independent deadlines, bounded combined raw-byte output, stdin, compiler diagnostics, cleanup, and host-authoritative Docker exit status. Python API/tool compatibility retained.
- Language-aware API/history/filtering, exact content-bound human approvals, live owner/tool checks, execute_code LangGraph integration, signed language/status audit metadata and original-turn finalization.
- Existing Sandbox UI extended with six templates, highlighted editing, stdin, backend-confirmed results, compiler output, history and readiness states.
- Optional Google code-flow OIDC with S256 PKCE, browser-bound atomic state, nonce, RS256/JWKS identity checks, fixed provider endpoints and bounded requests. Stable subject identities, unique partial index, additive state TTL, explicit session-bound linking, no email-based automatic merge and no fabricated passwords.
- Existing JWT/HttpOnly/CSRF/revocation infrastructure reused. Login/Register/Profile support Google redirects, setup errors, provider metadata and explicit linking. Password login remains available.
- Callback query redaction and disabled access logging in supplied launchers; Google secret included in shared redaction. External proxies must independently omit sensitive query strings.

## Executed evidence

| Check | Result |
| --- | --- |
| Full backend/security suite, plugin autoload disabled, real disposable MongoDB 7 | **TESTED: 327 passed, 16 skipped**; final run 39.11 seconds |
| Browser suite | **TESTED: 24 passed** in 53.8 seconds; real HTTP/cookies/MongoDB/WebSockets with explicit provider/runtime fixtures |
| ESLint, TypeScript, production Next.js build | **PASS** |
| pip check, pip-audit, npm audit | **PASS**, no known dependency advisories reported |
| Three language runtime image builds | **PASS** on cloud Linux x86_64; builds verify fixed toolchain versions, not submitted-code isolation |
| Backend/frontend image builds, Compose config, all three service health checks | **PASS** |
| Real Compose HTTP smoke | **PASS**: register/login/protected dashboard/persisted session/fail-closed denial/signed audit/monitor/logout |
| Recognizable credential-pattern scan / patch preservation | **PASS**; no detected credentials, unrelated phase5.patch unchanged |
| Real sandbox checks | **BLOCKED**: cgroup v2 driver `none`; validator returned SANDBOX_UNAVAILABLE with empty tests list |
| Real sandbox pytest | **SKIPPED**: original 10 plus six new language cases; skipped is not passed |
| Live Google sign-in / consent / account linking | **NOT VERIFIED**: operator credentials and real Google flow required |
| Mac ARM64 runtime behavior, effective cloud cgroup enforcement, public production deployment | **NOT VERIFIED** |

The mocked runtime phase tests cover all six registered languages, compilation stopping before execution, guard refusal before source staging, timeout/output outcomes and cleanup. Existing tests cover auth/authorization, isolation configuration, approval replay, concurrency and Docker failure behavior. These do not prove a compiler can safely execute hostile source. Opt-in real tests and the local validators must run on the target host.

## Recovery fixes

The interrupted apt build could not read a default mode-0400 temporary public CA mount as its unprivileged downloader. The mount now uses mode 0444; TLS and Debian signature checks stay enabled and no CA is copied into image layers. Java and Node compiler/runtime dependency pins were updated together to available matching security-update packages. Native Python stdin execution now uses an absolute interpreter path. Compiler/runtime output accounting preserves raw-byte limits across phases.

Recovered tests needed corrections: provider label `password` must not be confused with exposed password fields/values; the alias-conflict fixture must actually send both aliases; a multi-decision test must have sufficient test-only quota; monitoring must explicitly allow its sandbox tool; text and accessible alert selectors must match the updated interface. No test or security check was disabled.

## Local setup and remaining validation

Follow [Google setup](google-auth.md) for Google Cloud consent, Web application credentials and the exact local callback `http://localhost:3000/api/auth/google/callback`. Set all three GOOGLE_* variables securely, preserving JWT/audit keys and existing account data. Test actual Google login, returning identity, cancellation, conflict, explicit linking and logout before describing it as operational.

Follow [sandbox setup](multilanguage-sandbox.md) to build each runtime separately, copy printed immutable pins into the existing native backend env, and select the local Colima Unix endpoint. Run:

```sh
bash scripts/validate-phase4-colima.sh
PYTHONPATH=backend backend/.venv/bin/python backend/scripts/validate_multilanguage.py \
  --docker-url "$(docker context inspect colima --format '{{.Endpoints.docker.Host}}')"
```

The six-language validator checks all readiness gates before any program. It supplements the original Python isolation suite. Larger programs may exceed the deliberately small workspace/heap/PID limits. No Mac memory/latency benchmark is claimed. For the normal app, use the README native startup or existing Compose commands. Compose keeps execution disabled and has no Docker socket in the backend.

Docker containers are not perfect hostile-code isolation. Public execution needs dedicated trusted workers/VMs or a stronger isolation design. Signed records depend on signing-key/database trust and do not prevent administrator deletion. Secret redaction remains best effort. New fingerprints safely invalidate old pending approvals; resubmit them. Standalone Mongo multi-document interruption can leave partial records, but must not restore consumed authorization. Real per-language adversarial/resource behavior and external OAuth configuration remain release gates.

## Changed files

Modified:

- `.env.example`
- `README.md`
- `backend/Dockerfile`
- `backend/app/agents/api.py`
- `backend/app/agents/engine.py`
- `backend/app/agents/tools.py`
- `backend/app/auth.py`
- `backend/app/config.py`
- `backend/app/database.py`
- `backend/app/guards.py`
- `backend/app/main.py`
- `backend/app/monitoring/events.py`
- `backend/app/sandbox/api.py`
- `backend/app/sandbox/manager.py`
- `backend/app/sandbox/policy.py`
- `backend/app/sandbox/service.py`
- `backend/app/schemas.py`
- `backend/requirements.txt`
- `backend/scripts/browser_test_app.py`
- `backend/tests/conftest.py`
- `backend/tests/test_auth.py`
- `compose.yaml`
- `frontend/next.config.ts`
- `frontend/src/app/(protected)/profile/page.tsx`
- `frontend/src/app/login/page.tsx`
- `frontend/src/components/auth-form.tsx`
- `frontend/src/components/dashboard.tsx`
- `frontend/src/components/monitoring.tsx`
- `frontend/src/components/playground.tsx`
- `frontend/src/components/sandbox.tsx`
- `frontend/src/components/settings.tsx`
- `frontend/src/lib/auth-client.ts`
- `frontend/tests/monitoring.spec.ts`
- `frontend/tests/phase7.spec.ts`
- `frontend/tests/playground.spec.ts`
- `frontend/tests/sandbox.spec.ts`
- `scripts/run-backend.sh`

Created:

- `backend/app/oauth.py`
- `backend/app/sandbox/multilang.py`
- `backend/app/sandbox/registry.py`
- `backend/scripts/validate_multilanguage.py`
- `backend/tests/test_google_oauth.py`
- `backend/tests/test_multilanguage_api.py`
- `backend/tests/test_multilanguage_real.py`
- `backend/tests/test_runtime_phases.py`
- `docs/google-auth.md`
- `docs/multilanguage-google-plan.md`
- `docs/multilanguage-sandbox.md`
- `docs/phase8-completion.md`
- `frontend/src/components/code-editor.tsx`
- `frontend/src/components/google-button.tsx`
- `frontend/src/components/profile.tsx`
- `frontend/src/lib/languages.ts`
- `frontend/tests/upgrades.spec.ts`
- `sandbox/runtime/.dockerignore`
- `sandbox/runtime/Dockerfile`
- `scripts/build-sandbox-runtimes.py`
