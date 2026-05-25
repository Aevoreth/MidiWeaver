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


def test_echo_notes_by_track(project_bundle):
    from midiweaver.project.store import get_project

    store = get_project(str(project_bundle))
    ctx = store.get_context()
    executor = OpExecutor()
    seg = store.timeline.segments[0]
    track = seg.analysis.tracks[0]
    before = len(track.notes)
    op = Operation(
        op_type="echo_notes",
        params={
            "song_id": seg.id,
            "track_id": track.track_id,
            "repeats": 2,
            "interval_ticks": 480,
            "velocity_decay": 0.5,
        },
    )
    errors = executor.validate_op(op)
    assert not errors
    new_ctx, diff = executor.apply(ctx, [op])
    after = len(new_ctx.timeline.segments[0].analysis.tracks[0].notes)
    assert after > before


def test_shift_song(project_bundle):
    from midiweaver.project.store import get_project

    store = get_project(str(project_bundle))
    ctx = store.get_context()
    executor = OpExecutor()
    seg = store.timeline.segments[0]
    ppq = store.timeline.master_ppq
    before = seg.analysis.tracks[0].notes[0].start_tick
    op = Operation(
        op_type="shift_song",
        params={"song_id": seg.id, "delta_ticks": ppq * 4},
    )
    new_ctx, _ = executor.apply(ctx, [op])
    after = new_ctx.timeline.segments[0].analysis.tracks[0].notes[0].start_tick
    assert after == before + ppq * 4


def test_shift_song_earlier_overlap_is_audible(project_bundle):
    from midiweaver.normalize.timeline import collect_master_notes
    from midiweaver.project.store import get_project

    store = get_project(str(project_bundle))
    ctx = store.get_context()
    executor = OpExecutor()
    seg = store.timeline.segments[1]
    ppq = store.timeline.master_ppq
    overlap = ppq * 4 * 2
    before_start = seg.master_start_tick

    new_ctx, _ = executor.apply(
        ctx,
        [Operation(op_type="shift_song", params={"song_id": seg.id, "delta_ticks": -overlap})],
    )
    shifted = new_ctx.timeline.segments[1]
    assert shifted.master_start_offset_ticks == -overlap
    assert shifted.master_start_tick == before_start - overlap

    notes = collect_master_notes(new_ctx.timeline)
    song2_notes = [n for n in notes if n["song_id"] == seg.id]
    assert song2_notes, "shifted song should have audible notes"
    assert min(n["start_tick"] for n in song2_notes) < before_start
    assert all(n["velocity"] > 0 for n in song2_notes)


def test_echo_notes_playable_after_apply(project_bundle):
    from midiweaver.normalize.timeline import collect_master_notes
    from midiweaver.project.store import get_project

    store = get_project(str(project_bundle))
    ctx = store.get_context()
    executor = OpExecutor()
    seg = store.timeline.segments[0]
    track = seg.analysis.tracks[0]
    before_master = len(collect_master_notes(ctx.timeline))

    op = Operation(
        op_type="echo_notes",
        params={
            "song_id": seg.id,
            "track_id": track.track_id,
            "repeats": 2,
            "interval_ticks": 480,
            "velocity_decay": 0.5,
        },
    )
    new_ctx, diff = executor.apply(ctx, [op])
    after_master = collect_master_notes(new_ctx.timeline)
    assert len(after_master) > before_master
    assert len(diff.added_notes) >= 2
    echoed = [n for n in after_master if n["track_id"] == track.track_id]
    assert len(echoed) > len(track.notes)


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
