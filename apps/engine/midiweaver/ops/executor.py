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
from midiweaver.normalize.timeline import apply_tempo_ramp, build_master_timeline


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
        if op.op_type == "tempo_ramp":
            p = op.params
            for key in ("start_tick", "end_tick", "start_bpm", "end_bpm"):
                if key not in p:
                    errors.append(f"tempo_ramp missing {key}")
            if p.get("start_bpm", 0) < 20 or p.get("end_bpm", 0) > 300:
                errors.append("BPM out of bounds (20-300)")
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
                    clone = NoteEvent(
                        pitch=n.pitch,
                        start_tick=offset_base + rep * ppq * 4 + (n.start_tick - last_bar_start),
                        duration_ticks=n.duration_ticks,
                        velocity=n.velocity if mode != "repeat_with_fill" else min(127, n.velocity + 10),
                        channel=n.channel,
                    )
                    track.notes.append(clone)
    new_ctx.timeline = build_master_timeline(
        new_ctx.timeline.segments,
        new_ctx.timeline.master_ppq,
        new_ctx.timeline.transitions,
    )
    return new_ctx


def _copy_notes(ctx: OpContext, params: dict[str, Any]) -> OpContext:
    new_ctx = copy.deepcopy(ctx)
    src_start = params["source_start_tick"]
    src_end = params["source_end_tick"]
    dest_tick = params["dest_tick"]
    track_ids = params.get("track_ids", [])

    for seg in new_ctx.timeline.segments:
        if not seg.analysis:
            continue
        offset = seg.master_start_tick - seg.analysis.trim_start_tick
        for track in seg.analysis.tracks:
            if track_ids and track.track_id not in track_ids:
                continue
            for n in list(track.notes):
                abs_start = n.start_tick + offset
                if src_start <= abs_start < src_end:
                    delta = dest_tick - src_start
                    track.notes.append(
                        NoteEvent(
                            pitch=n.pitch,
                            start_tick=n.start_tick + delta,
                            duration_ticks=n.duration_ticks,
                            velocity=n.velocity,
                            channel=n.channel,
                        )
                    )
    return new_ctx


def _echo_notes(ctx: OpContext, params: dict[str, Any]) -> OpContext:
    params = {**params, "dest_tick": params["source_start_tick"] + params.get("delay_ticks", 480)}
    return _copy_notes(ctx, params)


def _manual_edit_note(ctx: OpContext, params: dict[str, Any]) -> OpContext:
    new_ctx = copy.deepcopy(ctx)
    action = params.get("action", "move")
    song_id = params["song_id"]
    track_id = params["track_id"]
    note_index = params.get("note_index", 0)

    for seg in new_ctx.timeline.segments:
        if seg.id != song_id or not seg.analysis:
            continue
        for track in seg.analysis.tracks:
            if track.track_id != track_id:
                continue
            if action == "add":
                track.notes.append(
                    NoteEvent(
                        pitch=params["pitch"],
                        start_tick=params["start_tick"],
                        duration_ticks=params.get("duration_ticks", 480),
                        velocity=params.get("velocity", 64),
                        channel=params.get("channel", 0),
                    )
                )
            elif action == "delete" and note_index < len(track.notes):
                track.notes.pop(note_index)
            elif action in ("move", "resize") and note_index < len(track.notes):
                note = track.notes[note_index]
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
    trans_id = params["transition_id"]
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


def _noop(ctx: OpContext, params: dict[str, Any]) -> OpContext:
    return ctx


ALLOWED_OPS = {
    "trim_silence",
    "set_transition_markers",
    "tempo_ramp",
    "extend_drums",
    "copy_notes",
    "echo_notes",
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
