# Phase 7 integration audit (before implementation)

Baseline: `3f7a1f865476a4717ad605d4477336e027374491`, main; fetched remote matches local HEAD. Tracked files clean; the pre-existing untracked `phase5.patch` is preserved. Existing evidence is 183 backend passes / 10 opt-in Docker skips, 10 browser passes, CI run #9 success, and the user's separate 12/12 Colima report. No new validation is claimed by this audit.

Scope reviewed: repository layout and README/phase/security/sandbox docs; frontend pages/components/clients/test fixtures; FastAPI auth, agent, sandbox and monitoring routes; LangGraph workflow/provider/tool boundaries; MongoDB collections/indexes; signed audit delivery and connection leases; Docker lifecycle/readiness; Compose and GitHub Actions. Findings below are concrete code/integration gaps. Existing auth/CSRF/rate/ownership/policy/cgroup checks remain the boundaries.

| Priority | Finding and evidence | Phase 7 disposition |
| --- | --- | --- |
| P0 | `agents/engine.py` serializes `pending_approval` as an ordinary tool response and continues the model; `sandbox/service.py` has no linked original turn resolution. A turn can claim completion before the human decision. Phase 5 docs explicitly acknowledge this gap. | Persist a truthful waiting state with an internally bound turn/execution link. Add single-use authenticated/CSRF resolution after a real decision, using actual stored results and no tools during finalization. No automatic code replay or long-lived HTTP wait. |
| P0 | Sandbox denied/unavailable outcomes can be treated as ordinary successful tool data. | Stop with truthful failed/blocked state and appropriate monitoring events. |
| P1 | Session lease finalization filters only owner/session; a stale finalizer could clear a newer recovered lease. | Bind acquisition/release to an execution holder identifier. |
| P1 | Monitoring browser retries stop on4401/4403 but pre-upgrade denial often appears1006. Logout/expiry are not shared cancellation signals. SessionProvider checks only mount/focus/pageshow. | Add safe expiry metadata, session invalidation signals, auth recheck after handshake denial, bounded retries and reconnect synchronization; never keep reconnecting after confirmed auth failure/logout. |
| P1 | Compose only starts MongoDB8, publishes27017, and has an existing `mongo-data` volume; no app images/health/dependencies/networking exist. | Add non-root app images and isolated MongoDB7 deployment using a new volume. Never reuse/downgrade Mongo8 data. No public backend Docker socket; Compose sandbox stays disabled and its limitation is explicit. |
| P1 | Deployment has no trusted-host enforcement and frontend API target is build-bound. | Add validated trusted host configuration, production cookie/HTTPS checks retained, consistent build/runtime proxy configuration and health checks. |
| P1 | Dashboard counts/status cards are static descriptions; Settings is a placeholder. Playground hardcodes every tool for new sessions. | Use existing summary/provider/readiness APIs; expose actual per-session configuration through existing SessionInput, avoiding duplicate configuration services. |
| P2 | Sandbox detail can show an expired approval request until physical TTL deletion. Immediate agent POST response omits persisted duration. | Explicit expiry filtering and consistent response metadata. |
| P2 | Child pages lack consistent navigation/logout; stale phase labels and “no sandbox available” text misdescribe current behavior. | Shared navigation and truthful loading, unavailable, waiting and empty states, preserving the design system. |
| P2 | Monitoring has no older-audit UI despite paginated API; approval pages can merge duplicates; sandbox readiness has no refresh and lacks rejection controls. | Bounded dedup/pagination, explicit readiness retry, and unified safe API handling/approval controls. |
| P2 | Conversation deletion has no confirmation; history over20 turns risks hiding newer messages if later pages are not loaded. | Confirmation and bounded latest/older-history loading. |
| P2 | Documentation still describes Phase3 reserved logs/Mongo8/no sandbox and has no cohesive deployment/testing guide. No reproducible measurement harness exists. | Replace current architecture/overview documentation, retain historical phase docs with clear superseding notes, add measured local workload report without invented benchmarks. |

## Preserved controls and implementation limits

- Preserve strict schemas, full-batch validation, live tool authorization, single-use content-bound approvals, signed audit checks, rate/admission limits, bounded feeds/queues, CSRF and user ownership.
- Preserve Docker manager/policy image digest, non-root, private namespaces, read-only root, no network, cgroup/time/output/PID bounds and cleanup. No socket mount in the public backend, no host code execution, no fake production provider.
- Preserve the MongoDB7/Ubuntu24.04 CI startup fix and all existing test coverage. Test fixture changes may add deterministic journeys but are never imported by production.
- Full malicious-tenant production isolation and a separate authenticated sandbox-orchestration service are not assumed complete. If not implemented safely, Compose explicitly disables sandbox and the full Colima demo uses the trusted native-host backend.
- Cloud runtime reports cgroup driver `none`; real submitted-code checks require the unchanged local Colima validator. Existing report filename is user-supplied evidence, not a report generated or revalidated here.

## Validation plan

Run the required plugin-autoload-disabled backend suite, frontend lint/type/build/browser suites, actual MongoDB7 failure/recovery and WebSocket journeys where practical, dependency audits and credential-pattern scans. Validate Compose, build app images, start/check local service health, exercise actual browser auth through Compose. Record every skipped/blocked external provider, macOS, runtime-security or deployment property separately. Use small logical commits after review; normal fast-forward pushes only.
