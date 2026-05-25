import pytest

from midiweaver.config import DEFAULT_SETTINGS
from midiweaver.settings_store import load_settings, save_settings, set_config_dir, settings_path, settings_public_view


def test_load_defaults_when_missing(tmp_path):
    set_config_dir(tmp_path)
    settings = load_settings()
    assert settings.ai_base_url == DEFAULT_SETTINGS.ai_base_url
    assert settings.ai_api_key == ""


def test_save_and_load_round_trip(tmp_path):
    set_config_dir(tmp_path)
    original = DEFAULT_SETTINGS.model_copy(update={"ai_api_key": "round-trip", "ai_model": "gpt-4o"})
    save_settings(original)
    loaded = load_settings()
    assert loaded.ai_api_key == "round-trip"
    assert loaded.ai_model == "gpt-4o"
    assert settings_path() == tmp_path / "settings.json"


def test_env_override_key(tmp_path, monkeypatch):
    set_config_dir(tmp_path)
    monkeypatch.setenv("MIDIWEAVER_AI_API_KEY", "from-env")
    settings = load_settings()
    assert settings.ai_api_key == "from-env"


def test_public_view_redacts_key():
    settings = DEFAULT_SETTINGS.model_copy(update={"ai_api_key": "secret"})
    view = settings_public_view(settings)
    assert view["ai_api_key_configured"] is True
    assert "ai_api_key" not in view


@pytest.fixture(autouse=True)
def reset_config_dir():
    yield
    set_config_dir(None)
