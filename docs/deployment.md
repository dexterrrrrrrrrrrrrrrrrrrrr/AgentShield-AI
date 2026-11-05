# Local deployment and production responsibilities

The Compose stack launches the real frontend, backend, and authenticated MongoDB 7. It does not use fake AI responses, disable authentication, or provide an unisolated execution fallback. It publishes only the frontend on loopback. This is a local deployment baseline; public HTTPS termination, operator secrets, backups, monitoring, and stronger hostile-code isolation remain deployment responsibilities.

## Deployment modes

| Mode | Application | AI | Python sandbox |
| --- | --- | --- | --- |
| Compose stack | Three real containers; only frontend port published | Optional configured Groq account; no automatic billing/fallback | **Disabled**. Backend has no Docker socket or container-management endpoint |
| Trusted-host local development | Native frontend/backend; native MongoDB or explicit loopback MongoDB override | Groq or opt-in loopback Ollama | Available only after the unchanged Colima readiness/validation procedure succeeds and explicit operator enablement |

A Docker socket gives its holder broad control over that daemon. Mounting the host socket in the public-facing backend would defeat the desired separation, so this stack never does it. No container-manager RPC service is added. A separate authenticated least-authority orchestration service or stronger runtime would require a separate design/security review. Do not expose an unauthenticated Docker TCP API as a workaround.

For the complete demonstration with real sandbox execution, use the existing native backend on a trusted Mac/Colima host. It retains the existing user authentication, independent policy, ownership checks, exact human approval, resource verification, and isolated container manager. It is a local trusted-operator mode, not a hostile multi-tenant production boundary. Existing safe tools, accounts, stored sessions, monitoring, approvals/history, and audit APIs stay available even when sandbox readiness is false.

## Prerequisites and configuration

Use Docker Engine with Compose v2. On an 8 GB Apple Silicon Mac, free Colima can run the stack with a four-GB VM and two CPUs; close unnecessary applications and avoid running a local model at the same time. The official MongoDB 7, Node 24, and Python 3.12 images support Apple Silicon; this cloud validation is a separate Linux runtime and does not validate your Mac.

Preserve existing secrets and data. Never overwrite a populated `.env` or `backend/.env`. Compose reads substitutions from its `--env-file` argument, not from `backend/.env` automatically. For a fresh isolated Compose stack, run `python3 scripts/init-compose-env.py`. It exclusively creates an ignored `.env.compose` at mode `0600` with generated keys and MongoDB passwords, refusing to overwrite existing files. To choose another frontend port, pass the helper's `--port` option and keep its generated origin. Existing native account/audit keys are intentionally not copied or overwritten; preserve them separately if migrating data. You may instead securely prepare another ignored env file. Required settings are:

- `JWT_SECRET`: preserve the existing strong random key if retaining sessions.
- `AUDIT_SIGNING_KEY`: preserve the existing audit key; see Phase 6 rotation/migration guidance before changing it.
- `MONGO_ROOT_PASSWORD`: a separate generated root/admin password used for initialization/administration.
- `MONGO_APP_PASSWORD`: a separate generated **URL-safe** application password.
- `MONGO_APP_USER`: defaults to `agentshield_app`; keep this URL-safe.
- `MONGODB_DATABASE`: defaults to `agentshield_ai`.
- `GROQ_API_KEY`: optional server-only free-tier key; leaving it empty produces an actionable setup error when requesting inference.
- `CORS_ORIGINS`: the exact browser origin, default `http://localhost:3000`.

Use a secure local secret manager or Python `secrets.token_urlsafe(48)` to generate values without committing them. Do not paste keys into chat, build arguments, frontend variables, screenshots, or shell history. Keep the populated file mode at `0600`. The example intentionally has no usable credentials; missing required values fail Compose configuration before startup. App username/password must be URL-safe, the password at least 32 characters, and the database identifier alphanumeric/underscore; initialization rejects invalid values with a generic error.

The API authenticates to MongoDB as a dedicated user with `readWrite` only on the configured application database. Root credentials are not given to the backend. The initialization script runs only on a new volume. Editing env passwords later does not automatically rotate users already stored in MongoDB; perform a deliberate database credential rotation and preserve backups.

