from midiweaver.ai.op_resolve import resolve_op_params
from midiweaver.models import Operation
from midiweaver.normalize.timeline import collect_master_notes, ticks_to_bars
from midiweaver.ops.executor import OpExecutor
from midiweaver.project.store import get_project


def test_loop_region_use_last_bars(project_bundle):
    store = get_project(str(project_bundle))
    seg = store.timeline.segments[0]
    op = resolve_op_params(
        Operation(
            op_type="loop_region",
            params={"song_id": seg.id, "use_last_bars": True, "repeat_count": 1},
        ),
        store.timeline,
    )
    assert "source_start_bar" in op.params
    assert "source_end_bar" in op.params
    assert op.params["source_start_bar"] >= 0


def test_loop_region_from_selection_resolve(project_bundle):
    store = get_project(str(project_bundle))
    seg = store.timeline.segments[0]
    op = resolve_op_params(
        Operation(op_type="loop_region", params={"repeat_count": 2}),
        store.timeline,
        {"master_bar_range": [0.0, 2.0], "scope": "edit"},
    )
    assert op.params["song_id"] == seg.id
    assert "source_start_bar" in op.params
    assert "source_end_bar" in op.params
    assert op.params.get("paste_mode") == "after_selection"
    assert "dest_start_tick" in op.params


def test_loop_region_master_bar_conversion(project_bundle):
    store = get_project(str(project_bundle))
    seg = store.timeline.segments[0]
    bpm = seg.analysis.estimated_bpm
    beats = seg.analysis.time_sig[0]
    ppq = store.timeline.master_ppq
    master_end = ticks_to_bars(seg.master_end_tick, ppq, bpm, beats)

    op = resolve_op_params(
        Operation(
            op_type="loop_region",
            params={
                "song_id": seg.id,
                "source_start_bar": master_end - 1,
                "source_end_bar": master_end,
                "bar_space": "master",
                "repeat_count": 1,
            },
        ),
        store.timeline,
    )
    assert op.params["source_start_bar"] < seg.analysis.bar_count


def test_shift_song_delta_bars_alias(project_bundle):
    store = get_project(str(project_bundle))
    seg = store.timeline.segments[0]
    op = resolve_op_params(
        Operation(
            op_type="shift_song",
            params={"song_id": seg.id, "delta_bars": 2},
        ),
        store.timeline,
    )
    assert op.params["delta_ticks"] == 2 * 4 * store.timeline.master_ppq


def test_insert_master_gap_from_selection(project_bundle):
    store = get_project(str(project_bundle))
    trans = store.timeline.transitions[0]
    op = resolve_op_params(
        Operation(
            op_type="insert_master_gap",
            params={"gap_bars": 8},
        ),
        store.timeline,
        {"transition_id": trans.id},
    )
    assert op.params["after_song_id"] == trans.from_song_id
    assert op.params["bars"] == 8


def test_loop_region_params_from_candidates_apply(project_bundle):
    from midiweaver.query.context import get_loop_candidates

    store = get_project(str(project_bundle))
    seg = store.timeline.segments[0]
    candidates = get_loop_candidates(store.timeline, seg.id)
    params = dict(candidates["loop_region_params"])
    params["repeat_count"] = 1
    op = resolve_op_params(
        Operation(op_type="loop_region", params=params),
        store.timeline,
    )
    ctx = store.get_context()
    executor = OpExecutor()
    before = len(collect_master_notes(ctx.timeline))
    new_ctx, diff = executor.apply(ctx, [op])
    after = len(collect_master_notes(new_ctx.timeline))
    assert after > before
    assert len(diff.added_notes) > 0


def test_copy_notes_from_candidate_params(project_bundle):
    from midiweaver.query.context import get_loop_candidates

    store = get_project(str(project_bundle))
    seg = store.timeline.segments[0]
    candidates = get_loop_candidates(store.timeline, seg.id)
    op = resolve_op_params(
        Operation(op_type="copy_notes", params=dict(candidates["copy_notes_params"])),
        store.timeline,
    )
    ctx = store.get_context()
    executor = OpExecutor()
    before = len(collect_master_notes(ctx.timeline))
    new_ctx, diff = executor.apply(ctx, [op])
    after = len(collect_master_notes(new_ctx.timeline))
    assert after > before
    assert len(diff.added_notes) > 0
