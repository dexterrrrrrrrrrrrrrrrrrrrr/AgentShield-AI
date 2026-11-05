import pytest
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect

from app.config import Settings


@pytest.mark.parametrize(
    "host",
    [
        "evil.example",
        "localhost.evil.example",
        "localhost@evil.example",
        "localhost:abc",
        "localhost/path",
        "localhost:",
        "local\thost",
        " localhost",
    ],
)
def test_untrusted_host_rejected_before_routes(client, host):
    response = client.get("/health", headers={"Host": host})
    assert response.status_code == 400
    assert host not in response.text


def test_websocket_untrusted_host_rejected(client):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(
            "/api/monitor/ws",
            headers={"Host": "evil.example", "Origin": "http://localhost:3000"},
        ):
            pass
    assert exc.value.code == 4403


@pytest.mark.parametrize(
    "value",
    [
        "*",
        "*.example.com",
        "https://example.com",
        "localhost:8000",
        "",
        "host/path",
        "user@host",
    ],
)
def test_trusted_host_configuration_is_exact(settings, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, jwt_secret=settings.jwt_secret, trusted_hosts=value)


def test_allowed_host_keeps_health_available(client):
    assert client.get("/health", headers={"Host": "localhost:8000"}).status_code == 200
