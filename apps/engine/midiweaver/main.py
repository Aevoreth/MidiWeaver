from __future__ import annotations

import argparse
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import httpx

from midiweaver import __version__
from midiweaver.ai.agent import ArrangementAgent, ArrangementPlanner
from midiweaver.ai.ask import AskAssistant
from midiweaver.ai.planner import AIPlanner, OllamaClientStub, PromptBuilder, resolve_plan, _song_segments_from_timeline
from midiweaver.ai.tools import ToolExecutor, plan_store, agent_session_store
from midiweaver.ai.selection import normalize_selection
from midiweaver.audio.engine import AudioEngine, MidiExporter
from midiweaver.models import ArrangementPlan, Operation, OperationPlan, TrackMappingEntry
from midiweaver.ops.executor import OpExecutor
from midiweaver.project.store import create_project, get_project, open_project
from midiweaver.query.context import (
    analyze_region,
    get_loop_candidates,
    get_timeline_summary,
    get_transition_context,
    measure_region,
    query_notes,
)
from midiweaver.settings_store import load_settings, save_settings, settings_public_view

app = FastAPI(title="MidiWeaver Engine", version=__version__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_settings = load_settings()
_audio = AudioEngine()
_exporter = MidiExporter()
_executor = OpExecutor()
_prompt_builder = PromptBuilder()
_ollama_stub = OllamaClientStub()


class HealthResponse(BaseModel):
    status: str
    version: str


class CreateProjectRequest(BaseModel):
    path: str
    name: str
    master_ppq: int = 480


class ApplyOpsRequest(BaseModel):
    project_path: str
    ops: list[Operation]
    label: str = "Apply ops"


class AIPlanRequest(BaseModel):
    project_path: str
    user_prompt: str
    selection: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    mock: bool = False


class ApplyPlanRequest(BaseModel):
    project_path: str
    plan: OperationPlan
    enabled_op_indices: list[int] | None = None
    transition_id: str | None = None


class DryRunOpsRequest(BaseModel):
    project_path: str
    ops: list[Operation]


class AskRequest(BaseModel):
    project_path: str
    messages: list[dict[str, Any]]
    selection: dict[str, Any] = Field(default_factory=dict)
    mock: bool = False


class AgentRunRequest(BaseModel):
    project_path: str
    prompt: str
    selection: dict[str, Any] = Field(default_factory=dict)
    session_id: str | None = None
    plan_id: str | None = None
    mock: bool = False


class AgentCancelRequest(BaseModel):
    session_id: str


class TrackMappingRequest(BaseModel):
    project_path: str
    mapping: list[TrackMappingEntry]


class ReorderSongsRequest(BaseModel):
    project_path: str
    song_ids: list[str]


class TemplateSaveRequest(BaseModel):
    project_path: str
    name: str
    transition_id: str
    constraints: dict[str, Any] = Field(default_factory=dict)


class TemplateApplyRequest(BaseModel):
    project_path: str
    template_id: str
    from_song_id: str
    to_song_id: str


class ExportMidiRequest(BaseModel):
    project_path: str
    output_path: str


class RenderRequest(BaseModel):
    project_path: str
    output_path: str
    format: str = "wav"
    start_tick: int = 0
    end_tick: int | None = None


class MixerUpdateRequest(BaseModel):
    track_id: str
    mute: bool | None = None
    solo: bool | None = None
    volume: float | None = None


class TransportRequest(BaseModel):
    action: str
    tick: int = 0
    project_path: str | None = None


class SettingsUpdate(BaseModel):
    ai_base_url: str | None = None
    ai_api_key: str | None = None
    ai_model: str | None = None
    ai_agent_model: str | None = None
    ai_agent_max_steps: int | None = None
    clear_ai_api_key: bool | None = None
    ollama_enabled: bool | None = None
    audio_backend: str | None = None
    soundfont_path: str | None = None
    midi_device: str | None = None


def _apply_settings_update(body: SettingsUpdate) -> None:
    global _settings
    updates = body.model_dump(exclude_none=True)

    if updates.pop("clear_ai_api_key", False):
        _settings = _settings.model_copy(update={"ai_api_key": ""})

    new_key = updates.pop("ai_api_key", None)
    if new_key:
        _settings = _settings.model_copy(update={"ai_api_key": new_key})

    if updates:
        _settings = _settings.model_copy(update=updates)

    save_settings(_settings)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", version=__version__)


@app.get("/api/settings")
def get_settings() -> dict[str, Any]:
    return settings_public_view(_settings)


@app.post("/api/settings")
def update_settings(body: SettingsUpdate) -> dict[str, Any]:
    global _audio
    _apply_settings_update(body)
    _audio = AudioEngine(
        backend=_settings.audio_backend,
        soundfont_path=_settings.soundfont_path,
        midi_device=_settings.midi_device,
    )
    return settings_public_view(_settings)


@app.post("/api/ai/test-connection")
async def test_ai_connection() -> dict[str, Any]:
    planner = AIPlanner(_settings.ai_base_url, _settings.ai_api_key, _settings.ai_model)
    try:
        result = await planner.test_connection()
        return {"ok": True, "model": _settings.ai_model, **result}
    except ValueError as e:
        return {"ok": False, "model": _settings.ai_model, "error": str(e)}


@app.post("/api/projects/create")
def api_create_project(body: CreateProjectRequest) -> dict[str, Any]:
    store = create_project(body.path, body.name, body.master_ppq)
    return {"path": body.path, "meta": store.project_json.read_text(encoding="utf-8")}


@app.post("/api/projects/open")
def api_open_project(body: CreateProjectRequest) -> dict[str, Any]:
    store = open_project(body.path)
    meta = store.load()
    return {"path": body.path, "meta": meta.model_dump(), "timeline": store.timeline.model_dump()}


def _load_meta(store: Any) -> Any:
    import json
    from midiweaver.models import ProjectMetadata

    return ProjectMetadata(**json.loads(store.project_json.read_text(encoding="utf-8")))


@app.get("/api/projects/{project_path:path}/query/timeline")
def query_timeline(project_path: str) -> dict[str, Any]:
    store = get_project(project_path)
    meta = _load_meta(store)
    return get_timeline_summary(store.timeline, meta.track_mapping)


@app.get("/api/projects/{project_path:path}/query/notes")
def query_notes_endpoint(
    project_path: str,
    start_bar: float | None = None,
    end_bar: float | None = None,
    start_tick: int | None = None,
    end_tick: int | None = None,
    song_id: str | None = None,
    track_id: str | None = None,
    limit: int = 500,
    offset: int = 0,
) -> dict[str, Any]:
    store = get_project(project_path)
    return query_notes(
        store.timeline,
        start_bar=start_bar,
        end_bar=end_bar,
        start_tick=start_tick,
        end_tick=end_tick,
        song_id=song_id,
        track_id=track_id,
        limit=min(limit, 500),
        offset=offset,
    )


@app.get("/api/projects/{project_path:path}/query/transition/{transition_id}")
def query_transition(project_path: str, transition_id: str) -> dict[str, Any]:
    store = get_project(project_path)
    return get_transition_context(store.timeline, transition_id)


@app.get("/api/projects/{project_path:path}/query/analyze")
def query_analyze(
    project_path: str,
    start_bar: float = Query(...),
    end_bar: float = Query(...),
) -> dict[str, Any]:
    store = get_project(project_path)
    return analyze_region(store.timeline, [start_bar, end_bar])


@app.get("/api/projects/{project_path:path}/query/loops/{song_id}")
def query_loops(project_path: str, song_id: str) -> dict[str, Any]:
    store = get_project(project_path)
    return get_loop_candidates(store.timeline, song_id)


@app.get("/api/projects/{project_path:path}/query/measure")
def query_measure_endpoint(
    project_path: str,
    start_bar: float | None = None,
    end_bar: float | None = None,
    song_id: str | None = None,
) -> dict[str, Any]:
    store = get_project(project_path)
    return measure_region(
        store.timeline,
        start_bar=start_bar,
        end_bar=end_bar,
        song_id=song_id,
    )


@app.post("/api/projects/dry-run-ops")
def dry_run_ops(body: DryRunOpsRequest) -> dict[str, Any]:
    store = get_project(body.project_path)
    errors: list[str] = []
    for op in body.ops:
        errors.extend(_executor.validate_op(op))
    if errors:
        raise HTTPException(status_code=400, detail=errors)
    diff = _executor.dry_run(store.get_context(), body.ops)
    return diff.model_dump()


@app.get("/api/projects/{project_path:path}/timeline")
def get_timeline(project_path: str) -> dict[str, Any]:
    store = get_project(project_path)
    return store.timeline.model_dump()


@app.post("/api/projects/import")
async def import_midi(project_path: str, file: UploadFile = File(...)) -> dict[str, Any]:
    store = get_project(project_path)
    suffix = Path(file.filename or "import.mid").suffix or ".mid"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)
    segment = store.import_midi(tmp_path, display_name=Path(file.filename or "import").stem)
    tmp_path.unlink(missing_ok=True)
    return {"segment": segment.model_dump(), "timeline": store.timeline.model_dump()}


