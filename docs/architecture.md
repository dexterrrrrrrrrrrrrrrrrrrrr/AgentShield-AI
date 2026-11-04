# Architecture and scope

The Next.js App Router frontend uses TypeScript and Tailwind CSS. Its client dashboard requests the FastAPI health endpoint with a five-second timeout, validates the status payload, and exposes checking, connected, and unavailable states. Navigation changes workspace panels locally; placeholders do not imply operational capabilities.

FastAPI exposes a typed `GET /health` response. It has no database dependency and performs no external AI calls. MongoDB persistence, LangGraph orchestration, Groq Llama API access, and Ollama are explicitly deferred. No API keys are needed for Phase 1.

## Trust boundaries

CORS allows explicitly configured frontend origins and GET requests without credentials. CORS is a browser policy, not authentication. The health endpoint is intentionally public. The frontend sets anti-framing, MIME-sniffing, and referrer headers. Do not expose future privileged endpoints until authentication and authorization are designed. Never place credentials in `NEXT_PUBLIC_*` variables. Local env files, virtual environments, dependencies, and build output are ignored by Git.

## Validation

API tests cover the health contract, allowed and denied browser origins, preflight, absent execution routes, and read-only health behavior. Frontend validation includes ESLint, TypeScript, a production build, and a browser smoke check of API connection and navigation. No persistence or agent behavior should be inferred from these checks.

## Dependency maintenance

The frontend lockfile pins the dependency tree. The minimatch override selects version 11.0.1 or newer to address GHSA-g3hv-75wg-m249 in development tooling. The ESLint 10 and TypeScript ESLint stack is validated with this override; rerun lint and the dependency audit when updating it. Python direct dependencies are pinned; transitive dependencies are resolved at installation time.
