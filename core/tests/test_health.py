from fastapi.testclient import TestClient

from freeread.main import create_app


def test_health_requires_token():
    client = TestClient(create_app(token="secret"))
    assert client.get("/health").status_code == 401
    resp = client.get("/health", headers={"X-FreeRead-Token": "secret"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_cors_preflight_from_tauri_webview():
    client = TestClient(create_app(token="secret"))
    resp = client.options(
        "/health",
        headers={
            "Origin": "http://tauri.localhost",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-freeread-token",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "http://tauri.localhost"
