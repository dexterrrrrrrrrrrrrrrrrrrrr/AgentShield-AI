# Phase 4: fail-closed sandbox implementation

**Implementation validation is separate from real isolation validation.** The managed runtime is rootless without delegated cgroups: effective memory was 32 GiB instead of 128 MiB, CPU was four instead of one, and PIDs were unlimited instead of 32. Real untrusted-program tests are BLOCKED here. The production adapter returns `SANDBOX_UNAVAILABLE`; no submitted program is started. The managed daemon is not modified. Colima/M2 has not been validated by this task.

## Architecture and boundaries

Authenticated API → deterministic policy → optional immutable human approval → distributed admission lease → sandbox manager → Docker adapter. LangGraph's `python_sandbox` tool invokes that same service with the authenticated owner and current agent session. There is no model-facing Docker API, host code evaluator, host shell command, image selector, volume selector, or environment selector.

The API process uses the Docker SDK over an explicitly configured **local Unix socket**. Access to this socket is powerful; keep the backend trusted and private. Do not expose Docker's management API on TCP or mount its socket into execution containers. A separate container/microVM management service is recommended before any hostile multi-tenant Internet deployment. The adapter interface (`readiness`, `execute`) can support a future gVisor/Firecracker implementation; those are not implemented in this phase.

Default settings: sandbox disabled; policy `approval`; 128 MiB RAM with no swap; at most one CPU; 32 PIDs; 10 seconds of program runtime; one live execution across backend workers; 64 KiB combined raw stdout/stderr; 32 KiB UTF-8 code. Environment validators cap settings at 256 MiB, one CPU, 64 PIDs, 15 seconds, 64 KiB output and 32 KiB code. The API body envelope permits JSON escaping overhead while the code byte limit remains strict. Request limits are operator-controlled, not request fields. Five sandbox operations per user per five-minute window by default; API and shared service counters cover direct requests, approvals, and agent calls.

Every container uses the pinned multi-platform Python image in `app/sandbox/policy.py`, numeric UID/GID 65534, read-only root, network `none`, dropped capabilities, no-new-privileges, private IPC/cgroup namespaces, default private PID namespace, Docker's default seccomp profile, and a small noexec/nosuid/nodev `/tmp` tmpfs. It has no host mounts, no environment forwarding, no proxy configuration injection, no stdin, no TTY, no core dumps, and no Docker log driver output. No application secrets enter the container. The image is never pulled automatically by requests. Its digest fixes content; it does **not** establish that its OS packages are vulnerability-free. Review/update the pinned image deliberately.

Readiness checks daemon support, local image availability, inspected container restrictions and a fixed harmless in-container probe of **effective** cgroup-v2 memory/PID/CPU settings, root filesystem mount flags, network routes, non-root UID, dropped capabilities, seccomp and NoNewPrivs. Unavailable/unknown controls fail closed. Readiness is rechecked before each execution. The same checks run again inside the execution container before the submitted code is interpreted, preventing reliance only on a previous probe. The only `exec` used for submitted code is inside the container's fixed launcher, never on the host. Python code may invoke programs inside its restricted container; there is no unrestricted shell tool or host command interface.

Output uses a bounded Docker multiplexed stream. Excess output terminates execution; invalid UTF-8 is discarded. Stored output is additionally redacted and capped by the existing redactor (12,000 characters per stream). A timeout kills the container, and force removal kills descendants. A cancellation waits for the shielded lifecycle worker's cleanup before releasing capacity. Cleanup failure disables that manager and latches a shared MongoDB block; another worker cannot silently continue. Restart alone does not clear the shared block.

**Limits:** Docker shares a kernel and does not guarantee complete isolation from malicious code. Kernel/runtime vulnerabilities, side channels, daemon compromises, and physical process/VM termination remain risks. SIGKILL/power loss can interrupt cleanup; inspect/remove only this application's labeled containers during operator recovery before clearing a shared block. There is no background recovery worker in this phase. Do not treat passed mocks or a successful preflight as proof against container escapes. Real M2 resource, timeout, cleanup and isolation tests remain required.

## Policy and approvals

`ALLOW`, `DENY`, and `REQUIRE_APPROVAL` are independent of model text. Authentication, session ownership, fixed tool name, code byte size, resource configuration, user quota, readiness and operator permission mode are checked. Default permission is approval; `deny` never runs, and `allow` is an explicit operator choice that still requires all isolation checks. The model cannot approve requests, change policy, change limits, or choose Docker controls.

An approval is bound to owner, exact code, agent session, tool, image digest, limits and policy revision using a SHA-256 canonical-request fingerprint. The UI retrieves the stored request and displays its code, hash and limits. Approval requires an authenticated CSRF-protected POST with `approve: true` and that hash. An atomic expiry/owner/hash/state comparison consumes it once. Changes to code/configuration require a new request. Cross-user approval, replay, expired approvals and implicit approval are rejected. Approval is consent to that exact request, not a bypass of subsequent readiness checks. Approvals expire after five minutes by default; their code is removed upon consumption and deleted by MongoDB TTL after expiry. TTL deletion is asynchronous, so authorization checks expiry explicitly.

