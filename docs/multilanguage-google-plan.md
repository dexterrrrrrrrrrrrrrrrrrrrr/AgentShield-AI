# Multi-language sandbox and Google authentication upgrade

Baseline: `c9cfdd40b6df725d5a55cceb6efb7a64914e2e6e`. Existing tracked tree clean; unrelated `phase5.patch` remains untouched.

## Inspection findings

The FastAPI factory and bounded middleware live in `backend/app/main.py`. Authentication in `auth.py` shares signed CSRF/JWT cookies and live MongoDB sessions through `security.py`; user projection is in `schemas.py`, indexes in `database.py`. Password-only login currently assumes every user has a password hash and must safely support external-only identities.

Sandbox `manager.py` owns Docker lifecycle and effective isolation probes. `policy.py` binds exact requests and limits; `service.py` owns expiring atomic approvals, quotas, logs and fail-closed locks. Agent `tools.py`, `engine.py` and `api.py` enforce schemas, permissions and approval-aware original-turn finalization. Monitoring signs fixed owner-scoped metadata. The Python API and old stored approval fingerprints need compatibility consideration when adding fields.

The existing Next.js Sandbox, Playground, Monitoring, auth form and Profile share protected API/CSRF/session utilities. These are extended in place. Compose deliberately excludes a Docker socket and disables execution. Native trusted-host orchestration remains the supported sandbox deployment mode. Existing MongoDB 7 CI startup and application isolation stay intact.

Observed cloud Docker: version 29.9.2, cgroup v2, driver `none`. This cannot establish effective sandbox resource enforcement. Real submitted-code execution must stay blocked. No Google credentials are configured; real Google login requires operator setup and permitted provider connectivity.

## Incremental implementation

1. Add a fixed server language registry and isolated runtime runners. Preserve Python compatibility; no request-selected commands/images. Compile inside the sandbox, with separate deadlines and bounded output. Retain noexec temporary storage and all existing isolation checks.
2. Carry language, bounded stdin and compilation results through strict API validation, content-bound approvals, ownership, LangGraph permissions and metadata-only monitoring.
3. Upgrade Sandbox editor/templates/history/approvals with existing UI components and bounded state.
4. Add optional Google authorization-code OIDC with S256 PKCE, nonce, browser-bound single-use state, fixed endpoints and strict ID-token validation. Reuse existing session issuance. Require authenticated explicit linking for email conflicts; never auto-merge or invent passwords.
5. Add additive MongoDB identity indexes/state TTL and safe user projections. Extend login/register/profile with real OAuth redirects and actionable configuration/error states.
6. Run focused tests after each layer, then all backend/frontend checks, dependency audits, Compose validation/builds and security review. Keep mocked provider/runtime tests distinct from actual Docker/OAuth verification.
7. Document operator runtime builds/pins, Colima checks, Google Console configuration, migration behavior, security boundaries and exact evidence.

## Security invariants

No user code runs on the host or application containers. No runtime auto-pulls, host mounts, socket exposure, external user-selected network targets or privileged containers. No approval replay, cross-owner requests, automatic email linking, plaintext passwords or persisted provider tokens. Callback codes and secrets must not enter access logs. Unknown/unverified runtime controls remain `SANDBOX_UNAVAILABLE`.

## Recovery outcome

The interrupted work was recovered in place on the feature branch. See [phase8-completion.md](phase8-completion.md) for executed evidence, corrected build pins and outstanding real-runtime/OAuth gates. Main remains untouched.
