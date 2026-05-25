from __future__ import annotations

from pydantic import BaseModel, Field


class EngineSettings(BaseModel):
    master_ppq: int = 480
    default_snap: str = "beat"
    quantize_default: bool = False
    ai_base_url: str = "https://api.openai.com/v1"
    ai_api_key: str = ""
    ai_model: str = "gpt-4o-mini"
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_enabled: bool = False
    audio_backend: str = "system_midi"
    soundfont_path: str = ""
    midi_device: str = ""


DEFAULT_SETTINGS = EngineSettings()
