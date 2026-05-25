import json
from unittest.mock import AsyncMock, MagicMock, patch

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


def test_ai_mock_plan(client, project_bundle, isolated_settings):
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
    body = r.json()
    plan = body["plan"]
    assert body["mode"] == "mock"
    assert len(plan["steps"]) >= 1
    assert "plan_id" in body


def test_validate_invalid_plan(client):
    r = client.post(
        "/api/ai/validate-plan",
        json={"plan_summary": "bad", "ops": [{"op_type": "unknown_op", "params": {}}]},
    )
    assert r.status_code == 200
    assert r.json()["valid"] is False


def test_settings_get_redacts_key(client, isolated_settings):
    client.post("/api/settings", json={"ai_api_key": "secret-key-123", "ai_model": "gpt-4o-mini"})
    r = client.get("/api/settings")
    assert r.status_code == 200
    data = r.json()
    assert data["ai_api_key_configured"] is True
    assert "ai_api_key" not in data


def test_settings_persist_to_disk(client, isolated_settings):
    client.post("/api/settings", json={"ai_api_key": "persist-key", "ai_base_url": "https://example.com/v1"})
    settings_file = isolated_settings / "settings.json"
    assert settings_file.is_file()
    saved = json.loads(settings_file.read_text(encoding="utf-8"))
    assert saved["ai_api_key"] == "persist-key"
    assert saved["ai_base_url"] == "https://example.com/v1"


def test_settings_preserve_key_on_partial_update(client, isolated_settings):
    client.post("/api/settings", json={"ai_api_key": "keep-me", "ai_model": "gpt-4o-mini"})
    r = client.post("/api/settings", json={"ai_base_url": "https://api.openai.com/v1"})
    assert r.status_code == 200
    assert r.json()["ai_api_key_configured"] is True
    saved = json.loads((isolated_settings / "settings.json").read_text(encoding="utf-8"))
    assert saved["ai_api_key"] == "keep-me"


def test_settings_clear_key(client, isolated_settings):
    client.post("/api/settings", json={"ai_api_key": "to-clear"})
    r = client.post("/api/settings", json={"clear_ai_api_key": True})
    assert r.status_code == 200
    assert r.json()["ai_api_key_configured"] is False
    saved = json.loads((isolated_settings / "settings.json").read_text(encoding="utf-8"))
    assert saved["ai_api_key"] == ""


def test_ai_plan_mode_mock_without_key(client, project_bundle, isolated_settings):
    r = client.post(
        "/api/ai/plan",
        json={
            "project_path": str(project_bundle),
            "user_prompt": "Smooth transition",
            "selection": {"master_bar_range": [0, 4], "scope": "transition"},
        },
    )
    assert r.status_code == 200
    assert r.json()["mode"] == "mock"


def test_ai_plan_mode_live_with_key(client, project_bundle, isolated_settings):
    client.post("/api/settings", json={"ai_api_key": "test-key"})

    live_plan = {
        "plan_summary": "Live AI transition plan",
        "steps": [
            {
                "id": "step_1",
                "description": "Trim silence",
                "intent": "trim",
                "suggested_tool": "trim_silence",
                "suggested_params": {},
            }
        ],
        "tempo_options": [
            {
                "label": "Linear",
                "policy": "linear_ramp",
                "duration_bars": 4,
                "start_bpm": 120,
                "end_bpm": 140,
            }
        ],
        "constraints_applied": {},
    }

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps(live_plan)}}]
    }

    mock_client_instance = AsyncMock()
    mock_client_instance.post = AsyncMock(return_value=mock_resp)
    mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
    mock_client_instance.__aexit__ = AsyncMock(return_value=None)

    with patch("midiweaver.ai.agent.httpx.AsyncClient", return_value=mock_client_instance):
        r = client.post(
            "/api/ai/plan",
            json={
                "project_path": str(project_bundle),
                "user_prompt": "Smooth transition",
                "selection": {"master_bar_range": [0, 4], "scope": "transition"},
            },
        )

    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "live"
    assert body["plan"]["plan_summary"] == "Live AI transition plan"


def test_apply_plan_rejects_invalid_ops(client, project_bundle):
    r = client.post(
        "/api/ai/apply-plan",
        json={
            "project_path": str(project_bundle),
            "plan": {
                "plan_summary": "bad echo",
                "tempo_options": [],
                "ops": [
                    {
                        "op_type": "echo_notes",
                        "params": {},
                        "enabled": True,
                    }
                ],
            },
        },
    )
    assert r.status_code == 400
    assert "echo_notes" in r.json()["detail"]


def test_test_connection_without_key(client, isolated_settings):
    r = client.post("/api/ai/test-connection")
    assert r.status_code == 200
    assert r.json()["ok"] is False
    assert "No API key" in r.json()["error"]


def test_dry_run_ops_api(client, project_bundle):
    store_resp = client.get(f"/api/projects/{project_bundle}/timeline")
    song_id = store_resp.json()["segments"][0]["id"]
    r = client.post(
        "/api/projects/dry-run-ops",
        json={
            "project_path": str(project_bundle),
            "ops": [
                {
                    "op_type": "extend_drums",
                    "params": {"song_id": song_id, "bars": 1},
                }
            ],
        },
    )
    assert r.status_code == 200
    assert "added_notes" in r.json()


def test_query_timeline_api(client, project_bundle):
    r = client.get(f"/api/projects/{project_bundle}/query/timeline")
    assert r.status_code == 200
    assert len(r.json()["songs"]) == 2


def test_ai_ask_mock(client, project_bundle, isolated_settings):
    r = client.post(
        "/api/ai/ask",
        json={
            "project_path": str(project_bundle),
            "messages": [{"role": "user", "content": "How many songs?"}],
            "mock": True,
        },
    )
    assert r.status_code == 200
    assert r.json()["mode"] == "mock"
    assert "message" in r.json()


def test_agent_run_mock(client, project_bundle, isolated_settings):
    r = client.post(
        "/api/ai/agent/run",
        json={
            "project_path": str(project_bundle),
            "prompt": "Extend drums",
            "mock": True,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "done"
    assert len(body["steps"]) >= 1
