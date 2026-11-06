# Multi-language sandbox

The existing execution service supports Python, C, C++, Java, JavaScript and TypeScript through a fixed server registry. Python's original `python_sandbox` tool and `code` API remain available. The new `execute_code` tool accepts only `language`, `code` and optional bounded `stdin`. Unknown languages, arbitrary compiler flags, runtime paths, images, mounts and environment variables are rejected.

## Execution and security boundaries

Every request passes live authentication, ownership, the tool allowlist, deterministic policy, quotas and readiness. Approval mode stores a short-lived exact request; its fingerprint includes language, source, stdin, registry recipe, image identity and limits. Approval atomically consumes the owner-bound request and revalidates authorization/policy/readiness. Configuration changes invalidate pending approval. Pre-upgrade pending fingerprints must be resubmitted rather than executed under a changed recipe.

Compilation and execution occur only in a short-lived isolated container. The backend performs trusted Docker lifecycle operations, never compiles or executes submitted source. A job has separate compiler and runtime deadlines and a shared bounded output budget. Docker process exit status determines success; text printed by submitted code is never an attestation. Compilation failures return compiler output without starting the user program.

The sandbox preserves UID 65534, no network, read-only root, dropped capabilities, no-new-privileges, private namespaces, seccomp, effective memory/CPU/PID verification, no swap, bounded noexec/nosuid/nodev temporary storage, and cleanup on completion/error/timeout/cancellation. No host credentials, environment files, filesystem directories or Docker socket enter a job. Jobs remain serialized by the existing local and MongoDB admission locks.

C/C++ need executable machine code. The trusted container runner loads the compiled ELF into a sealed Linux memory file descriptor for execution, while `/tmp` stays `noexec`. This is deliberate permission to execute compiled native code; noexec temporary storage must not be presented as preventing all executable mappings. Java/Node load classes or scripts as data. Ordinary containers are not a perfect boundary against malicious native code or kernel/runtime exploits. Public hostile-code deployments should use dedicated worker VMs or stronger isolation and an independently reviewed orchestration service.

## API and results

Authenticated, CSRF-protected execution:

```json
{"language":"cpp","source_code":"#include <iostream>\nint main(){std::cout << 2+2 << '\\n';}","stdin":"","tool":"execute_code"}
```

`POST /api/sandbox/execute` creates a server-generated execution ID. `GET /api/sandbox/languages` describes registered languages and limits; `GET /api/sandbox/readiness?language=cpp` reports readiness for that recipe. Existing owner-scoped history, detail, approve and reject routes remain. History accepts an optional language filter; old records without a language are interpreted as Python.

Results retain `id`, `duration`, `status`, `stdout`, `stderr` and `exit_code`, and add `execution_id`, `language`, `compile_status`, `compile_stdout`, `compile_stderr` and `execution_duration_ms`. Pending/denied/unavailable executions must never appear as successful output. Monitoring signs fixed language/compilation/status metadata, not source, stdin or provider credentials. Existing retention and audit integrity behavior remain.

Source is limited to 32 KiB UTF-8, stdin to 8 KiB and combined output to 64 KiB (operator settings may lower limits). Default execution timeout is 10 seconds; compilation has a separate bounded timeout. Memory stays within the validated 128–256 MiB range, CPU at most one, default PID limit 32 and concurrency one. Larger programs and runtimes may fail within these deliberately small limits. No dependency downloads or package installation are available during jobs.

## Runtime provisioning and Colima

Python keeps its existing approved image digest. Other runtimes require operator-built approved images and explicit immutable local image IDs. Builds/installations are trusted operator actions; the API never pulls images or downloads language packages. Runtime images are started only for active jobs, not as six background services.

Use the committed runtime build instructions and record the emitted `sha256:` identities in the native backend configuration. Do not substitute tags, arbitrary images or an unreviewed recipe. Apple Silicon must build and validate its own native images; cloud x86_64 image IDs are not Mac validation evidence. Missing image provisioning returns `SANDBOX_UNAVAILABLE`.

Compose continues to disable sandbox execution and has no Docker socket in its public-facing backend. Use the native trusted-host backend with Colima for full code execution. The existing Python validator remains:

```sh
bash scripts/validate-phase4-colima.sh
```

Stop competing sandbox activity before validation. Both the original and new language checks must verify actual cgroup/security state before fixed harmless programs. Do not disable checks or modify a managed daemon to obtain a green result.

