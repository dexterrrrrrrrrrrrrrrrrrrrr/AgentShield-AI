# Dedicated local sandbox executor

## Why Compose previously reported unavailable

The default Phase 7 Compose backend intentionally sets `SANDBOX_ENABLED=false` and has no Docker socket. Standalone Colima checks validate the local runtime, not connectivity from that backend. The opt-in `compose.executor.yaml` supplies the missing execution plane; the default stack stays disabled.

## Architecture and trust

Browser -> existing Next.js/FastAPI API -> JWT/CSRF/ownership/policy/approval/audit -> private Unix HTTP socket -> trusted executor -> existing verified DockerAdapter -> isolated job.

The backend never receives a Docker socket or Docker TCP address. Only backend/executor mount the control-socket volume. The executor has no network interface beyond loopback, publishes no TCP port, has no database/provider credentials, and exposes only liveness, an authenticated challenge, signed readiness, and signed execution operations. `/health` means the process is alive, not that execution is safe. User-facing readiness invokes the actual language-specific effective isolation probe through the executor.

A separate shared credential authenticates the caller. Execution/readiness requests have HMAC-bound endpoint/body, an ephemeral executor epoch, a timestamp and a one-use nonce. A bounded 128-entry replay cache rejects excess admission rather than evicting live entries. Restart changes the epoch, so captured requests cannot replay after restart. A configuration hash binds the fixed language recipe, image identity and every resource limit; mismatched backend/executor configuration fails closed. Strict schemas reject caller-selected images/flags/mounts. Responses are bounded and allowlisted before entering execution records. No automatic execution retry occurs after timeout/disconnect; uncertain work latches the existing fail-closed recovery state.

The executor retains one worker/one execution, the existing Docker isolation probes and cleanup, UID 65534 jobs, read-only rootfs, network none, private namespaces, dropped capabilities, seccomp, no-new-privileges, no swap, CPU/memory/PID/time/output bounds and noexec/nosuid/nodev tmpfs. Job containers receive neither control sockets, Docker sockets, host mounts nor credentials. Approval fingerprints and language image identities are unchanged.

**Remaining boundary:** Docker socket membership gives the trusted executor broad daemon/VM authority; a read-only socket mount does not restrict Docker API methods. This service is not a generic Docker proxy, but compromising its process can compromise that daemon. The executor trusts the public backend's authorization decisions: compromise of the backend and its credential could submit new executions under the executor's fixed restrictions. Isolation of services does not make the backend an untrusted caller or certify hostile multi-tenant safety. Use a dedicated Colima VM/worker host; public hostile-code deployments need stronger worker isolation and further review.

## Existing Mac deployment: exact commands

Use the feature branch containing this change and preserve all existing `.env.compose`, MongoDB volumes, JWT/audit keys and OAuth/provider configuration. First stop the native backend or other sandbox activity; leave Colima running. From the repository root:

```sh
python3 scripts/init-executor-secret.py
colima ssh -- stat -c '%g' /var/run/docker.sock
```

The secret helper refuses existing directories/files. The token is container-readable within a host directory created mode 0700; keep that directory private and ignored. Do not paste its contents into terminals/chat. For later deployments reuse it; deliberate rotation requires restarting backend and executor together.

Add the reported numeric group as `SANDBOX_DOCKER_GID` to the existing ignored `.env.compose`. Add the three immutable pins you already validated: `SANDBOX_NATIVE_IMAGE`, `SANDBOX_JAVA_IMAGE`, `SANDBOX_NODE_IMAGE`. Preserve their exact `sha256:` values. They must exist in this same Colima daemon. If needed, the existing `scripts/build-sandbox-runtimes.py` builds each family independently. Set any previously validated `SANDBOX_MEMORY_MB`, CPU/PID/time/output limits in this same file; the override applies identical values to both services. The default memory is 128 MiB, configurable up to the existing 256 MiB maximum.

```sh
docker context use colima
docker compose --env-file .env.compose -f compose.yaml -f compose.executor.yaml config --quiet
docker compose --env-file .env.compose -f compose.yaml -f compose.executor.yaml up --build -d --wait
docker compose --env-file .env.compose -f compose.yaml -f compose.executor.yaml ps
```

Only frontend localhost:3000 is published by default. Open Sandbox, select a language, and refresh readiness. A healthy executor plus unavailable readiness is a real failure, not a reason to loosen controls. The executor's socket group must come from the VM, not the macOS host. Do not expose the Docker daemon on TCP or mount it into the backend as a workaround. Keep the override present in subsequent Compose commands; running only the default file restores the intentionally disabled backend configuration.

The public backend uses `SANDBOX_TRANSPORT=executor`; native deployments retain the default local adapter. No changes to authentication, MongoDB schema, OAuth or agent APIs are needed. Existing sessions/tools/approvals/monitoring keep using the same public service.

## Actual validation

With no active executions, retain the existing local validators:

```sh
bash scripts/validate-phase4-colima.sh
PYTHONPATH=backend backend/.venv/bin/python backend/scripts/validate_multilanguage.py \
  --docker-url "$(docker context inspect colima --format '{{.Endpoints.docker.Host}}')"
```

Then test the deployed path, preferably on an isolated validation stack. This creates one synthetic account and audit/history records per language, respecting per-user execution quotas. Each invocation explicitly approves only its fixed harmless hello-world request:

```sh
for language in python c cpp java javascript typescript; do
  backend/.venv/bin/python scripts/validate-deployed-sandbox.py \
    --base-url http://localhost:3000 --language "$language" || break
done
```

PASS requires an actual successful response through public authentication -> pending approval -> backend -> private executor -> real container -> stored result. A BLOCKED response sends no program. Six registrations fit the default IP quota, but rapid repeated runs can legitimately hit authentication rate limits; wait for the configured window instead of weakening quotas. Google/Groq credentials are unnecessary for these fixed programs.

Stop without deleting data:

```sh
docker compose --env-file .env.compose -f compose.yaml -f compose.executor.yaml down
```

Do not use `down -v` for persistent deployments. In uncertain execution failures, inspect sandbox-labeled containers and the existing MongoDB blocked latch via the documented trusted-operator recovery workflow. Never clear the latch or replay an approval merely to obtain readiness.

## Verification evidence

Final backend/security run: **350 passed, 16 real-Docker tests skipped**. Both images built, Compose validated, and all four services were healthy. Actual container inspection confirmed the backend lacks a Docker socket and the non-root read-only executor has no network attachment. Automated tests cover six-language remote dispatch, actual existing auth/CSRF/approval/persistence with a mocked execution adapter, HMAC rejection, replay/restart rejection, configuration mismatch, oversized input, response-field injection and fail-closed transport behavior. These are not real Docker isolation tests.

The cloud Compose stack was built and all four services became healthy. An actual registered/logged-in request through the public frontend/backend reached the executor, which inspected the daemon and returned `CGROUP_V2_UNAVAILABLE`. **Operational execution is BLOCKED**, because this daemon reports cgroup v2 with driver `none`; zero submitted programs ran. Both standalone validators likewise stopped at readiness. Earlier user-reported Colima 12/12 and 6/6 results do not verify this newly deployed path. Do not call the Sandbox operational until the deployed validator succeeds on the target runtime.

## Optional local automatic execution

Approval remains the Compose default. For the direct Code Sandbox compiler UX,
see [trusted-local auto execution](sandbox-auto-execution.md). The dedicated
executor and isolation checks are unchanged. Use `--policy auto` only after
explicitly configuring that mode; the validator otherwise expects approval.
