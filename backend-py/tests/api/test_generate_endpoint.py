import json

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_generate_missing_source_type_returns_400_diagram_generation(client):
    response = client.post("/api/generate", data={})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "diagram-generation"


def test_generate_text_file_without_file_returns_400_file_required(client):
    response = client.post("/api/generate", data={"sourceType": "text-file"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "file-required"


def test_generate_link_without_value_returns_400_link_required(client):
    response = client.post("/api/generate", data={"sourceType": "link", "link": ""})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "link-required"


def test_generate_link_invalid_format_returns_400_invalid_link(client):
    response = client.post("/api/generate", data={"sourceType": "link", "link": "not-a-url"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid-link"


def test_generate_text_file_unsupported_format_returns_400_file_format(client):
    response = client.post(
        "/api/generate",
        data={"sourceType": "text-file"},
        files={"file": ("song.mp3", b"binary data", "audio/mpeg")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "file-format"


def test_generate_text_file_too_large_returns_400_file_size(client):
    huge = b"x" * (10 * 1024 * 1024 + 1)
    response = client.post(
        "/api/generate",
        data={"sourceType": "text-file"},
        files={"file": ("notes.txt", huge, "text/plain")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "file-size"


def test_generate_text_file_success_returns_200(client, monkeypatch):
    async def fake_generate_diagram(source_text, details, client=None):
        return "flowchart LR\nA --> B"

    monkeypatch.setattr("app.api.generate.generate_diagram", fake_generate_diagram)

    response = client.post(
        "/api/generate",
        data={"sourceType": "text-file", "details": "some details"},
        files={"file": ("notes.txt", b"Hello world", "text/plain")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["result"]["mermaidCode"].startswith("flowchart LR")
    assert body["result"]["sourceText"] == "Hello world"


def test_generate_llm_failure_returns_500_diagram_generation(client, monkeypatch):
    async def fake_generate_diagram(source_text, details, client=None):
        raise RuntimeError("LLM down")

    monkeypatch.setattr("app.api.generate.generate_diagram", fake_generate_diagram)

    response = client.post(
        "/api/generate",
        data={"sourceType": "text-file"},
        files={"file": ("notes.txt", b"Hello world", "text/plain")},
    )
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "diagram-generation"
