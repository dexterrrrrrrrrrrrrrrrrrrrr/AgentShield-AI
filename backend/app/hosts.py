"""Exact Host admission for HTTP and WebSocket scopes, including IPv6 literals."""

from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse


class HostAdmissionMiddleware:
    def __init__(self, app, allowed_hosts):
        self.app = app
        self.allowed = frozenset(allowed_hosts)

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        values = Headers(scope=scope).getlist("host")
        admitted = False
        if (
            len(values) == 1
            and values[0].isascii()
            and not any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in values[0])
            and not values[0].endswith(":")
        ):
            try:
                parsed = urlsplit("http://" + values[0])
                port = parsed.port  # Reject malformed ports rather than stripping them.
                admitted = bool(
                    parsed.hostname in self.allowed
                    and not any(
                        (
                            parsed.username,
                            parsed.password,
                            parsed.path,
                            parsed.query,
                            parsed.fragment,
                        )
                    )
                    and (port is None or 1 <= port <= 65535)
                )
            except ValueError:
                pass
        if admitted:
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            return await send({"type": "websocket.close", "code": 4403})
        await PlainTextResponse("Invalid request host", status_code=400)(
            scope, receive, send
        )
