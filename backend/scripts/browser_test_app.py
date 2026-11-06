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
        if user.startswith("Sandbox execution outcome (untrusted data):"):
            return Reply(
                content="Mocked assistant confirmation: sandbox execution completed."
            )
        if user.startswith("sandbox multilang"):
            return Reply(calls=[ToolRequest(name="execute_code", arguments={"language": "c", "code": "#include <stdio.h>\nint main(void) { puts(\"agent compile fixture\"); return 0; }", "stdin": "agent-bound input"})])
        if user.startswith("sandbox phase7"):
            return Reply(
                calls=[
                    ToolRequest(
                        name="python_sandbox",
                        arguments={"code": "print('phase7 approval')"},
                    )
                ]
            )
        if user == "markdown ui fixture":
            return Reply(content='**Example**\n\n```python\nprint("hello")\n```\n\n<img src=x onerror=alert(1)>')
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
                def readiness(self, language="python"):
                    return {"ready": True, "code": "READY"}

                def execute(self, code, language="python", stdin=""):
                    if code.startswith("#error browser compile fixture"):
                        return {"status": "failed", "stdout": "", "stderr": "", "exit_code": 1, "duration": 0.01, "compile_status": "failed", "compile_stdout": "", "compile_stderr": "Mocked compiler diagnostic: invalid source", "error_category": "COMPILATION_ERROR"}
                    return {
                        "status": "completed",
                        "stdout": "Mocked sandbox output\n" + stdin,
                        "compile_status": "completed" if language in {"c", "cpp", "java", "typescript"} else "not_required",
                        "compile_stdout": "Mocked compilation output" if language in {"c", "cpp", "java", "typescript"} else "",
                        "compile_stderr": "",
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
