from __future__ import annotations

import copy
import uuid
from typing import Any

from midiweaver.models import (
    AnalysisSnapshot,
    MasterTimeline,
    NoteEvent,
    Operation,
    OperationPlan,
    RevisionDiff,
    TrackData,
)
from midiweaver.normalize.timeline import apply_tempo_ramp, build_master_timeline, sync_segment_trim_bounds
from midiweaver.normalize.notes import ensure_note_id


class OpContext:
    def __init__(
        self,
        timeline: MasterTimeline,
        segments: list | None = None,
    ):
        self.timeline = timeline
        self.segments = segments or timeline.segments


class OpExecutor:
    """Validate, dry-run, and apply operations non-destructively."""

    def validate_op(self, op: Operation) -> list[str]:
        errors: list[str] = []
        if op.op_type not in ALLOWED_OPS:
            errors.append(f"Unknown op_type: {op.op_type}")
            return errors

        p = op.params
        if op.op_type == "tempo_ramp":
            for key in ("start_tick", "end_tick", "start_bpm", "end_bpm"):
                if key not in p:
                    errors.append(f"tempo_ramp missing {key}")
            if p.get("start_bpm", 0) < 20 or p.get("end_bpm", 0) > 300:
                errors.append("BPM out of bounds (20-300)")
        elif op.op_type == "copy_notes":
            for key in ("source_start_tick", "source_end_tick", "dest_tick"):
                if key not in p:
                    errors.append(f"copy_notes missing {key}")
        elif op.op_type == "echo_notes":
            has_region = "source_start_tick" in p and "source_end_tick" in p
            has_track = ("track_id" in p or "master_track_id" in p) and "song_id" in p
            if not has_region and not has_track:
                errors.append(
                    "echo_notes needs source_start_tick/source_end_tick or song_id with track_id"
                )
        elif op.op_type == "set_transition_markers":
            has_trans = "transition_id" in p
            has_songs = "from_song_id" in p and "to_song_id" in p
            if not has_trans and not has_songs:
                errors.append(
                    "set_transition_markers missing transition_id or from_song_id/to_song_id"
                )
        elif op.op_type == "shift_song":
            if "song_id" not in p:
                errors.append("shift_song missing song_id")
            elif "delta_ticks" not in p and "bars" not in p:
                errors.append("shift_song missing delta_ticks or bars")
        elif op.op_type == "manual_edit_note":
            for key in ("song_id", "track_id"):
                if key not in p:
                    errors.append(f"manual_edit_note missing {key}")
        elif op.op_type in ("transpose_region", "quantize_region"):
            for key in ("start_tick", "end_tick"):
                if key not in p:
                    errors.append(f"{op.op_type} missing {key}")
        elif op.op_type == "mute_track" and "track_id" not in p:
            errors.append("mute_track missing track_id")
        elif op.op_type == "insert_master_gap":
            if "after_song_id" not in p:
                errors.append("insert_master_gap missing after_song_id")
            elif "bars" not in p and "ticks" not in p:
                errors.append("insert_master_gap missing bars or ticks")
        elif op.op_type == "loop_region":
            if "song_id" not in p:
                errors.append("loop_region missing song_id")
            elif "source_start_bar" not in p or "source_end_bar" not in p:
                errors.append("loop_region missing source_start_bar or source_end_bar")
            elif "repeat_count" not in p and "target_total_bars" not in p:
                errors.append("loop_region missing repeat_count or target_total_bars")
        elif op.op_type == "delete_notes_in_region":
            for key in ("start_tick", "end_tick"):
                if key not in p:
                    errors.append(f"delete_notes_in_region missing {key}")
        return errors

    def validate_plan(self, plan: OperationPlan) -> list[str]:
        errors: list[str] = []
        for op in plan.ops:
            if op.enabled:
                errors.extend(self.validate_op(op))
        return errors

    def dry_run(self, ctx: OpContext, ops: list[Operation]) -> RevisionDiff:
        before = self._snapshot_notes(ctx)
        after_ctx = copy.deepcopy(ctx)
        for op in ops:
            if op.enabled:
                after_ctx = self._apply_one(after_ctx, op)
        after = self._snapshot_notes(after_ctx)
        return self._compute_diff(before, after)

    def apply(self, ctx: OpContext, ops: list[Operation]) -> tuple[OpContext, RevisionDiff]:
        diff = self.dry_run(ctx, ops)
        new_ctx = copy.deepcopy(ctx)
        for op in ops:
            if op.enabled:
                new_ctx = self._apply_one(new_ctx, op)
        return new_ctx, diff

    def _apply_one(self, ctx: OpContext, op: Operation) -> OpContext:
        handler = OP_HANDLERS.get(op.op_type)
        if handler:
            return handler(ctx, op.params)
        return ctx

    def _snapshot_notes(self, ctx: OpContext) -> list[dict]:
        from midiweaver.normalize.timeline import collect_master_notes

        return collect_master_notes(ctx.timeline)

    def _compute_diff(self, before: list[dict], after: list[dict]) -> RevisionDiff:
        def key(n: dict) -> tuple:
            return (n["start_tick"], n["pitch"], n.get("track_id", ""))

        before_map = {key(n): n for n in before}
        after_map = {key(n): n for n in after}
        added = [after_map[k] for k in after_map if k not in before_map]
        removed = [before_map[k] for k in before_map if k not in after_map]
        moved = []
        for k in before_map:
            if k in after_map:
                b, a = before_map[k], after_map[k]
                if b.get("start_tick") != a.get("start_tick"):
                    moved.append({"before": b, "after": a})
        return RevisionDiff(added_notes=added, removed_notes=removed, moved_notes=moved)


