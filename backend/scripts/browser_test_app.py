"""Explicit browser-test entry point, never imported by the production app."""

from contextlib import asynccontextmanager

from app.agents.providers import ProviderError, Reply
from app.agents.tools import ToolRequest
from app.main import create_app


class BrowserProvider:
    async def complete(self, provider, model, messages, allowed):
        user = next(m["content"] for m in reversed(messages) if m["role"] == "user")
        if user.startswith("fail"):
            raise ProviderError("Mock provider unavailable. Retry later.", 503)
        if user.startswith("<img"):
            return Reply(
                content='<svg onload="document.body.dataset.phase6Attack=1">untrusted model output</svg>'
            )
        if "calculate" in user.lower() and messages[-1]["role"] != "tool":
            return Reply(
                calls=[ToolRequest(name="calculator", arguments={"text": "(12+8)/2"})]
            )
        return Reply(content="Mocked assistant response: 10.")


def make_app():
    import os

    if os.environ.get("APP_ENV") != "test" or not os.environ.get(
        "MONGODB_DATABASE", ""
    ).startswith("agentshield_e2e_"):
        raise RuntimeError("Browser-test app requires an isolated test environment")
    app = create_app()
    original = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app):
        async with original(app):
            app.state.agent_engine.providers = BrowserProvider()
            from app.sandbox.manager import SandboxManager

            class FakeSandbox:
                def readiness(self):
                    return {"ready": True, "code": "READY"}

                def execute(self, code):
                    return {
                        "status": "completed",
                        "stdout": "Mocked sandbox output\n",
                        "stderr": "",
                        "exit_code": 0,
                        "duration": 0.01,
                    }

            app.state.settings.sandbox_enabled = True
            app.state.sandbox_manager = SandboxManager(
                app.state.settings, FakeSandbox()
            )
            yield

    app.router.lifespan_context = lifespan
    return app
