from __future__ import annotations

import json
from typing import Any

import httpx

from midiweaver.models import MasterTimeline, Operation, OperationPlan, TempoOption
from midiweaver.ops.executor import ALLOWED_OPS, OpExecutor


def _bar_to_tick(bar: float, ppq: int) -> int:
    return int(bar * 4 * ppq)


def _song_segments_from_timeline(timeline: MasterTimeline) -> list[dict[str, Any]]:
    return [
        {
            "id": seg.id,
            "master_start_tick": seg.master_start_tick,
            "master_end_tick": seg.master_end_tick,
        }
        for seg in timeline.segments
    ]


def resolve_plan(
    plan: OperationPlan,
    *,
    ppq: int,
    bar_range: list[float] | None = None,
    song_segments: list[dict[str, Any]] | None = None,
    timeline: MasterTimeline | None = None,
    transition_id: str | None = None,
    merge_selected_tempo_option: bool = False,
) -> OperationPlan:
    """Fill missing op params from tempo_options, timeline context, and selection."""
    bar_range = bar_range or [0.0, 4.0]
    tempo_opt: TempoOption | None = None
    if plan.tempo_options:
        idx = min(max(plan.selected_tempo_option_index, 0), len(plan.tempo_options) - 1)
        tempo_opt = plan.tempo_options[idx]

    default_start = _bar_to_tick(bar_range[0], ppq)
    song_starts = {s["id"]: s["master_start_tick"] for s in (song_segments or []) if "master_start_tick" in s}
    second_song_start = (
        song_segments[1]["master_start_tick"]
        if song_segments and len(song_segments) > 1 and "master_start_tick" in song_segments[1]
        else default_start
    )

    new_ops: list[Operation] = []
    for op in plan.ops:
        p = dict(op.params)

        if op.op_type == "tempo_ramp":
            if tempo_opt:
                if merge_selected_tempo_option:
                    p["start_bpm"] = tempo_opt.start_bpm
                    p["end_bpm"] = tempo_opt.end_bpm
                    p["policy"] = tempo_opt.policy
                else:
                    p.setdefault("start_bpm", tempo_opt.start_bpm)
                    p.setdefault("end_bpm", tempo_opt.end_bpm)
                    p.setdefault("policy", tempo_opt.policy)

            if "start_bar" in p and "start_tick" not in p:
                p["start_tick"] = _bar_to_tick(float(p["start_bar"]), ppq)
            if "end_bar" in p and "end_tick" not in p:
                p["end_tick"] = _bar_to_tick(float(p["end_bar"]), ppq)

            if "start_tick" not in p or "end_tick" not in p:
                policy = p.get("policy", "linear_ramp")
                duration_bars = float(
                    p.get("duration_bars", tempo_opt.duration_bars if tempo_opt else bar_range[1] - bar_range[0])
                )
                song_id = p.get("song_id") or p.get("at_song_id")
                if song_id and song_id in song_starts:
                    boundary = song_starts[song_id]
                elif policy == "step_at_boundary":
                    boundary = second_song_start
                else:
                    boundary = default_start

                if policy == "step_at_boundary" or duration_bars <= 1:
                    p.setdefault("start_tick", boundary)
                    p.setdefault("end_tick", boundary)
                else:
                    p.setdefault("start_tick", boundary)
                    p.setdefault("end_tick", boundary + _bar_to_tick(duration_bars, ppq))

        elif op.op_type == "echo_notes":
            p.setdefault("interval_ticks", ppq)
            p.setdefault("velocity_decay", 0.85)
            p.setdefault("repeats", 4)
            if "bars" in p and "repeats" not in p:
                p["repeats"] = max(1, int(float(p["bars"]) * 4))
            if "source_start_tick" not in p and "source_end_tick" not in p and bar_range:
                has_track_target = ("track_id" in p or "master_track_id" in p) and "song_id" in p
                if has_track_target:
                    p.setdefault("source_start_tick", _bar_to_tick(bar_range[0], ppq))
                    p.setdefault("source_end_tick", _bar_to_tick(bar_range[1], ppq))

        elif op.op_type == "shift_song":
            if "delta_ticks" not in p and "bars" in p:
                bars = float(p["bars"])
                if p.get("direction") in ("back", "earlier", "left"):
                    bars = -abs(bars)
                elif p.get("direction") in ("forward", "later", "right"):
                    bars = abs(bars)
                p["delta_ticks"] = int(bars * 4 * ppq)

        elif op.op_type == "set_transition_markers":
            if "transition_id" not in p:
                if timeline:
                    match = None
                    if "from_song_id" in p and "to_song_id" in p:
                        match = next(
                            (
                                t
                                for t in timeline.transitions
                                if t.from_song_id == p["from_song_id"]
                                and t.to_song_id == p["to_song_id"]
                            ),
                            None,
                        )
                    elif transition_id:
                        p["transition_id"] = transition_id
                    elif len(timeline.transitions) == 1:
                        p["transition_id"] = timeline.transitions[0].id
                    if match:
                        p["transition_id"] = match.id
                elif transition_id:
                    p["transition_id"] = transition_id

        new_ops.append(op.model_copy(update={"params": p}))

    return plan.model_copy(update={"ops": new_ops})


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
                    "master_start_tick": seg.master_start_tick,
                    "master_end_tick": seg.master_end_tick,
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
Each op has op_type, params, enabled=true, description. Never output raw MIDI.

