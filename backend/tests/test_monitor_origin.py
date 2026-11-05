from conftest import login, register


def test_monitor_origin_metadata_is_authenticated_and_does_not_change_policy(client):
    assert (
        client.get(
            "/api/monitor/summary?frontend_origin=http://localhost:3000"
        ).status_code
        == 401
    )
    register(client)
    login(client)
    assert (
        client.get("/api/monitor/summary?frontend_origin=http://localhost:3000").json()[
            "websocket_origin_allowed"
        ]
        is True
    )
    assert (
        client.get("/api/monitor/summary?frontend_origin=https://evil.example").json()[
            "websocket_origin_allowed"
        ]
        is False
    )
    assert client.get("/api/monitor/summary").json()["websocket_origin_allowed"] is None
    assert (
        client.get("/api/monitor/summary?frontend_origin=" + "x" * 201).status_code
        == 422
    )
