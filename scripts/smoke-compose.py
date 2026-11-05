#!/usr/bin/env python3
"""Exercise real loopback Compose APIs with a disposable account; no inference/code runs.

Run only against an isolated validation stack. It creates an account and audit rows.
Uses the standard library so CI does not need application/test dependencies.
"""

import argparse
import http.cookiejar
import json
import secrets
import urllib.error
import urllib.parse
import urllib.request
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:3002")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    url = urllib.parse.urlsplit(base)
    if (
        url.scheme not in ("http", "https")
        or url.hostname not in ("localhost", "127.0.0.1", "::1")
        or url.username
        or url.password
        or url.path
        or url.query
        or url.fragment
    ):
        parser.error("Validation requires a credential-free loopback HTTP(S) origin")
    origin = base
    jar = http.cookiejar.CookieJar()

    class SameOriginRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            redirected = urllib.parse.urlsplit(newurl)
            if (redirected.scheme, redirected.netloc) != (url.scheme, url.netloc):
                raise urllib.error.URLError(
                    "Refusing a redirect outside the validation origin"
                )
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    client = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar),
        urllib.request.ProxyHandler({}),
        SameOriginRedirect(),
    )

    def request(path, method="GET", body=None, expected=200):
        headers = {"Accept": "application/json"}
        if method in ("POST", "DELETE"):
            csrf = request("/api/auth/csrf")["csrf_token"]
            headers.update({"Origin": origin, "X-CSRF-Token": csrf})
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        req = urllib.request.Request(
            base + path, data=data, method=method, headers=headers
        )
        try:
            response = client.open(req, timeout=15)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            status, payload, kind = (
                response.status,
                response.read(),
                response.headers.get("Content-Type", ""),
            )
        if status != expected:
            # Never print response bodies or auth headers/cookies in failure logs.
            raise AssertionError(
                f"{method} {path}: expected HTTP {expected}, received {status}"
            )
        return (
            json.loads(payload)
            if "application/json" in kind and payload
            else payload.decode()
        )

    assert request("/api/health")["status"] == "ok"
    request("/api/auth/me", expected=401)
    email = "compose-validation-" + uuid.uuid4().hex + "@example.com"
    password = secrets.token_urlsafe(32)
    profile = request(
        "/api/auth/register",
        "POST",
        {
            "full_name": "Compose Validation",
            "email": email,
            "password": password,
            "confirm_password": password,
        },
        201,
    )
    assert not profile["authenticated"]
    request("/api/auth/login", "POST", {"email": email, "password": password})
    profile = request("/api/auth/me")
    assert profile["email"] == email and profile["authenticated"]
    assert "Dashboard overview" in request("/")
    providers = request("/api/agent/providers")["providers"]
    configured = next(p for p in providers if p["id"] == "groq")
    session = request(
        "/api/agent/sessions",
        "POST",
        {
            "provider": "groq",
            "model": configured["model"],
            "allowed_tools": ["calculator"],
        },
        201,
    )
    sid = session["id"]
    assert any(s["id"] == sid for s in request("/api/agent/sessions")["sessions"])
    assert request(f"/api/agent/sessions/{sid}/messages")["messages"] == []
    # Deployment intentionally has no Docker management endpoint/socket.
    assert request("/api/sandbox/readiness")["ready"] is False
    denied = request("/api/sandbox/execute", "POST", {"code": "print(1)"})
    assert denied["status"] == "unavailable" and denied["policy_decision"] == "DENY"
    audit = request("/api/monitor/events")["events"]
    assert any(
        e["kind"] == "tool_rejected" and e["integrity"] == "verified" for e in audit
    )
    assert all(e["user_id"] == profile["id"] for e in audit)
    assert request("/api/monitor/summary")["blocked_tool_requests"] >= 1
    assert request("/api/sandbox/executions/" + denied["id"])["status"] == "unavailable"
    assert "Live Monitoring" in request("/monitoring")
    request(f"/api/agent/sessions/{sid}", "DELETE", expected=204)
    request("/api/auth/logout", "POST", expected=204)
    request("/api/auth/me", expected=401)
    print(
        "PASS: real Compose health, registration/login, protected dashboard, persisted session, fail-closed sandbox denial, signed owner-scoped audit, monitoring, cleanup, and logout"
    )
    print(
        "NOT VERIFIED: live LLM inference, real sandbox execution, TLS termination, effective cgroup resource enforcement"
    )


if __name__ == "__main__":
    main()