@app.post("/api/projects/apply-ops")
def apply_ops(body: ApplyOpsRequest) -> dict[str, Any]:
    store = get_project(body.project_path)
    rev = store.apply_ops(body.ops, body.label)
    return {"revision": rev.model_dump(), "timeline": store.timeline.model_dump()}


@app.post("/api/projects/undo")
def undo(project_path: str = Query(...)) -> dict[str, Any]:
    store = get_project(project_path)
    rev = store.undo()
    return {"revision": rev.model_dump() if rev else None, "timeline": store.timeline.model_dump()}


@app.post("/api/projects/redo")
def redo(project_path: str = Query(...)) -> dict[str, Any]:
    store = get_project(project_path)
    rev = store.redo()
    return {"revision": rev.model_dump() if rev else None, "timeline": store.timeline.model_dump()}


@app.get("/api/projects/{project_path:path}/revisions")
def list_revisions(project_path: str) -> list[dict[str, Any]]:
    store = get_project(project_path)
    return [r.model_dump() for r in store.list_revisions()]


@app.get("/api/projects/{project_path:path}/diff")
def compare_revisions(project_path: str, rev_a: int, rev_b: int) -> dict[str, Any]:
    store = get_project(project_path)
    diff = store.compare_revisions(rev_a, rev_b)
    return diff.model_dump()