def _trim_silence(ctx: OpContext, params: dict[str, Any]) -> OpContext:
    song_id = params.get("song_id")
    threshold = params.get("threshold", 0.05)
    new_ctx = copy.deepcopy(ctx)
    for seg in new_ctx.timeline.segments:
        if song_id and seg.id != song_id:
            continue
        if seg.analysis:
            from midiweaver.analysis.analyzer import _find_silence_trim

            start, end = _find_silence_trim(
                seg.analysis.tracks, seg.analysis.ppq, threshold
            )
            seg.analysis.trim_start_tick = start
            seg.analysis.trim_end_tick = end
            seg.trim_start_ticks = start
            seg.trim_end_ticks = end
    new_ctx.timeline = build_master_timeline(
        new_ctx.timeline.segments,
        new_ctx.timeline.master_ppq,
        new_ctx.timeline.transitions,
    )
    return new_ctx


def _tempo_ramp(ctx: OpContext, params: dict[str, Any]) -> OpContext:
    new_ctx = copy.deepcopy(ctx)
    new_ctx.timeline = apply_tempo_ramp(
        new_ctx.timeline,
        params["start_tick"],
        params["end_tick"],
        params["start_bpm"],
        params["end_bpm"],
        params.get("policy", "linear_ramp"),
    )
    return new_ctx


def _extend_drums(ctx: OpContext, params: dict[str, Any]) -> OpContext:
    new_ctx = copy.deepcopy(ctx)
    song_id = params.get("song_id")
    bars = int(params.get("bars", 2))
    mode = params.get("mode", "repeat_last_phrase")
    ppq = new_ctx.timeline.master_ppq
    extend_ticks = bars * ppq * 4

    for seg in new_ctx.timeline.segments:
        if song_id and seg.id != song_id:
            continue
        if not seg.analysis:
            continue
        for track in seg.analysis.tracks:
            if not track.is_drum:
                continue
            drum_notes = sorted(track.notes, key=lambda n: n.start_tick)
            if not drum_notes:
                continue
            last_bar_start = max(n.start_tick for n in drum_notes) - ppq * 4
            phrase = [n for n in drum_notes if n.start_tick >= last_bar_start]
            offset_base = seg.analysis.trim_end_tick or seg.master_end_tick
            for rep in range(bars):
                for n in phrase:
                    clone = ensure_note_id(
                        NoteEvent(
                            pitch=n.pitch,
                            start_tick=offset_base + rep * ppq * 4 + (n.start_tick - last_bar_start),
                            duration_ticks=n.duration_ticks,
                            velocity=n.velocity if mode != "repeat_with_fill" else min(127, n.velocity + 10),
                            channel=n.channel,
                        )
                    )
                    track.notes.append(clone)
    new_ctx.timeline = build_master_timeline(
        new_ctx.timeline.segments,
        new_ctx.timeline.master_ppq,
        new_ctx.timeline.transitions,
    )
    return new_ctx


