import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    # Must use `with` — TestClient only runs the app's lifespan (startup /
    # shutdown) inside the context manager. Without it, `app.state.redis`
    # and `app.state.db_sessionmaker` are never set, and the lifespan
    # wiring added in Tasks 4/5 goes completely untested.
    with TestClient(app) as test_client:
        yield test_client


def test_health_ok(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "service": "copilot-mermaid-skeleton"}


def test_config_ok(client):
    response = client.get("/api/config")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert "productHomeUrl" in body


def test_health_response_headers(client):
    response = client.get("/api/health")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_lifespan_wires_db_sessionmaker_and_redis_onto_app_state(client):
    # Regression test for the Phase 0 review gap: the lifespan defined in
    # app/main.py must actually run and populate app.state, not just exist
    # as dead code that no test exercises.
    assert app.state.db_sessionmaker is not None
    assert app.state.redis is not None


def test_unhandled_exception_returns_safe_envelope_and_logs_traceback(monkeypatch, caplog):
    def boom():
        raise RuntimeError("boom: leaked secret path /etc/passwd")

    monkeypatch.setattr("app.api.config_route.get_settings", boom)

    with TestClient(app, raise_server_exceptions=False) as client:
        with caplog.at_level("ERROR"):
            response = client.get("/api/config")

    assert response.status_code == 500
    assert response.json() == {
        "ok": False,
        "error": {"code": "internal-error", "message": "Внутренняя ошибка сервера"},
    }
    assert "boom" not in response.text

    assert "boom: leaked secret path /etc/passwd" in caplog.text
    assert "Traceback" in caplog.text