tempo_ramp params MUST include start_tick, end_tick, start_bpm, end_bpm, and policy.
Use global.songs[].master_start_tick for song boundaries. For an immediate tempo change at a song
boundary, use policy step_at_boundary with start_tick and end_tick both set to that song's
master_start_tick. For ramps, set start_tick/end_tick to the master tick range spanned.

echo_notes: delayed copies of notes. Prefer source_start_tick/source_end_tick in master
ticks (use selection.master_bar_range converted to ticks when the user selected a region).
When echoing a whole part/track, provide song_id + track_id — all notes on that track are echoed.
Include repeats (default 4) or bars for echo length, interval_ticks (default one beat),
velocity_decay (0-1, default 0.85).
shift_song: song_id plus bars (negative to shift earlier for overlap) or delta_ticks.
Earlier shifts overlap the prior song on the master timeline.
set_transition_markers: transition_id, or from_song_id + to_song_id."""

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

    def _chat_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _format_http_error(self, exc: httpx.HTTPStatusError) -> str:
        status = exc.response.status_code
        detail = exc.response.text.strip()
        if len(detail) > 300:
            detail = detail[:300] + "…"
        if status == 401:
            return "AI API authentication failed (401). Check your API key."
        if status == 404:
            return f"AI API endpoint not found (404). Check base URL: {self.base_url}"
        if status == 429:
            return "AI API rate limit exceeded (429). Try again later."
        return f"AI API request failed ({status}): {detail or exc.response.reason_phrase}"

    async def test_connection(self) -> dict[str, str]:
        if not self.api_key:
            raise ValueError("No API key configured.")
        messages = [{"role": "user", "content": "Reply with the single word: ok"}]
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._chat_headers(),
                    json={"model": self.model, "messages": messages, "max_tokens": 5},
                )
                resp.raise_for_status()
        except httpx.TimeoutException:
            raise ValueError(f"AI API timed out connecting to {self.base_url}") from None
        except httpx.ConnectError as e:
            raise ValueError(f"Could not connect to AI API at {self.base_url}: {e}") from None
        except httpx.HTTPStatusError as e:
            raise ValueError(self._format_http_error(e)) from None
        return {"message": "Connection successful"}

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
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._chat_headers(),
                    json={"model": self.model, "messages": messages, "response_format": {"type": "json_object"}},
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                data = json.loads(content)
        except httpx.TimeoutException:
            raise ValueError(f"AI planning timed out connecting to {self.base_url}") from None
        except httpx.ConnectError as e:
            raise ValueError(f"Could not connect to AI API at {self.base_url}: {e}") from None
        except httpx.HTTPStatusError as e:
            raise ValueError(self._format_http_error(e)) from None
        except (KeyError, json.JSONDecodeError) as e:
            raise ValueError(f"AI API returned an unexpected response: {e}") from None
        try:
            raw_plan = OperationPlan(**data)
        except Exception as e:
            raise ValueError(f"Invalid plan: [{e}]") from None
        bar_range = payload.get("selection", {}).get("master_bar_range", [0, 4])
        ppq = payload.get("global", {}).get("master_ppq", 480)
        songs = payload.get("global", {}).get("songs", [])
        song_segments = [
            {"id": s["id"], "master_start_tick": s["master_start_tick"], "master_end_tick": s["master_end_tick"]}
            for s in songs
            if "master_start_tick" in s
        ]
        resolved = resolve_plan(
            raw_plan,
            ppq=ppq,
            bar_range=bar_range,
            song_segments=song_segments or None,
        )
        plan, errors = self.validate_plan(resolved.model_dump())
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