def _match_track(track: TrackData, track_ref: str) -> bool:
    return track.track_id == track_ref or track.master_track_id == track_ref or track.name == track_ref


def _resolve_note_region(
    ctx: OpContext, params: dict[str, Any]
) -> tuple[int, int, list[str]] | None:
    """Resolve master-tick source region from explicit ticks or song_id+track_id."""
    if "source_start_tick" in params and "source_end_tick" in params:
        track_ids = params.get("track_ids", [])
        if params.get("track_id"):
            track_ids = [params["track_id"], *track_ids]
        if params.get("master_track_id"):
            track_ids = [params["master_track_id"], *track_ids]
        return int(params["source_start_tick"]), int(params["source_end_tick"]), track_ids

    song_id = params.get("song_id")
    track_ref = params.get("track_id") or params.get("master_track_id")
    if not song_id or not track_ref:
        return None

    for seg in ctx.timeline.segments:
        if seg.id != song_id or not seg.analysis:
            continue
        for track in seg.analysis.tracks:
            if not _match_track(track, track_ref) or not track.notes:
                continue
            offset = seg.master_start_tick - seg.analysis.trim_start_tick
            notes = sorted(track.notes, key=lambda n: n.start_tick)
            first = notes[0]
            last = max(notes, key=lambda n: n.start_tick + n.duration_ticks)
            abs_start = first.start_tick + offset
            abs_end = last.start_tick + last.duration_ticks + offset
            return int(abs_start), int(abs_end), [track.track_id]
    return None


def _copy_notes(ctx: OpContext, params: dict[str, Any]) -> OpContext:
    new_ctx = copy.deepcopy(ctx)
    region = _resolve_note_region(new_ctx, params)
    if region is None:
        return new_ctx
    src_start, src_end, track_ids = region
    dest_tick = params.get("dest_tick", src_start + int(params.get("delay_ticks", new_ctx.timeline.master_ppq)))
    velocity_scale = float(params.get("velocity_scale", 1.0))

    for seg in new_ctx.timeline.segments:
        if not seg.analysis:
            continue
        offset = seg.master_start_tick - seg.analysis.trim_start_tick
        for track in seg.analysis.tracks:
            if track_ids and track.track_id not in track_ids and not any(
                _match_track(track, tid) for tid in track_ids
            ):
                continue
            for n in list(track.notes):
                abs_start = n.start_tick + offset
                if src_start <= abs_start < src_end:
                    delta = dest_tick - src_start
                    track.notes.append(
                        ensure_note_id(
                            NoteEvent(
                                pitch=n.pitch,
                                start_tick=max(0, n.start_tick + delta),
                                duration_ticks=n.duration_ticks,
                                velocity=max(1, min(127, int(n.velocity * velocity_scale))),
                                channel=n.channel,
                            )
                        )
                    )
    for seg in new_ctx.timeline.segments:
        if seg.analysis:
            sync_segment_trim_bounds(seg.analysis)
            seg.trim_start_ticks = seg.analysis.trim_start_tick
            seg.trim_end_ticks = seg.analysis.trim_end_tick
    return new_ctx


def _echo_notes(ctx: OpContext, params: dict[str, Any]) -> OpContext:
    region = _resolve_note_region(ctx, params)
    if region is None:
        return ctx

    src_start, src_end, _ = region
    ppq = ctx.timeline.master_ppq
    interval = int(params.get("interval_ticks", params.get("delay_ticks", ppq)))
    repeats = int(params.get("repeats", 1))
    if repeats <= 1 and "bars" in params:
        beats_per_bar = 4
        repeats = max(1, int(float(params["bars"]) * beats_per_bar))
    decay = float(params.get("velocity_decay", 1.0))

    new_ctx = copy.deepcopy(ctx)
    for i in range(repeats):
        echo_params = {
            **params,
            "source_start_tick": src_start,
            "source_end_tick": src_end,
            "dest_tick": src_start + interval * (i + 1),
            "velocity_scale": decay ** (i + 1) if decay < 1 else 1.0,
        }
        new_ctx = _copy_notes(new_ctx, echo_params)
    new_ctx.timeline = build_master_timeline(
        new_ctx.timeline.segments,
        new_ctx.timeline.master_ppq,
        new_ctx.timeline.transitions,
    )
    return new_ctx