@app.post("/api/projects/track-mapping")
def update_track_mapping(body: TrackMappingRequest) -> dict[str, str]:
    store = get_project(body.project_path)
    store.update_track_mapping(body.mapping)
    return {"status": "ok"}


@app.post("/api/projects/reorder-songs")
def reorder_songs(body: ReorderSongsRequest) -> dict[str, Any]:
    store = get_project(body.project_path)
    store.reorder_songs(body.song_ids)
    return {"timeline": store.timeline.model_dump()}


@app.post("/api/ai/ask")
async def ai_ask(body: AskRequest) -> dict[str, Any]:
    store = get_project(body.project_path)
    tool_executor = ToolExecutor(store, _executor)
    assistant = AskAssistant(_settings.ai_base_url, _settings.ai_api_key, _settings.ai_model)
    use_mock = body.mock or not _settings.ai_api_key
    try:
        result = await assistant.chat(body.messages, tool_executor, mock=use_mock)
    except httpx.HTTPStatusError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    return result


@app.post("/api/ai/plan")
async def ai_plan(body: AIPlanRequest) -> dict[str, Any]:
    store = get_project(body.project_path)
    meta = _load_meta(store)
    selection = normalize_selection(body.selection)
    payload = _prompt_builder.build(
        store.timeline,
        meta.track_mapping,
        selection,
        body.user_prompt,
        body.constraints,
    )
    tool_executor = ToolExecutor(store, _executor)
    planner = ArrangementPlanner(_settings.ai_base_url, _settings.ai_api_key, _settings.ai_model)
    use_mock = body.mock or not _settings.ai_api_key
    try:
        plan = await planner.plan(payload, tool_executor, mock=use_mock)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    plan_id = plan_store.put(plan)
    mode = "mock" if use_mock else "live"
    return {
        "payload": payload,
        "plan": plan.model_dump(),
        "plan_id": plan_id,
        "mode": mode,
    }


@app.get("/api/ai/plan/{plan_id}")
def get_stored_plan(plan_id: str) -> dict[str, Any]:
    plan = plan_store.get(plan_id)
    if not plan:
        raise HTTPException(404, "Plan not found or expired")
    return {"plan": plan.model_dump(), "plan_id": plan_id}


