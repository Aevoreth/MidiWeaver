"""Smoke tests for Phase 0 bootstrap."""

from fastapi.testclient import TestClient

from midiweaver.main import app


def test_health_smoke():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body
