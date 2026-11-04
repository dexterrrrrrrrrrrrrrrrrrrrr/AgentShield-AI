from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_contract():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "agentshield-api", "version": "0.1.0"}


def test_allowed_frontend_origin():
    response = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "access-control-allow-credentials" not in response.headers


def test_untrusted_origin_not_allowed():
    response = client.get("/health", headers={"Origin": "https://untrusted.example"})
    assert "access-control-allow-origin" not in response.headers


def test_unknown_route():
    assert client.get("/execute").status_code == 404


def test_health_is_read_only():
    assert client.post("/health").status_code == 405


def test_preflight():
    response = client.options("/health", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-methods"] == "GET"