def _shift_song(ctx: OpContext, params: dict[str, Any]) -> OpContext:
    new_ctx = copy.deepcopy(ctx)
    song_id = params["song_id"]
    ppq = new_ctx.timeline.master_ppq
    if "delta_ticks" in params:
        delta = int(params["delta_ticks"])
    else:
        delta = int(float(params.get("bars", 0)) * 4 * ppq)

    for seg in new_ctx.timeline.segments:
        if seg.id != song_id or not seg.analysis:
            continue
        for track in seg.analysis.tracks:
            for n in track.notes:
                n.start_tick = max(0, n.start_tick + delta)
        seg.analysis.trim_start_tick = max(0, seg.analysis.trim_start_tick + delta)
        if delta > 0 and seg.analysis.trim_end_tick is not None:
            seg.analysis.trim_end_tick = seg.analysis.trim_end_tick + delta
        sync_segment_trim_bounds(seg.analysis)
        seg.trim_start_ticks = seg.analysis.trim_start_tick
        seg.trim_end_ticks = seg.analysis.trim_end_tick
        if delta < 0:
            seg.master_start_offset_ticks += delta
    new_ctx.timeline = build_master_timeline(
        new_ctx.timeline.segments,
        new_ctx.timeline.master_ppq,
        new_ctx.timeline.transitions,
    )
    return new_ctx


def _find_note_index(track: TrackData, params: dict[str, Any]) -> int | None:
    if "note_id" in params and params["note_id"]:
        for i, n in enumerate(track.notes):
            if n.note_id == params["note_id"]:
                return i
    if "start_tick" in params and "pitch" in params:
        for i, n in enumerate(track.notes):
            if n.start_tick == params["start_tick"] and n.pitch == params["pitch"]:
                return i
    note_index = params.get("note_index")
    if note_index is not None and note_index < len(track.notes):
        return int(note_index)
    return None


def _manual_edit_note(ctx: OpContext, params: dict[str, Any]) -> OpContext:
    new_ctx = copy.deepcopy(ctx)
    action = params.get("action", "move")
    song_id = params["song_id"]
    track_id = params["track_id"]

    for seg in new_ctx.timeline.segments:
        if seg.id != song_id or not seg.analysis:
            continue
        for track in seg.analysis.tracks:
            if track.track_id != track_id:
                continue
            if action == "add":
                track.notes.append(
                    ensure_note_id(
                        NoteEvent(
                            pitch=params["pitch"],
                            start_tick=params["start_tick"],
                            duration_ticks=params.get("duration_ticks", 480),
                            velocity=params.get("velocity", 64),
                            channel=params.get("channel", 0),
                        )
                    )
                )
            else:
                idx = _find_note_index(track, params)
                if idx is None:
                    continue
                if action == "delete":
                    track.notes.pop(idx)
                elif action in ("move", "resize"):
                    note = track.notes[idx]
                    if "start_tick" in params:
                        note.start_tick = params["start_tick"]
                    if "duration_ticks" in params:
                        note.duration_ticks = params["duration_ticks"]
                    if "velocity" in params:
                        note.velocity = params["velocity"]
    new_ctx.timeline = build_master_timeline(
        new_ctx.timeline.segments,
        new_ctx.timeline.master_ppq,
        new_ctx.timeline.transitions,
    )
    return new_ctx


def _set_transition_markers(ctx: OpContext, params: dict[str, Any]) -> OpContext:
    new_ctx = copy.deepcopy(ctx)
    trans_id = params.get("transition_id")
    if not trans_id and "from_song_id" in params and "to_song_id" in params:
        match = next(
            (
                t
                for t in new_ctx.timeline.transitions
                if t.from_song_id == params["from_song_id"]
                and t.to_song_id == params["to_song_id"]
            ),
            None,
        )
        trans_id = match.id if match else None
    if not trans_id:
        return new_ctx
    for trans in new_ctx.timeline.transitions:
        if trans.id == trans_id:
            trans.mix_out_bars = params.get("mix_out_bars", trans.mix_out_bars)
            trans.mix_in_bars = params.get("mix_in_bars", trans.mix_in_bars)
            trans.duration_bars = params.get("duration_bars", trans.duration_bars)
    return new_ctx


