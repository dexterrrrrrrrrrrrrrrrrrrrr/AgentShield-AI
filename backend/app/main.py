"""AgentShield API. MongoDB is a required, verified dependency."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pymongo.errors import PyMongoError

from .agents.api import router as agent_router
from .agents.engine import Engine
from .auth import router
from .config import Settings
from .database import connect_database
from .monitoring.api import router as monitor_router
from .monitoring.events import Monitor
from .sandbox.api import router as sandbox_router
from .sandbox.manager import SandboxManager
from .security import Passwords


class BodyLimitMiddleware:
    """Bound actual auth request bytes, including chunked requests, before JSON parsing."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope["method"] not in ("POST", "DELETE")
            or not scope["path"].startswith(
                ("/api/auth/", "/api/agent/", "/api/sandbox/", "/api/monitor/")
            )
        ):
            return await self.app(scope, receive, send)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body = message.get("body", b"")
            size += len(body)
            if size > (262144 if scope["path"].startswith("/api/sandbox/") else 16384):
                return await JSONResponse(
                    {"detail": "Request body too large"}, status_code=413
                )(scope, receive, send)
            chunks.append(body)
            if not message.get("more_body", False):
                break
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {
                    "type": "http.request",
                    "body": b"".join(chunks),
                    "more_body": False,
                }
            return await receive()

        await self.app(scope, replay, send)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        client, db = await connect_database(settings)
        app.state.db = db
        app.state.settings = settings
        try:
            app.state.passwords = Passwords()
            app.state.agent_engine = Engine(settings)
            app.state.agent_active = 0
            app.state.sandbox_manager = SandboxManager(settings)
            app.state.monitor = Monitor(db)
            yield
        finally:
            await client.close()

    app = FastAPI(title="AgentShield AI", version="0.2.0", lifespan=lifespan)
    app.state.settings = settings
    app.add_middleware(BodyLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Accept", "Content-Type", "X-CSRF-Token"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith(
            ("/api/auth/", "/api/agent/", "/api/sandbox/", "/api/monitor/")
        ):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
        return response

    @app.exception_handler(PyMongoError)
    async def database_error(request: Request, exc: PyMongoError):
        return JSONResponse(
            status_code=503, content={"detail": "Database temporarily unavailable"}
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # Never echo rejected passwords, confirm_password, or full request bodies.
        return JSONResponse(
            status_code=422,
            content={
                "detail": "Invalid input. Check your name, email, and password requirements."
            },
        )

    class HealthResponse(BaseModel):
        status: str
        service: str
        version: str

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok", service="agentshield-api", version="0.2.0")

    @app.get("/ready")
    async def ready(request: Request):
        await request.app.state.db.command("ping")
        return {"status": "ready"}

    app.include_router(router)
    app.include_router(agent_router)
    app.include_router(sandbox_router)
    app.include_router(monitor_router)
    return app


app = create_app()