### Existing MongoDB 8 data

The old Compose definition used MongoDB 8 and a `mongo-data` volume. This stack uses a **new `mongo7-data` volume** and the distinct default project `agentshield-ai-v7`. It does not replace containers in the previous `agentshield-ai` project. Explicit `-p` overrides must likewise select a fresh intended project. It never mounts the old volume. Do not attach MongoDB 8 data files to MongoDB 7, delete the old volume, or copy its WiredTiger files between versions. A migration requires a supported logical backup/export and restoration into a new database, with application/key compatibility verified separately. Keep the original database until you have validated the restored records. No automatic data migration is implemented.

## Start the stack

From the repository root, after creating `.env.compose` with the helper:

```sh
docker compose --env-file .env.compose config --quiet
docker compose --env-file .env.compose build
docker compose --env-file .env.compose up -d --wait
docker compose --env-file .env.compose ps
```

Open the frontend on localhost port 3000. Register, sign in, open the agent playground, and configure only a free-tier Groq account without billing enabled if you want live hosted inference. The frontend proxies both HTTP and WebSockets to the backend. There are no published backend or MongoDB ports in this mode. If you change `FRONTEND_PORT`, set `CORS_ORIGINS` to the corresponding exact browser origin.

Next.js rewrites are compiled with the Docker build argument `API_INTERNAL_URL=http://backend:8000`. The runtime environment uses the same internal target. Rebuild the frontend when changing this target. No credentials enter that build argument. Actual API keys are provided only to the backend at runtime.

The frontend and backend images use UID/GID `10001`, read-only roots, bounded temporary filesystems, dropped capabilities, and no privilege escalation. MongoDB uses UID/GID `999`, a writable persistent data volume, and a read-only initialization script. Its root password is isolated to that trusted database container; dependency health verifies the application user rather than merely an admin login. App and database networks are internal. The frontend joins a separate edge bridge for its loopback port publication, and the backend joins a separate egress bridge for its fixed provider API. These Docker bridge networks are not an outbound domain firewall; a public deployment needs appropriate host/edge egress policy. Compose forces `SANDBOX_ENABLED=false` and `OLLAMA_ENABLED=false` rather than relaxing the existing loopback-only provider validation.

Declared budgets are frontend 512 MiB/1 CPU, backend 512 MiB/1 CPU, and MongoDB 768 MiB/1 CPU with a 256-MiB WiredTiger cache. PID counts, log rotation, health checks, dependency readiness, restart policies, and graceful shutdown are configured. Verify effective resource enforcement on the chosen Docker runtime; configuration alone does not establish that cgroup controllers work. These application-container budgets are not evidence of sandbox isolation.

Health checks use frontend `/login`, backend `/ready`, and a ping authenticated as the same application user required by the backend. MongoDB waits up to its configured startup window before dependents start. Docker marks unhealthy services but does not itself restart a process solely because its health check failed; the app returns safe database errors and PyMongo reconnects when the database recovers. `restart: unless-stopped` handles process exits, not all outage scenarios.

Stop without deleting data:

```sh
docker compose --env-file .env.compose stop
# To remove containers/networks while retaining the named database volume:
docker compose --env-file .env.compose down
```

Do not run `down --volumes` on your persistent deployment unless you intend to erase its database.

## Native backend and verified Colima sandbox

For native app development with the new authenticated MongoDB container only:

```sh
docker compose --env-file .env.compose -f compose.yaml -f compose.native.yaml up -d --wait mongo
```

This explicit override publishes MongoDB only on `127.0.0.1:27017` (or `MONGODB_PORT`). Configure the ignored `backend/.env` with the matching application username/password, database, and a loopback URI with `authSource` set to that database. Do not use production credentials in automated tests, whose fixtures deliberately require a separate credential-free test server. If port 27017 is already occupied by your original MongoDB, select another port; do not stop or replace that database casually.

If reusing the same application database, the native backend must use the existing deployment's effective JWT and audit signing keys as well as matching app credentials. Generating new keys for populated audit data invalidates signatures; preserve and transfer configuration securely instead.