def _mute_track(ctx: OpContext, params: dict[str, Any]) -> OpContext:
    new_ctx = copy.deepcopy(ctx)
    track_id = params["track_id"]
    mute = params.get("mute", True)
    for seg in new_ctx.timeline.segments:
        if seg.analysis:
            for track in seg.analysis.tracks:
                if track.track_id == track_id or track.master_track_id == track_id:
                    track.mute = mute
    return new_ctx


def _transpose_region(ctx: OpContext, params: dict[str, Any]) -> OpContext:
    new_ctx = copy.deepcopy(ctx)
    semitones = params.get("semitones", 0)
    start = params["start_tick"]
    end = params["end_tick"]
    for seg in new_ctx.timeline.segments:
        if not seg.analysis:
            continue
        offset = seg.master_start_tick - seg.analysis.trim_start_tick
        for track in seg.analysis.tracks:
            for n in track.notes:
                abs_start = n.start_tick + offset
                if start <= abs_start < end:
                    n.pitch = max(0, min(127, n.pitch + semitones))
    return new_ctx


def _quantize_region(ctx: OpContext, params: dict[str, Any]) -> OpContext:
    new_ctx = copy.deepcopy(ctx)
    grid = params.get("grid_ticks", 480)
    strength = params.get("strength", 1.0)
    start = params["start_tick"]
    end = params["end_tick"]
    ppq = new_ctx.timeline.master_ppq

    for seg in new_ctx.timeline.segments:
        if not seg.analysis:
            continue
        offset = seg.master_start_tick - seg.analysis.trim_start_tick
        for track in seg.analysis.tracks:
            if not track.quantize_enabled and not params.get("force", False):
                continue
            eff = strength * (track.quantize_strength or 1.0)
            for n in track.notes:
                abs_start = n.start_tick + offset
                if start <= abs_start < end:
                    grid_pos = round(n.start_tick / grid) * grid
                    n.start_tick = int(n.start_tick + (grid_pos - n.start_tick) * eff)
    return new_ctx


def _insert_master_gap(ctx: OpContext, params: dict[str, Any]) -> OpContext:
    new_ctx = copy.deepcopy(ctx)
    after_song_id = params["after_song_id"]
    ppq = new_ctx.timeline.master_ppq
    if "ticks" in params:
        gap = int(params["ticks"])
    else:
        gap = int(float(params["bars"]) * 4 * ppq)

    seg_index = next(
        (i for i, s in enumerate(new_ctx.timeline.segments) if s.id == after_song_id),
        None,
    )
    if seg_index is None or seg_index >= len(new_ctx.timeline.segments) - 1:
        return new_ctx

    next_seg = new_ctx.timeline.segments[seg_index + 1]
    next_seg.master_start_offset_ticks += gap
    new_ctx.timeline = build_master_timeline(
        new_ctx.timeline.segments,
        new_ctx.timeline.master_ppq,
        new_ctx.timeline.transitions,
    )
    return new_ctx


