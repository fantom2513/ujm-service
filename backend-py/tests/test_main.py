from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_ok():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "service": "copilot-mermaid-skeleton"}


def test_config_ok():
    response = client.get("/api/config")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert "productHomeUrl" in body


def test_health_response_headers():
    response = client.get("/api/health")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
