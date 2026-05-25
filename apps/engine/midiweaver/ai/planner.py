from __future__ import annotations

import json
from typing import Any

import httpx

from midiweaver.models import Operation, OperationPlan, TempoOption
from midiweaver.ops.executor import ALLOWED_OPS, OpExecutor


DEFAULT_CONSTRAINTS = {
    "max_transpose_semitones": 6,
    "max_tempo_delta": 40,
    "allowed_ops": sorted(ALLOWED_OPS),
    "max_transition_bars": 16,
    "drum_only_mode": False,
    "preserve_programs": True,
    "preserve_cc": True,
}


class PromptBuilder:
    """Build compact global + regional note context for AI."""

    def build(
        self,
        timeline: Any,
        track_mapping: list[Any],
        selection: dict[str, Any],
        user_prompt: str,
        constraints: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        global_ctx = self._build_global(timeline, track_mapping)
        regional = self._build_selection(timeline, selection)
        return {
            "global": global_ctx,
            "selection": regional,
            "user_prompt": user_prompt,
            "constraints": {**DEFAULT_CONSTRAINTS, **(constraints or {})},
        }

    def _build_global(self, timeline: Any, track_mapping: list[Any]) -> dict[str, Any]:
        songs = []
        for seg in timeline.segments:
            a = seg.analysis
            if not a:
                continue
            songs.append(
                {
                    "id": seg.id,
                    "display_name": seg.display_name,
                    "bpm_range": list(a.bpm_range),
                    "time_sig": list(a.time_sig),
                    "key": a.key,
                    "bar_count": a.bar_count,
                    "track_summaries": [ts.model_dump() for ts in a.track_summaries],
                }
            )
        return {
            "songs": songs,
            "track_mapping": [m.model_dump() if hasattr(m, "model_dump") else m for m in track_mapping],
            "master_ppq": timeline.master_ppq,
            "total_bars": timeline.total_bars,
        }

    def _build_selection(self, timeline: Any, selection: dict[str, Any]) -> dict[str, Any]:
        from midiweaver.normalize.timeline import bars_to_ticks, collect_master_notes

        bar_range = selection.get("master_bar_range", [0, 4])
        bpm = 120.0
        if timeline.segments and timeline.segments[0].analysis:
            bpm = timeline.segments[0].analysis.estimated_bpm
        start_tick = bars_to_ticks(bar_range[0], timeline.master_ppq, bpm)
        end_tick = bars_to_ticks(bar_range[1], timeline.master_ppq, bpm)
        track_filter = set(selection.get("tracks", []))

        notes = collect_master_notes(timeline)
        filtered = [
            n
            for n in notes
            if start_tick <= n["start_tick"] < end_tick
            and (not track_filter or n.get("master_track_id") in track_filter or n.get("track_id") in track_filter)
        ]
        return {
            "scope": selection.get("scope", "transition"),
            "master_bar_range": bar_range,
            "tracks": list(track_filter) if track_filter else selection.get("tracks", []),
            "note_events": filtered,
        }


class AIPlanner:
    SYSTEM_PROMPT = """You are MidiWeaver's transition planner. Return ONLY valid JSON matching OperationPlan schema.
Include plan_summary, 2-3 tempo_options with label/policy/duration_bars/start_bpm/end_bpm, and ops array.
Each op has op_type, params, enabled=true, description. Never output raw MIDI."""

    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.prompt_builder = PromptBuilder()
        self.executor = OpExecutor()

    def validate_plan(self, data: dict[str, Any]) -> tuple[OperationPlan | None, list[str]]:
        errors: list[str] = []
        try:
            plan = OperationPlan(**data)
        except Exception as e:
            return None, [str(e)]
        errors.extend(self.executor.validate_plan(plan))
        return (plan if not errors else None), errors

    async def plan(
        self,
        payload: dict[str, Any],
        mock: bool = False,
    ) -> OperationPlan:
        if mock or not self.api_key:
            return self._mock_plan(payload)

        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(payload) + "\n\nRespond with OperationPlan JSON only.",
            },
        ]
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "messages": messages, "response_format": {"type": "json_object"}},
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            data = json.loads(content)
        plan, errors = self.validate_plan(data)
        if plan is None:
            raise ValueError(f"Invalid plan: {errors}")
        return plan

    def _mock_plan(self, payload: dict[str, Any]) -> OperationPlan:
        """Deterministic mock for tests and offline dev."""
        bar_range = payload.get("selection", {}).get("master_bar_range", [0, 4])
        songs = payload.get("global", {}).get("songs", [])
        start_bpm = songs[0]["bpm_range"][0] if songs else 120.0
        end_bpm = songs[1]["bpm_range"][0] if len(songs) > 1 else start_bpm

        return OperationPlan(
            plan_summary="Mock transition: trim, tempo ramp, extend drums",
            tempo_options=[
                TempoOption(
                    label="Smooth linear ramp",
                    policy="linear_ramp",
                    duration_bars=bar_range[1] - bar_range[0],
                    start_bpm=start_bpm,
                    end_bpm=end_bpm,
                ),
                TempoOption(
                    label="Hold then ramp",
                    policy="hold_song1_then_ramp",
                    duration_bars=bar_range[1] - bar_range[0],
                    start_bpm=start_bpm,
                    end_bpm=end_bpm,
                ),
                TempoOption(
                    label="Step at boundary",
                    policy="step_at_boundary",
                    duration_bars=1,
                    start_bpm=start_bpm,
                    end_bpm=end_bpm,
                ),
            ],
            ops=[
                Operation(
                    op_type="trim_silence",
                    params={"song_id": songs[0]["id"] if songs else "song_1"},
                    description="Trim leading/trailing silence",
                ),
                Operation(
                    op_type="tempo_ramp",
                    params={
                        "start_tick": 0,
                        "end_tick": 1920,
                        "start_bpm": start_bpm,
                        "end_bpm": end_bpm,
                        "policy": "linear_ramp",
                    },
                    description="Tempo transition",
                ),
                Operation(
                    op_type="extend_drums",
                    params={"bars": 2, "mode": "repeat_last_phrase"},
                    description="Extend drum groove",
                ),
            ],
        )


class OllamaClientStub:
    """v1 stub — settings only; use OpenAI-compatible path for real calls."""

    def __init__(self, base_url: str = "http://localhost:11434/v1"):
        self.base_url = base_url

    async def plan(self, payload: dict[str, Any]) -> OperationPlan:
        raise NotImplementedError(
            "Ollama integration is stubbed in v1. Configure OpenAI-compatible API instead."
        )

    def status(self) -> dict[str, str]:
        return {"status": "stub", "message": "Ollama support planned for v1.1"}
