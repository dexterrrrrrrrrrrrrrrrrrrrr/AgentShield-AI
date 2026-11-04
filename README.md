# AgentShield AI

Phase 1 full-stack foundation for an AI agent security workspace.

## Requirements

- Node.js 24 and npm
- Python 3.12

## Local development

Use two terminals from the repository root:

```sh
python -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements-dev.txt
cd backend
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

```sh
cd frontend
npm ci
npm run dev
```

Open the frontend on port 3000. The dashboard checks `GET /health` on port 8000 and displays its actual connection state. API documentation is at backend `/docs`.

## Configuration

See `.env.example` for variable names. Next.js reads `frontend/.env.local`; set `NEXT_PUBLIC_API_URL` there if the backend is on another host. This is a public, build-time URL visible to browsers, never a secret. Use a browser-reachable backend URL for remote development. Export `CORS_ORIGINS` in the backend process for the exact frontend origin(s), comma-separated. FastAPI does not automatically load the root example file. Defaults support local development without an env file.

## Validation

```sh
cd frontend
npm run lint
npm run typecheck
npm run build
# Production frontend: npm start
```

```sh
cd backend
.venv/bin/python -m pip check
.venv/bin/python -m pytest -q
```

GitHub Actions runs the same lint, type, build, and API tests. See [architecture](docs/architecture.md) for scope and trust boundaries.

## Phase 1 scope

Responsive dashboard, sidebar navigation, overview, API connection status with retry, and clearly marked placeholders for Agent Playground, Sandbox, Execution Logs, Security Monitoring, and Settings. No authentication, AI agents, command execution, database connection, or real monitoring is implemented. MongoDB, LangGraph, Groq Llama API, and Ollama are future integration points only. Phase 2 requires approval.