Run the native backend and frontend using the README's startup commands. Ollama remains a native loopback opt-in; the app neither downloads a model nor changes to another provider. A lightweight 1.5-B-class model is recommended only after considering the shared memory needed by macOS, Colima, MongoDB, and the app.

For real sandbox validation, stop the local backend first, ensure Colima is running, and run:

```sh
bash scripts/validate-phase4-colima.sh
```

The unchanged script checks effective cgroup/security controls before any sandbox test program. Inspect the generated report; a skipped/blocked check is not a pass. Enable sandbox execution in the native backend only after all required checks succeed. The user-reported 12/12 Colima result from Phase 4 is not a new Phase 7 runtime result. Containers do not guarantee immunity from kernel/runtime escape vulnerabilities.

## HTTPS and public deployment

The default stack is HTTP development on loopback. A public deployment must place an independently managed HTTPS/WSS reverse proxy in front of the frontend, set backend `APP_ENV=production`, configure exact HTTPS `CORS_ORIGINS`, preserve the backend trusted-host allowlist for internal proxy requests, and forward WebSocket Upgrade/Connection headers. Production mode uses Secure `__Host-` HttpOnly cookies; they intentionally do not authenticate over ordinary HTTP. Keep backend and MongoDB ports unpublished, retain app/container limits, and set proxy timeouts above the heartbeat interval and bounded agent timeout. Do not enable broad trusted proxy headers or wildcard hosts/origins.

TLS certificates, private networking, host patching, registry update review, secret rotation, backups, edge abuse controls, alerting, and disaster-recovery drills are operator responsibilities. The partial browser CSP does not replace escaping or a full nonce-based policy. A single trusted operator/small local demonstration is the target; no production certification is claimed.

## Backups and recovery

Stop frontend/backend to pause application writes, leaving MongoDB running. Use the trusted database container's `mongodump` with `--username agentshield_admin --authenticationDatabase admin --db agentshield_ai --archive=/tmp/agentshield-backup.archive.gz --gzip --password` so the admin password is entered at the tool prompt, not embedded in the command. Copy the archive out with `docker compose cp` into a secured directory outside Git, then remove the temporary archive and restart the app. Adjust the database name if configured differently. Keep JWT/audit keys in a separate protected secret backup. Time-based TTL cleanup continues in MongoDB; this standalone setup is not a transactional point-in-time archive.

Practice restoration into a **new project/volume** with the same application/audit key requirements before relying on a backup. Initialize credentials there, stop its backend, copy in the archive, then use `mongorestore --archive=... --gzip --username agentshield_admin --authenticationDatabase admin --password` with a prompt. Verify account access, signed audit verification, ownership, and representative histories before switching users. Do not restore over your only live copy or use `--drop` casually. Expired sessions/audit TTL data are not permanent archives.

## Troubleshooting and evidence

- Configuration rejects an unset secret: populate the ignored env file and use `--env-file .env.compose`; never substitute a shared committed default.
- MongoDB authentication fails after env editing: existing volume users keep their original passwords; rotate deliberately rather than wiping data.
- MongoDB fails on an old volume: stop and inspect the image/data version; never downgrade MongoDB 8 files into this MongoDB 7 service.
- HTTP login fails with production cookies: provide HTTPS or use the explicit loopback development mode.
- Wrong origin/host rejection: match the exact browser origin and internal backend host; do not add wildcards.
- Sandbox unavailable in Compose: expected; there is no socket/control-plane mount. Use the trusted native backend validation path.
- Provider setup error: securely configure a free-tier Groq key or use native Ollama. Mocked tests never establish real inference availability.
- Managed proxy build TLS errors: Dockerfiles accept an optional BuildKit secret `proxy_ca` with a trusted CA bundle. Pass it to each image build with `--secret id=proxy_ca,src=/path/to/trusted-bundle`; never bake it into an image or disable TLS verification. Runtime provider traffic may need its own trusted CA configuration in that environment.

Exact Phase 7 build/start/auth/recovery measurements and validation outcomes are recorded in `docs/phase7.md`. Do not infer a successful build, live inference, Mac resource enforcement, or real sandbox execution from this configuration document alone.