The current cloud Docker daemon reports cgroup v2 with driver `none`; effective controls are unavailable. Mocked lifecycle/compiler/API tests demonstrate application behavior only. Real multi-language isolation and execution on the Mac are **NOT VERIFIED** until the separate local validation completes.

## User workflow

Choose a language in Sandbox, edit the highlighted source template and optional standard input, and select Run Code. Review the exact language/source/stdin when approval is required. Approve or reject only your own requests. Compilation diagnostics, execution output, exit status and duration come from the backend. Clear Output affects only the current UI output; retained execution history remains available. Agent requests follow the same policy and approval path, and original-turn finalization never replays code.

### Exact local build and validation commands

From the repository root, with the Colima context selected:

```sh
colima start --cpu 2 --memory 4
docker context use colima
backend/.venv/bin/python scripts/build-sandbox-runtimes.py native
backend/.venv/bin/python scripts/build-sandbox-runtimes.py java
backend/.venv/bin/python scripts/build-sandbox-runtimes.py node
```

Review and copy each printed `SANDBOX_NATIVE_IMAGE`, `SANDBOX_JAVA_IMAGE`, and `SANDBOX_NODE_IMAGE` assignment into your existing ignored `backend/.env`, preserving other keys. The recipes pin GCC/G++ 14.2.0, OpenJDK 21.0.13, Debian-maintained Node 20.19.2 and TypeScript 5.9.3. The immutable image ID and recipe version bind approval. Repository package availability can change: rebuild failures require reviewed pin updates, never removing version checks. Use `SANDBOX_MEMORY_MB=256` for compiler-heavy workloads within the existing upper bound; no runtime can exceed the configured cgroup budget.

```sh
bash scripts/validate-phase4-colima.sh
PYTHONPATH=backend backend/.venv/bin/python backend/scripts/validate_multilanguage.py \
  --docker-url "$(docker context inspect colima --format '{{.Endpoints.docker.Host}}')"
```

The second command checks readiness for all six languages before any program, then runs fixed harmless hello-world programs. It supplements the original Python isolation suite; it does not prove every compiler/runtime resistant to hostile code. A BLOCKED report means no program ran. Only enable `SANDBOX_ENABLED=true` in the native backend after the required real checks pass, keeping `SANDBOX_POLICY=approval`. This cloud environment cannot substitute for that Mac validation.

## Read-only-rootfs source transfer fix

Docker Engine rejects its archive upload API (`put_archive`) when the container root filesystem is read-only, even if the requested destination is a writable tmpfs. Moving the upload earlier does not solve that daemon restriction, and tmpfs is only mounted once the container starts.

The job now starts an inert trusted holder with the original restrictions, verifies effective isolation in that exact container, and runs a fixed trusted staging writer as UID 65534. Source and stdin travel as bounded base64 data arguments to Docker exec, never as shell commands or interpolated Python. The writer repeats the isolation guard, checks UTF-8 and byte bounds, and creates only registry-selected source names and `/tmp/input.txt` using exclusive/no-follow opens with mode 0600. The encoded argument is below 56,000 bytes; source remains at most 32 KiB and stdin 8 KiB. Staging has its own three-second deadline and bounded diagnostics.

No compiler or submitted program starts until staging succeeds. Any staging refusal, timeout or Docker failure reaches the existing container-removal cleanup. Rootfs remains read-only for the complete lifecycle; `/tmp` remains bounded noexec/nosuid/nodev. No staging volume, host path, extra container, image rebuild or permission relaxation is introduced. Language recipes, immutable image identities and approval fingerprints are unchanged. Source is data visible to the trusted Docker operator, as with existing execution commands; ordinary application logs must never record Docker exec arguments.

Regression evidence for this fix: **334 backend/security tests passed, 16 real-Docker tests skipped**. Six-language lifecycle mocks model the exact archive rejection and verify no archive API is called, no compiler starts after staging failure, and cleanup runs. UTF-8/base64 roundtrip and maximum argument-size tests pass. Real cloud validation returned **BLOCKED / SANDBOX_UNAVAILABLE**, exit 2, because its cgroup driver is `none`; no programs ran. These mocks do not verify real execution or isolation. The operator's earlier Python 12/12 Colima result predates this fix.

Re-run both local commands above on Colima. The multi-language validator now supplies nonempty stdin so Python also exercises the new staging path. No runtime-image rebuild or fingerprint migration is required for this backend-only transfer fix. Compilation/runtime failures, memory/output/time restrictions and isolation still require real target-runtime verification; the Python isolation validator and six-language smoke validator provide complementary evidence.
