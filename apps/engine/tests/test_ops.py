from midiweaver.models import Operation
from midiweaver.ops.executor import OpContext, OpExecutor
from midiweaver.project.store import create_project


def test_trim_silence_op(project_bundle):
    from midiweaver.project.store import get_project

    store = get_project(str(project_bundle))
    ctx = store.get_context()
    executor = OpExecutor()
    song_id = store.timeline.segments[0].id
    op = Operation(op_type="trim_silence", params={"song_id": song_id})
    new_ctx, diff = executor.apply(ctx, [op])
    assert new_ctx.timeline.total_ticks >= 0


def test_tempo_ramp_op(project_bundle):
    from midiweaver.project.store import get_project

    store = get_project(str(project_bundle))
    ctx = store.get_context()
    executor = OpExecutor()
    end = store.timeline.total_ticks
    op = Operation(
        op_type="tempo_ramp",
        params={
            "start_tick": 0,
            "end_tick": min(end, 1920),
            "start_bpm": 120,
            "end_bpm": 140,
            "policy": "linear_ramp",
        },
    )
    new_ctx, diff = executor.apply(ctx, [op])
    assert len(new_ctx.timeline.tempo_events) >= 1


def test_extend_drums(project_bundle):
    from midiweaver.project.store import get_project

    store = get_project(str(project_bundle))
    before = len(store.timeline.segments[0].analysis.tracks[0].notes)
    rev = store.apply_ops(
        [Operation(op_type="extend_drums", params={"song_id": store.timeline.segments[0].id, "bars": 1})],
        "extend",
    )
    after_track = store.timeline.segments[0].analysis.tracks[0]
    assert len(after_track.notes) >= before


def test_undo_redo(project_bundle):
    from midiweaver.project.store import get_project

    store = get_project(str(project_bundle))
    store.apply_ops(
        [Operation(op_type="mute_track", params={"track_id": "track_000", "mute": True})],
        "mute",
    )
    undone = store.undo()
    assert undone is not None
    redone = store.redo()
    assert redone is not None
