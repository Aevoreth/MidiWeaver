from __future__ import annotations

from typing import Any

from midiweaver.models import MasterTimeline, Operation, SongSegment
from midiweaver.normalize.timeline import bars_to_ticks, ticks_to_bars


def _timeline_bpm(timeline: MasterTimeline) -> tuple[float, int]:
    bpm = 120.0
    beats = 4
    if timeline.segments and timeline.segments[0].analysis:
        bpm = timeline.segments[0].analysis.estimated_bpm
        beats = timeline.segments[0].analysis.time_sig[0]
    return bpm, beats


def _bar_to_tick(bar: float, timeline: MasterTimeline) -> int:
    bpm, beats = _timeline_bpm(timeline)
    return bars_to_ticks(bar, timeline.master_ppq, bpm, beats)


def _segment(timeline: MasterTimeline, song_id: str | None) -> SongSegment | None:
    if not song_id:
        return None
    return next((s for s in timeline.segments if s.id == song_id), None)


def _transition(timeline: MasterTimeline, selection: dict[str, Any]):
    transition_id = selection.get("transition_id")
    if not transition_id:
        return None
    return next((t for t in timeline.transitions if t.id == transition_id), None)


def _infer_song_id(
    timeline: MasterTimeline,
    selection: dict[str, Any],
    params: dict[str, Any],
    *,
    role: str = "from",
) -> str | None:
    if params.get("song_id"):
        return str(params["song_id"])
    if params.get("after_song_id") and role == "from":
        return str(params["after_song_id"])
    trans = _transition(timeline, selection)
    if trans:
        return trans.from_song_id if role == "from" else trans.to_song_id
    if timeline.segments:
        if role == "to" and len(timeline.segments) > 1:
            return timeline.segments[1].id
        return timeline.segments[0].id
    return None


def _master_bar_to_local_bar(seg: SongSegment, master_bar: float, timeline: MasterTimeline) -> float:
    bpm, beats = _timeline_bpm(timeline)
    ppq = timeline.master_ppq
    master_start = ticks_to_bars(seg.master_start_tick, ppq, bpm, beats)
    return master_bar - master_start


def _looks_like_master_bar(seg: SongSegment, bar: float, timeline: MasterTimeline) -> bool:
    if seg.analysis is None:
        return False
    bpm, beats = _timeline_bpm(timeline)
    ppq = timeline.master_ppq
    master_start = ticks_to_bars(seg.master_start_tick, ppq, bpm, beats)
    master_end = ticks_to_bars(seg.master_end_tick, ppq, bpm, beats)
    local_span = seg.analysis.bar_count
    local_equiv = bar - master_start
    if bar < master_start - 1:
        return False
    if bar > master_end + 1:
        return False
    if local_equiv < 0:
        return True
    if local_equiv > local_span + 2:
        return True
    return False


def _normalize_loop_bars(
    seg: SongSegment,
    params: dict[str, Any],
    timeline: MasterTimeline,
) -> None:
    bar_space = params.get("bar_space", "auto")
    for master_key, local_key in (
        ("master_source_start_bar", "source_start_bar"),
        ("master_source_end_bar", "source_end_bar"),
    ):
        if master_key in params and local_key not in params:
            params[local_key] = _master_bar_to_local_bar(seg, float(params[master_key]), timeline)

    for key in ("source_start_bar", "source_end_bar"):
        if key not in params:
            continue
        bar = float(params[key])
        if bar_space == "master" or (bar_space == "auto" and _looks_like_master_bar(seg, bar, timeline)):
            params[key] = _master_bar_to_local_bar(seg, bar, timeline)


def _apply_last_bars(seg: SongSegment, params: dict[str, Any], timeline: MasterTimeline) -> None:
    if not seg.analysis:
        return
    a = seg.analysis
    ppq = timeline.master_ppq
    beats = a.time_sig[0]
    bar_ticks = ppq * beats
    last_bars = int(params.get("last_bars", 4))
    end_local = a.trim_end_tick or (seg.master_end_tick - (seg.master_start_tick - a.trim_start_tick))
    last_start = max(a.trim_start_tick, end_local - last_bars * bar_ticks)
    params.setdefault("source_start_bar", (last_start - a.trim_start_tick) / bar_ticks)
    params.setdefault("source_end_bar", (end_local - a.trim_start_tick) / bar_ticks)


