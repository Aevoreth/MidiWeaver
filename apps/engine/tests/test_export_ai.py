from pathlib import Path

import mido

from midiweaver.ai.planner import AIPlanner
from midiweaver.audio.engine import MidiExporter
from midiweaver.project.store import get_project


def test_export_type1(project_bundle, tmp_path):
    store = get_project(str(project_bundle))
    out = tmp_path / "merged.mid"
    exporter = MidiExporter()
    report = exporter.export_type1(store.timeline, out)
    assert out.exists()
    assert report.format == "SMF Type 1"
    assert report.track_count >= 1


def test_export_preserves_program_and_timing(project_bundle, tmp_path):
    store = get_project(str(project_bundle))
    out = tmp_path / "merged.mid"
    MidiExporter().export_type1(store.timeline, out)

    exported = mido.MidiFile(str(out))
    melody_track = next(
        (t for t in exported.tracks if any(m.type == "track_name" and m.name == "Melody" for m in t if m.is_meta)),
        None,
    )
    assert melody_track is not None

    abs_tick = 0
    programs: list[int] = []
    note_on_ticks: list[int] = []
    for msg in melody_track:
        abs_tick += msg.time
        if msg.type == "program_change":
            programs.append(msg.program)
        if msg.type == "note_on" and msg.velocity > 0:
            note_on_ticks.append(abs_tick)

    assert 33 in programs
    assert note_on_ticks, "exported melody should contain notes"
    assert note_on_ticks[0] == 0, "first melody note should start at tick 0 within its track"


def test_ai_plan_mock(project_bundle):
    from midiweaver.models import ProjectMetadata
    import json

    store = get_project(str(project_bundle))
    meta = ProjectMetadata(**json.loads(store.project_json.read_text(encoding="utf-8")))
    from midiweaver.ai.planner import PromptBuilder

    pb = PromptBuilder()
    payload = pb.build(
        store.timeline,
        meta.track_mapping,
        {"master_bar_range": [0, 2], "scope": "transition"},
        "Make it groovy",
    )
    planner = AIPlanner("", "", "test")
    import asyncio

    plan = asyncio.run(planner.plan(payload, mock=True))
    assert len(plan.tempo_options) == 3
    validated, errors = planner.validate_plan(plan.model_dump())
    assert validated is not None
    assert not errors