`execution_logs` stores owner, agent session, tool, policy decision, status, UTC timestamps, duration, exit code, bounded/redacted output, limits, hash and error category, **not submitted source**. Logs have owner/time indexes and a default seven-day retention TTL. `sandbox_approvals` temporarily stores the exact pending source for authorized review and an expiry index. `sandbox_locks` holds a global infrastructure lease/block, not user conversation data. These writes are not multi-document transactions; interrupted operations can leave an incomplete log or consumed approval. Retry requires a new request and cannot replay the consumed approval.

Do not submit credentials or sensitive data. Configured signing/provider keys and recognizable Groq keys in source are rejected. Output redaction is best effort, not comprehensive data-loss prevention. Docker administrators can inspect transient container arguments while a container exists; this is another reason never to submit secrets.

## API

All routes require the existing JWT/server session. Writes additionally require allowed Origin plus signed, session-bound CSRF cookie/header. Owner filters protect every execution/approval/agent-session query; global lease metadata is service-only.

| Method | Endpoint                                    | Purpose                                                                                |
| ------ | ------------------------------------------- | -------------------------------------------------------------------------------------- |
| GET    | `/api/sandbox/readiness`                    | `ready` and `READY` / `SANDBOX_UNAVAILABLE`                                            |
| POST   | `/api/sandbox/execute`                      | `{code, agent_session_id?}`; return a denied, unavailable, pending or completed record |
| GET    | `/api/sandbox/executions?offset=0&limit=20` | Paginated owner history                                                                |
| GET    | `/api/sandbox/executions/{id}`              | Owner result and exact pending approval request                                        |
| POST   | `/api/sandbox/approvals/{id}`               | `{approve:true, request_hash}`; atomically approve and attempt execution               |

Execution failures are represented by `status` and `error_category` in execution records; HTTP errors cover authorization, malformed requests, quota and approval errors. The `/sandbox` page displays policy, approval review, status, stdout, stderr, exit code, duration, errors and paginated history. Unavailable readiness disables the Execute button without breaking auth, dashboard or existing safe tools. Model-generated sandbox requests appear in this same history and require the same approval flow. Reload the page to refresh readiness; there is no polling loop.

## Local MacBook Air M2 / 8 GB validation (not yet executed)

Use free, open-source Colima, Lima and Docker Engine/CLI. Do not install a paid authentication/database service or assume Docker Desktop is required.

```sh
brew install colima docker
colima start --runtime docker --arch aarch64 --cpu 2 --memory 3 --disk 20
docker context use colima
docker info --format '{{.CgroupDriver}} {{.CgroupVersion}} memory={{.MemoryLimit}} cpu={{.CPUCfsQuota}} pids={{.PidsLimit}}'
```

Require cgroup v2, a real driver, and all three controllers. A rootless runtime is acceptable only when controllers are properly delegated and effective checks pass. Stop if these properties are missing; do not remove limit flags or enable privileged mode as a workaround. Inspect the image's architecture/digest after pulling the exact reviewed reference:

```sh
docker pull python@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30
docker image inspect python@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30 --format '{{.Architecture}} {{json .RepoDigests}}'
export SANDBOX_DOCKER_URL="unix://$HOME/.colima/default/docker.sock"
```

The backend SDK deliberately does not follow `DOCKER_CONTEXT` or forward Docker client proxy defaults. Explicitly set the matching socket. Prepare native MongoDB and the ignored backend environment as described in README, preserving the existing signing key. From `backend/`, verify only the fixed trusted probe first:

```sh
.venv/bin/python -m scripts.check_sandbox
```

Exit 0 / `READY` is required. Exit 2 / `SANDBOX_UNAVAILABLE` means **do not run submitted code**. Only after success, opt into harmless integration programs:

```sh
RUN_SANDBOX_INTEGRATION=1 .venv/bin/python -m pytest -q tests/test_sandbox_real.py
```

These tests independently gate every program with readiness and cover success, syntax/runtime errors, a bounded infinite-loop timeout, memory allocation rejection, non-root UID, read-only root and writable tmpfs, denied network connection, denied UID elevation, output truncation, and cleanup. Effective CPU/PID limits are checked by the probe. Real tests are off by default and report skipped/blocked, never a mock-based isolation pass. Repeat the normal backend and browser regression suites too.

After real tests pass, set `SANDBOX_ENABLED=true` and `SANDBOX_POLICY=approval` in the backend process environment. Run the backend and frontend using the README commands. All code still goes through fresh checks per execution. Do not enable real execution on the current managed cloud daemon.

For cleanup/recovery, first stop the backend and any tests, then inspect containers:

```sh
docker ps -a --filter label=agentshield.sandbox=true
# Remove only individually reviewed execution container IDs, never MongoDB:
docker rm -f <execution-container-id>
colima stop
```

Never mount host home, SSH/cloud credentials, env files, Docker sockets, or MongoDB volumes into execution containers. Do not delete the MongoDB data volume for sandbox cleanup. If a shared `sandbox_locks` record has `blocked: true`, keep execution disabled until an operator confirms no sandbox containers remain and fixes the daemon. Only then clear the `blocked` field on the single infrastructure record `_id: execution`, preserve other data, restart the backend and rerun readiness plus real tests.