def resolve_op_params(
    op: Operation,
    timeline: MasterTimeline,
    selection: dict[str, Any] | None = None,
) -> Operation:
    """Fill missing op params from bars, selection, and timeline context."""
    p = dict(op.params)
    selection = selection or {}
    ppq = timeline.master_ppq
    bpm, beats = _timeline_bpm(timeline)

    if op.op_type == "copy_notes":
        bar_range = selection.get("master_bar_range")
        if "source_bar_range" in p and "source_start_bar" not in p:
            start, end = p["source_bar_range"]
            p["source_start_bar"] = float(start)
            p["source_end_bar"] = float(end)
        if "master_source_start_bar" in p and "source_start_bar" not in p:
            p["source_start_bar"] = float(p["master_source_start_bar"])
        if "master_source_end_bar" in p and "source_end_bar" not in p:
            p["source_end_bar"] = float(p["master_source_end_bar"])
        if "source_start_bar" in p and "source_start_tick" not in p:
            p["source_start_tick"] = _bar_to_tick(float(p["source_start_bar"]), timeline)
        if "source_end_bar" in p and "source_end_tick" not in p:
            p["source_end_tick"] = _bar_to_tick(float(p["source_end_bar"]), timeline)
        if bar_range and "source_start_tick" not in p and "source_end_tick" not in p:
            has_track = ("track_id" in p or "master_track_id" in p) and "song_id" in p
            if not has_track:
                p.setdefault("source_start_tick", _bar_to_tick(float(bar_range[0]), timeline))
                p.setdefault("source_end_tick", _bar_to_tick(float(bar_range[1]), timeline))
        src_end = p.get("source_end_tick")
        if "dest_tick" not in p:
            if "dest_bar" in p:
                p["dest_tick"] = _bar_to_tick(float(p["dest_bar"]), timeline)
            elif "dest_offset_bars" in p and src_end is not None:
                p["dest_tick"] = int(src_end) + _bar_to_tick(float(p["dest_offset_bars"]), timeline)
            elif "delay_bars" in p and src_end is not None:
                p["dest_tick"] = int(src_end) + _bar_to_tick(float(p["delay_bars"]), timeline)
            elif "delay_ticks" in p and src_end is not None:
                p["dest_tick"] = int(src_end) + int(p["delay_ticks"])
            elif src_end is not None and "bars" in p:
                p["dest_tick"] = int(src_end) + _bar_to_tick(float(p["bars"]), timeline)

    elif op.op_type == "echo_notes":
        if "source_start_bar" in p and "source_start_tick" not in p:
            p["source_start_tick"] = _bar_to_tick(float(p["source_start_bar"]), timeline)
        if "source_end_bar" in p and "source_end_tick" not in p:
            p["source_end_tick"] = _bar_to_tick(float(p["source_end_bar"]), timeline)
        bar_range = selection.get("master_bar_range")
        if bar_range and "source_start_tick" not in p and "source_end_tick" not in p:
            has_track = ("track_id" in p or "master_track_id" in p) and "song_id" in p
            if has_track:
                p.setdefault("source_start_tick", _bar_to_tick(float(bar_range[0]), timeline))
                p.setdefault("source_end_tick", _bar_to_tick(float(bar_range[1]), timeline))
        p.setdefault("interval_ticks", ppq)

    elif op.op_type == "delete_notes_in_region":
        if "start_bar" in p and "start_tick" not in p:
            p["start_tick"] = _bar_to_tick(float(p["start_bar"]), timeline)
        if "end_bar" in p and "end_tick" not in p:
            p["end_tick"] = _bar_to_tick(float(p["end_bar"]), timeline)

    elif op.op_type == "shift_song":
        p.setdefault("song_id", _infer_song_id(timeline, selection, p, role="to"))
        for alias in ("delta_bars", "shift_bars"):
            if alias in p and "bars" not in p:
                p["bars"] = p[alias]
        if "delta_ticks" not in p and "bars" in p:
            bars = float(p["bars"])
            if p.get("direction") in ("back", "earlier", "left"):
                bars = -abs(bars)
            elif p.get("direction") in ("forward", "later", "right"):
                bars = abs(bars)
            p["delta_ticks"] = int(bars * beats * ppq)

    elif op.op_type == "insert_master_gap":
        p.setdefault("after_song_id", _infer_song_id(timeline, selection, p, role="from"))
        for alias in ("gap_bars", "duration_bars"):
            if alias in p and "bars" not in p:
                p["bars"] = p[alias]

    elif op.op_type == "loop_region":
        p.setdefault("song_id", _infer_song_id(timeline, selection, p, role="from"))
        if "source_bar_range" in p:
            start, end = p["source_bar_range"]
            p.setdefault("source_start_bar", float(start))
            p.setdefault("source_end_bar", float(end))
        for src, dst in (("start_bar", "source_start_bar"), ("end_bar", "source_end_bar")):
            if src in p and dst not in p:
                p[dst] = p[src]
        if p.get("use_last_bars"):
            seg = _segment(timeline, p.get("song_id"))
            if seg:
                _apply_last_bars(seg, p, timeline)
        seg = _segment(timeline, p.get("song_id"))
        if seg:
            _normalize_loop_bars(seg, p, timeline)
        for alias in ("repeats", "repeat"):
            if alias in p and "repeat_count" not in p:
                p["repeat_count"] = p[alias]

    elif op.op_type == "tempo_ramp":
        bar_range = selection.get("master_bar_range")
        if "start_bar" in p and "start_tick" not in p:
            p["start_tick"] = _bar_to_tick(float(p["start_bar"]), timeline)
        if "end_bar" in p and "end_tick" not in p:
            p["end_tick"] = _bar_to_tick(float(p["end_bar"]), timeline)
        if bar_range and "start_tick" not in p and "end_tick" not in p:
            p.setdefault("start_tick", _bar_to_tick(float(bar_range[0]), timeline))
            p.setdefault("end_tick", _bar_to_tick(float(bar_range[1]), timeline))
        if "duration_bars" in p and "start_tick" in p and "end_tick" not in p:
            span = _bar_to_tick(float(p["duration_bars"]), timeline)
            p["end_tick"] = int(p["start_tick"]) + span
        trans = _transition(timeline, selection)
        if trans and "start_bpm" not in p:
            from_seg = _segment(timeline, trans.from_song_id)
            to_seg = _segment(timeline, trans.to_song_id)
            if from_seg and from_seg.analysis:
                p.setdefault("start_bpm", from_seg.analysis.estimated_bpm)
            if to_seg and to_seg.analysis:
                p.setdefault("end_bpm", to_seg.analysis.estimated_bpm)
        p.setdefault("policy", "linear_ramp")

    return op.model_copy(update={"params": p})
