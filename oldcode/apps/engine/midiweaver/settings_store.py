from __future__ import annotations

import json
import os
from pathlib import Path

from platformdirs import user_config_dir

from midiweaver.config import DEFAULT_SETTINGS, EngineSettings

APP_NAME = "MidiWeaver"
SETTINGS_FILENAME = "settings.json"

_config_dir_override: Path | None = None


def set_config_dir(path: Path | None) -> None:
    """Override config directory (for tests)."""
    global _config_dir_override
    _config_dir_override = path


def config_dir() -> Path:
    if _config_dir_override is not None:
        return _config_dir_override
    return Path(user_config_dir(APP_NAME, appauthor=False))


def settings_path() -> Path:
    return config_dir() / SETTINGS_FILENAME


def load_settings() -> EngineSettings:
    path = settings_path()
    data: dict = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}

    merged = DEFAULT_SETTINGS.model_copy(update={k: v for k, v in data.items() if k in EngineSettings.model_fields})

    env_key = os.environ.get("MIDIWEAVER_AI_API_KEY", "").strip()
    if env_key:
        merged = merged.model_copy(update={"ai_api_key": env_key})

    return merged


def save_settings(settings: EngineSettings) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(settings.model_dump(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def settings_public_view(settings: EngineSettings) -> dict:
    data = settings.model_dump()
    data.pop("ai_api_key", None)
    data["ai_api_key_configured"] = bool(settings.ai_api_key)
    return data
