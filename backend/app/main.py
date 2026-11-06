"""AgentShield API. MongoDB is a required, verified dependency."""

import asyncio
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
from .guards import strict_json
from .hosts import HostAdmissionMiddleware
from .monitoring.api import router as monitor_router
from .monitoring.events import AuditIntegrityError, Monitor
from .oauth import GoogleProvider, install_access_filter
from .oauth import router as oauth_router
from .sandbox.api import router as sandbox_router
from .sandbox.manager import SandboxManager
from .security import Passwords


class BodyLimitMiddleware:
    """Bound actual auth request bytes, including chunked requests, before JSON parsing."""

    def __init__(self, app, read_timeout=10):
        self.app = app
        self.read_timeout = read_timeout

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope["method"] not in ("POST", "DELETE")
            or not scope["path"].startswith(
                ("/api/auth/", "/api/agent/", "/api/sandbox/", "/api/monitor/")
            )
        ):
            return await self.app(scope, receive, send)
        body_bytes = bytearray()
        try:
            async with asyncio.timeout(self.read_timeout):
                for _ in range(1024):
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    chunk = message.get("body", b"")
                    if len(body_bytes) + len(chunk) > (
                        262144 if scope["path"].startswith("/api/sandbox/") else 16384
                    ):
                        return await JSONResponse(
                            {"detail": "Request body too large"}, status_code=413
                        )(scope, receive, send)
                    body_bytes.extend(chunk)
                    if not message.get("more_body", False):
                        break
                else:
                    return await JSONResponse(
                        {"detail": "Too many body chunks"}, status_code=413
                    )(scope, receive, send)
            if body_bytes:
                strict_json(body_bytes)
        except TimeoutError:
            return await JSONResponse(
                {"detail": "Request body timed out"}, status_code=408
            )(scope, receive, send)
        except (ValueError, RecursionError, UnicodeError):
            return await JSONResponse({"detail": "Invalid JSON body"}, status_code=422)(
                scope, receive, send
            )
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {
                    "type": "http.request",
                    "body": bytes(body_bytes),
                    "more_body": False,
                }
            return await receive()

        await self.app(scope, replay, send)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    install_access_filter()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        client, db = await connect_database(settings)
        app.state.db = db
        app.state.settings = settings
        try:
            app.state.google_provider = GoogleProvider(settings)
            app.state.passwords = Passwords()
            app.state.agent_engine = Engine(settings)
            app.state.agent_active = 0
            if settings.sandbox_transport == "executor":
                from .sandbox.remote import RemoteManager
                app.state.sandbox_manager = RemoteManager(settings)
            else:
                app.state.sandbox_manager = SandboxManager(settings)
            app.state.monitor = Monitor(db, settings)
            yield
        finally:
            if hasattr(app.state, "google_provider"):
                await app.state.google_provider.close()
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
    app.add_middleware(HostAdmissionMiddleware, allowed_hosts=settings.hosts)

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

    @app.exception_handler(AuditIntegrityError)
    async def audit_error(request: Request, exc: AuditIntegrityError):
        return JSONResponse(
            status_code=503, content={"detail": "Security audit verification failed"}
        )

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
    app.include_router(oauth_router)
    app.include_router(agent_router)
    app.include_router(sandbox_router)
    app.include_router(monitor_router)
    return app


app = create_app()