def _loop_region(ctx: OpContext, params: dict[str, Any]) -> OpContext:
    new_ctx = copy.deepcopy(ctx)
    song_id = params["song_id"]
    ppq = new_ctx.timeline.master_ppq

    for seg in new_ctx.timeline.segments:
        if seg.id != song_id or not seg.analysis:
            continue
        a = seg.analysis
        beats = a.time_sig[0]
        bar_ticks = ppq * beats
        src_start = a.trim_start_tick + int(float(params["source_start_bar"]) * bar_ticks)
        src_end = a.trim_start_tick + int(float(params["source_end_bar"]) * bar_ticks)
        region_len = max(bar_ticks, src_end - src_start)
        track_filter = set(params.get("track_ids", []))

        if "repeat_count" in params:
            repeats = int(params["repeat_count"])
        else:
            target = float(params["target_total_bars"])
            source_bars = max(1, (src_end - src_start) / bar_ticks)
            repeats = max(0, int(round(target / source_bars)) - 1)

        dest_base = a.trim_end_tick or src_end
        for rep in range(repeats):
            dest_offset = dest_base + rep * region_len - src_start
            for track in a.tracks:
                if track_filter and track.track_id not in track_filter:
                    continue
                for n in list(track.notes):
                    if src_start <= n.start_tick < src_end:
                        track.notes.append(
                            ensure_note_id(
                                NoteEvent(
                                    pitch=n.pitch,
                                    start_tick=n.start_tick + dest_offset,
                                    duration_ticks=n.duration_ticks,
                                    velocity=n.velocity,
                                    channel=n.channel,
                                )
                            )
                        )
        sync_segment_trim_bounds(a)
        seg.trim_start_ticks = a.trim_start_tick
        seg.trim_end_ticks = a.trim_end_tick

    new_ctx.timeline = build_master_timeline(
        new_ctx.timeline.segments,
        new_ctx.timeline.master_ppq,
        new_ctx.timeline.transitions,
    )
    return new_ctx


def _delete_notes_in_region(ctx: OpContext, params: dict[str, Any]) -> OpContext:
    new_ctx = copy.deepcopy(ctx)
    start = int(params["start_tick"])
    end = int(params["end_tick"])
    song_id = params.get("song_id")
    track_id = params.get("track_id")
    pitch_min = params.get("pitch_min")
    pitch_max = params.get("pitch_max")
    drum_only = params.get("drum_only", False)

    for seg in new_ctx.timeline.segments:
        if song_id and seg.id != song_id:
            continue
        if not seg.analysis:
            continue
        offset = seg.master_start_tick - seg.analysis.trim_start_tick
        for track in seg.analysis.tracks:
            if track_id and track.track_id != track_id and track.master_track_id != track_id:
                continue
            if drum_only and not track.is_drum:
                continue
            kept: list[NoteEvent] = []
            for n in track.notes:
                abs_start = n.start_tick + offset
                if start <= abs_start < end:
                    if pitch_min is not None and n.pitch < pitch_min:
                        kept.append(n)
                        continue
                    if pitch_max is not None and n.pitch > pitch_max:
                        kept.append(n)
                        continue
                    continue
                kept.append(n)
            track.notes = kept
        sync_segment_trim_bounds(seg.analysis)
        seg.trim_start_ticks = seg.analysis.trim_start_tick
        seg.trim_end_ticks = seg.analysis.trim_end_tick

    new_ctx.timeline = build_master_timeline(
        new_ctx.timeline.segments,
        new_ctx.timeline.master_ppq,
        new_ctx.timeline.transitions,
    )
    return new_ctx


def _noop(ctx: OpContext, params: dict[str, Any]) -> OpContext:
    return ctx


ALLOWED_OPS = {
    "trim_silence",
    "set_transition_markers",
    "tempo_ramp",
    "extend_drums",
    "copy_notes",
    "echo_notes",
    "shift_song",
    "insert_master_gap",
    "loop_region",
    "delete_notes_in_region",
    "insert_song",
    "transpose_region",
    "quantize_region",
    "set_velocity_curve",
    "mute_track",
    "manual_edit_note",
}

OP_HANDLERS = {
    "trim_silence": _trim_silence,
    "tempo_ramp": _tempo_ramp,
    "extend_drums": _extend_drums,
    "copy_notes": _copy_notes,
    "echo_notes": _echo_notes,
    "shift_song": _shift_song,
    "insert_master_gap": _insert_master_gap,
    "loop_region": _loop_region,
    "delete_notes_in_region": _delete_notes_in_region,
    "manual_edit_note": _manual_edit_note,
    "set_transition_markers": _set_transition_markers,
    "mute_track": _mute_track,
    "transpose_region": _transpose_region,
    "quantize_region": _quantize_region,
    "insert_song": _noop,
    "set_velocity_curve": _noop,
}


def create_manual_edit_op(action: str, **params: Any) -> Operation:
    return Operation(
        op_type="manual_edit_note",
        params={"action": action, **params},
        description=f"Manual {action}",
    )