@app.post("/api/ai/agent/run")
async def agent_run(body: AgentRunRequest) -> dict[str, Any]:
    store = get_project(body.project_path)
    agent_model = _settings.ai_agent_model or _settings.ai_model
    agent = ArrangementAgent(
        _settings.ai_base_url,
        _settings.ai_api_key,
        agent_model,
        max_steps=_settings.ai_agent_max_steps,
    )
    use_mock = body.mock or not _settings.ai_api_key
    try:
        result = await agent.run(
            store=store,
            prompt=body.prompt,
            selection=normalize_selection(body.selection),
            session_id=body.session_id,
            plan_id=body.plan_id,
            mock=use_mock,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    return result


@app.post("/api/ai/agent/cancel")
def agent_cancel(body: AgentCancelRequest) -> dict[str, str]:
    agent_session_store.cancel(body.session_id)
    return {"status": "cancelled", "session_id": body.session_id}


@app.get("/api/ai/agent/session/{session_id}")
def agent_session(session_id: str) -> dict[str, Any]:
    session = agent_session_store.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found or expired")
    return session


@app.post("/api/ai/validate-plan")
def validate_plan(plan: OperationPlan) -> dict[str, Any]:
    planner = AIPlanner(_settings.ai_base_url, _settings.ai_api_key, _settings.ai_model)
    validated, errors = planner.validate_plan(plan.model_dump())
    return {"valid": validated is not None, "errors": errors, "plan": validated.model_dump() if validated else None}


@app.post("/api/ai/apply-plan")
def apply_plan(body: ApplyPlanRequest) -> dict[str, Any]:
    store = get_project(body.project_path)
    plan = resolve_plan(
        body.plan,
        ppq=store.timeline.master_ppq,
        song_segments=_song_segments_from_timeline(store.timeline),
        timeline=store.timeline,
        transition_id=body.transition_id,
        merge_selected_tempo_option=True,
    )
    planner = AIPlanner(_settings.ai_base_url, _settings.ai_api_key, _settings.ai_model)
    validated, errors = planner.validate_plan(plan.model_dump())
    if validated is None:
        raise HTTPException(status_code=400, detail=f"Invalid plan: {errors}")
    ops = validated.ops
    if body.enabled_op_indices is not None:
        enabled = set(body.enabled_op_indices)
        ops = [
            op.model_copy(update={"enabled": i in enabled})
            for i, op in enumerate(validated.ops)
        ]
    rev = store.apply_ops(ops, label=validated.plan_summary[:80])
    return {"revision": rev.model_dump(), "timeline": store.timeline.model_dump()}


@app.get("/api/ollama/status")
def ollama_status() -> dict[str, str]:
    return _ollama_stub.status()


@app.post("/api/templates/save")
def save_template(body: TemplateSaveRequest) -> dict[str, str]:
    store = get_project(body.project_path)
    trans = next((t for t in store.timeline.transitions if t.id == body.transition_id), None)
    if not trans:
        raise HTTPException(404, "Transition not found")
    tid = store.save_template(body.name, trans, body.constraints)
    return {"template_id": tid}


@app.get("/api/templates/{project_path:path}")
def list_templates(project_path: str) -> list[dict[str, Any]]:
    store = get_project(project_path)
    return store.list_templates()


@app.post("/api/templates/apply")
def apply_template(body: TemplateApplyRequest) -> dict[str, Any]:
    store = get_project(body.project_path)
    trans = store.apply_template(body.template_id, body.from_song_id, body.to_song_id)
    import json
    from midiweaver.models import ProjectMetadata

    meta = ProjectMetadata(**json.loads(store.project_json.read_text(encoding="utf-8")))
    meta.transitions = [t if t.id != trans.id else trans for t in meta.transitions]
    if not any(t.from_song_id == body.from_song_id for t in meta.transitions):
        meta.transitions.append(trans)
    store.save(meta)
    store._rebuild_timeline(meta)
    return {"transition": trans.model_dump(), "timeline": store.timeline.model_dump()}


@app.post("/api/export/midi")
def export_midi(body: ExportMidiRequest) -> dict[str, Any]:
    store = get_project(body.project_path)
    import json
    from midiweaver.models import ProjectMetadata

    meta = ProjectMetadata(**json.loads(store.project_json.read_text(encoding="utf-8")))
    report = _exporter.export_type1(store.timeline, body.output_path, meta.track_mapping)
    return report.model_dump()


@app.post("/api/audio/render")
def render_audio(body: RenderRequest) -> dict[str, Any]:
    store = get_project(body.project_path)
    import json
    from midiweaver.models import ProjectMetadata

    meta = ProjectMetadata(**json.loads(store.project_json.read_text(encoding="utf-8")))
    wav = _audio.render_wav(
        store.timeline,
        body.output_path if body.format == "wav" else str(Path(body.output_path).with_suffix(".wav")),
        body.start_tick,
        body.end_tick,
        track_mapping=meta.track_mapping,
    )
    result = {"wav": str(wav)}
    if body.format == "ogg":
        ogg = _audio.render_ogg(wav, Path(body.output_path).with_suffix(".ogg"))
        result["ogg"] = str(ogg)
    return result


@app.get("/api/audio/devices")
def audio_devices() -> dict[str, Any]:
    return {"midi_outputs": _audio.list_midi_devices()}


@app.post("/api/audio/mixer")
def update_mixer(body: MixerUpdateRequest) -> dict[str, Any]:
    _audio.set_mixer(body.track_id, body.mute, body.solo, body.volume)
    return _audio.get_mixer()


@app.get("/api/audio/mixer")
def get_mixer() -> dict[str, Any]:
    return _audio.get_mixer()


@app.post("/api/audio/transport")
def transport(body: TransportRequest) -> dict[str, Any]:
    if body.action == "play":
        timeline = _audio._timeline
        if body.project_path:
            store = get_project(body.project_path)
            timeline = store.timeline
        _audio.play(timeline, body.tick)
    elif body.action == "pause":
        _audio.pause()
    elif body.action == "stop":
        _audio.stop()
    elif body.action == "seek":
        _audio.seek(body.tick)
    else:
        raise HTTPException(400, f"Unknown action: {body.action}")
    return _audio.transport_state()


@app.get("/api/audio/transport")
def get_transport() -> dict[str, Any]:
    return _audio.transport_state()


def cli_main() -> None:
    parser = argparse.ArgumentParser(description="MidiWeaver Engine Sidecar")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    cli_main()
