def test_health_contract(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "agentshield-api",
        "version": "0.2.0",
    }


def test_allowed_frontend_origin(client):
    response = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_untrusted_origin_not_allowed(client):
    response = client.get("/health", headers={"Origin": "https://untrusted.example"})
    assert "access-control-allow-origin" not in response.headers


def test_unknown_route(client):
    assert client.get("/execute").status_code == 404


def test_health_is_read_only(client):
    assert client.post("/health").status_code == 405


def test_preflight(client):
    response = client.options(
        "/api/auth/logout",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "X-CSRF-Token",
        },
    )
    assert response.status_code == 200
    assert "POST" in response.headers["access-control-allow-methods"]


def test_readiness_checks_database(client):
    assert client.get("/ready").json() == {"status": "ready"}
