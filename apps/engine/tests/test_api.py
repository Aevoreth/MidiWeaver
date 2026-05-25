import pytest
from fastapi.testclient import TestClient

from midiweaver.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_create_and_import(client, tmp_path, fixture_dir):
    bundle = tmp_path / "APISet.midiweaver"
    r = client.post("/api/projects/create", json={"path": str(bundle), "name": "API Set"})
    assert r.status_code == 200

    with open(fixture_dir / "song_a.mid", "rb") as f:
        r = client.post(
            f"/api/projects/import?project_path={bundle}",
            files={"file": ("song_a.mid", f, "audio/midi")},
        )
    assert r.status_code == 200
    data = r.json()
    assert "segment" in data
    assert "timeline" in data


def test_ai_mock_plan(client, project_bundle):
    r = client.post(
        "/api/ai/plan",
        json={
            "project_path": str(project_bundle),
            "user_prompt": "Smooth transition",
            "selection": {"master_bar_range": [0, 4], "scope": "transition"},
            "mock": True,
        },
    )
    assert r.status_code == 200
    plan = r.json()["plan"]
    assert len(plan["tempo_options"]) >= 2
    assert len(plan["ops"]) >= 1


def test_validate_invalid_plan(client):
    r = client.post(
        "/api/ai/validate-plan",
        json={"plan_summary": "bad", "ops": [{"op_type": "unknown_op", "params": {}}]},
    )
    assert r.status_code == 200
    assert r.json()["valid"] is False
