from midiweaver.ai.op_resolve import resolve_op_params
from midiweaver.models import Operation
from midiweaver.normalize.timeline import collect_master_notes
from midiweaver.ops.executor import OpExecutor
from midiweaver.project.store import get_project


def test_add_dj_drums_intro_shifts_drums(project_bundle):
    store = get_project(str(project_bundle))
    seg = store.timeline.segments[0]
    if not seg.analysis:
        return
    drum_track = next((t for t in seg.analysis.tracks if t.is_drum), None)
    if not drum_track or not drum_track.notes:
        return
    min_before = min(n.start_tick for n in drum_track.notes)
    ctx = store.get_context()
    executor = OpExecutor()
    op = Operation(
        op_type="add_dj_drums",
        params={"song_id": seg.id, "placement": "intro", "bars": 2, "style": "four_on_floor", "source": "template"},
    )
    new_ctx, diff = executor.apply(ctx, [op])
    assert len(diff.added_notes) > 0
    new_seg = new_ctx.timeline.segments[0]
    new_drums = next(t for t in new_seg.analysis.tracks if t.is_drum)
    min_after = min(n.start_tick for n in new_drums.notes)
    assert min_after == 0
    assert any(n.start_tick >= min_before + 2 * store.timeline.master_ppq * 4 for n in new_drums.notes)


def test_add_dj_drums_outro(project_bundle):
    store = get_project(str(project_bundle))
    seg = store.timeline.segments[0]
    before = len(collect_master_notes(store.timeline))
    ctx = store.get_context()
    executor = OpExecutor()
    op = Operation(
        op_type="add_dj_drums",
        params={"song_id": seg.id, "placement": "outro", "bars": 2, "style": "phrase_repeat", "source": "auto"},
    )
    new_ctx, diff = executor.apply(ctx, [op])
    after = len(collect_master_notes(new_ctx.timeline))
    assert after > before
    assert len(diff.added_notes) > 0


def test_add_dj_drums_resolve_from_selection(project_bundle):
    store = get_project(str(project_bundle))
    seg = store.timeline.segments[0]
    op = resolve_op_params(
        Operation(op_type="add_dj_drums", params={"placement": "outro"}),
        store.timeline,
        {"master_bar_range": [0.0, 1.0], "scope": "edit"},
    )
    assert op.params["song_id"] == seg.id
    assert op.params["source"] == "selection"
    assert op.params["master_bar_range"] == [0.0, 1.0]


def test_loop_region_after_selection_placement(project_bundle):
    store = get_project(str(project_bundle))
    seg = store.timeline.segments[0]
    if not seg.analysis:
        return
    a = seg.analysis
    ppq = store.timeline.master_ppq
    beats = a.time_sig[0]
    bar_ticks = ppq * beats
    src_start_bar = 0.0
    src_end_bar = 1.0
    src_start = a.trim_start_tick + int(src_start_bar * bar_ticks)
    src_end = a.trim_start_tick + int(src_end_bar * bar_ticks)

    ctx = store.get_context()
    executor = OpExecutor()
    op = Operation(
        op_type="loop_region",
        params={
            "song_id": seg.id,
            "source_start_bar": src_start_bar,
            "source_end_bar": src_end_bar,
            "repeat_count": 1,
            "paste_mode": "after_selection",
        },
    )
    new_ctx, diff = executor.apply(ctx, [op])
    assert diff.added_notes
    first_added = min(diff.added_notes, key=lambda n: n.get("start_tick", 0))
    assert first_added["start_tick"] >= src_end - 2
