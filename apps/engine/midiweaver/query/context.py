from __future__ import annotations

from typing import Any

from midiweaver.models import MasterTimeline, TrackMappingEntry
from midiweaver.normalize.timeline import (
    bars_to_ticks,
    collect_master_notes,
    ticks_to_bars,
)

MAX_NOTES_PER_QUERY = 500


def _default_bpm(timeline: MasterTimeline) -> float:
    if timeline.segments and timeline.segments[0].analysis:
        return timeline.segments[0].analysis.estimated_bpm
    return 120.0


def _beats_per_bar(timeline: MasterTimeline) -> int:
    if timeline.segments and timeline.segments[0].analysis:
        return timeline.segments[0].analysis.time_sig[0]
    return 4


def get_timeline_summary(
    timeline: MasterTimeline,
    track_mapping: list[TrackMappingEntry] | list[Any] | None = None,
) -> dict[str, Any]:
    """Compact project overview for AI inspect tools."""
    bpm = _default_bpm(timeline)
    beats = _beats_per_bar(timeline)
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
                "estimated_bpm": a.estimated_bpm,
                "time_sig": list(a.time_sig),
                "key": a.key,
                "bar_count": a.bar_count,
                "master_start_tick": seg.master_start_tick,
                "master_end_tick": seg.master_end_tick,
                "master_start_bar": ticks_to_bars(seg.master_start_tick, timeline.master_ppq, bpm, beats),
                "master_end_bar": ticks_to_bars(seg.master_end_tick, timeline.master_ppq, bpm, beats),
                "master_start_offset_ticks": seg.master_start_offset_ticks,
                "loop_boundaries": a.loop_boundaries,
                "track_summaries": [ts.model_dump() for ts in a.track_summaries],
            }
        )

    mapping = []
    for entry in track_mapping or []:
        if hasattr(entry, "model_dump"):
            mapping.append(entry.model_dump())
        else:
            mapping.append(entry)

    transitions = [
        {
            "id": t.id,
            "from_song_id": t.from_song_id,
            "to_song_id": t.to_song_id,
            "duration_bars": t.duration_bars,
            "mix_out_bars": t.mix_out_bars,
            "mix_in_bars": t.mix_in_bars,
            "master_start_bar": t.master_start_bar,
            "master_end_bar": t.master_end_bar,
        }
        for t in timeline.transitions
    ]

    return {
        "master_ppq": timeline.master_ppq,
        "total_ticks": timeline.total_ticks,
        "total_bars": timeline.total_bars,
        "songs": songs,
        "transitions": transitions,
        "track_mapping": mapping,
        "tempo_events": [e.model_dump() for e in timeline.tempo_events],
    }


def get_transition_context(timeline: MasterTimeline, transition_id: str) -> dict[str, Any]:
    trans = next((t for t in timeline.transitions if t.id == transition_id), None)
    if not trans:
        return {"error": f"Transition not found: {transition_id}"}

    bpm = _default_bpm(timeline)
    beats = _beats_per_bar(timeline)
    ppq = timeline.master_ppq
    from_seg = next((s for s in timeline.segments if s.id == trans.from_song_id), None)
    to_seg = next((s for s in timeline.segments if s.id == trans.to_song_id), None)
    if not from_seg or not to_seg:
        return {"error": "Transition songs not found on timeline"}

    mix_out_start = from_seg.master_end_tick - int(trans.mix_out_bars * ppq * beats)
    mix_in_end = to_seg.master_start_tick + int(trans.mix_in_bars * ppq * beats)
    gap_ticks = max(0, to_seg.master_start_tick - from_seg.master_end_tick)

    return {
        "transition_id": trans.id,
        "from_song_id": trans.from_song_id,
        "to_song_id": trans.to_song_id,
        "duration_bars": trans.duration_bars,
        "mix_out_bars": trans.mix_out_bars,
        "mix_in_bars": trans.mix_in_bars,
        "master_start_bar": trans.master_start_bar,
        "master_end_bar": trans.master_end_bar,
        "mix_out_start_tick": mix_out_start,
        "mix_in_end_tick": mix_in_end,
        "mix_out_start_bar": ticks_to_bars(mix_out_start, ppq, bpm, beats),
        "mix_in_end_bar": ticks_to_bars(mix_in_end, ppq, bpm, beats),
        "from_song_end_tick": from_seg.master_end_tick,
        "to_song_start_tick": to_seg.master_start_tick,
        "gap_ticks": gap_ticks,
        "gap_bars": ticks_to_bars(gap_ticks, ppq, bpm, beats),
        "to_song_offset_ticks": to_seg.master_start_offset_ticks,
    }


def query_notes(
    timeline: MasterTimeline,
    *,
    start_tick: int | None = None,
    end_tick: int | None = None,
    start_bar: float | None = None,
    end_bar: float | None = None,
    song_id: str | None = None,
    track_id: str | None = None,
    master_track_id: str | None = None,
    limit: int = MAX_NOTES_PER_QUERY,
    offset: int = 0,
) -> dict[str, Any]:
    bpm = _default_bpm(timeline)
    beats = _beats_per_bar(timeline)
    ppq = timeline.master_ppq

    if start_bar is not None:
        start_tick = bars_to_ticks(start_bar, ppq, bpm, beats)
    if end_bar is not None:
        end_tick = bars_to_ticks(end_bar, ppq, bpm, beats)
    start_tick = start_tick or 0
    end_tick = end_tick or timeline.total_ticks or ppq * beats * 4

    notes = collect_master_notes(timeline)
    filtered = [
        n
        for n in notes
        if start_tick <= n["start_tick"] < end_tick
        and (not song_id or n.get("song_id") == song_id)
        and (not track_id or n.get("track_id") == track_id)
        and (not master_track_id or n.get("master_track_id") == master_track_id)
    ]

    total = len(filtered)
    page = filtered[offset : offset + min(limit, MAX_NOTES_PER_QUERY)]
    return {
        "start_tick": start_tick,
        "end_tick": end_tick,
        "start_bar": ticks_to_bars(start_tick, ppq, bpm, beats),
        "end_bar": ticks_to_bars(end_tick, ppq, bpm, beats),
        "total": total,
        "offset": offset,
        "limit": limit,
        "truncated": total > offset + len(page),
        "notes": page,
    }


def analyze_region(
    timeline: MasterTimeline,
    bar_range: list[float],
) -> dict[str, Any]:
    bpm = _default_bpm(timeline)
    beats = _beats_per_bar(timeline)
    ppq = timeline.master_ppq
    start_tick = bars_to_ticks(bar_range[0], ppq, bpm, beats)
    end_tick = bars_to_ticks(bar_range[1], ppq, bpm, beats)
    bar_ticks = ppq * beats

    notes = collect_master_notes(timeline)
    in_region = [n for n in notes if start_tick <= n["start_tick"] < end_tick]

    density: list[dict[str, Any]] = []
    bar_start = int(start_tick // bar_ticks) * bar_ticks
    while bar_start < end_tick:
        bar_end = bar_start + bar_ticks
        bar_notes = [n for n in in_region if bar_start <= n["start_tick"] < bar_end]
        drum_notes = [n for n in bar_notes if n.get("is_drum")]
        density.append(
            {
                "bar": ticks_to_bars(bar_start, ppq, bpm, beats),
                "note_count": len(bar_notes),
                "drum_count": len(drum_notes),
                "unique_pitches": sorted({n["pitch"] for n in bar_notes}),
            }
        )
        bar_start = bar_end

    pitch_classes: dict[int, int] = {}
    for n in in_region:
        pitch_classes[n["pitch"]] = pitch_classes.get(n["pitch"], 0) + 1

    return {
        "bar_range": bar_range,
        "start_tick": start_tick,
        "end_tick": end_tick,
        "total_notes": len(in_region),
        "density_per_bar": density,
        "pitch_histogram": pitch_classes,
        "tracks": sorted({n.get("track_name", n.get("track_id", "")) for n in in_region}),
    }


def get_loop_candidates(timeline: MasterTimeline, song_id: str) -> dict[str, Any]:
    seg = next((s for s in timeline.segments if s.id == song_id), None)
    if not seg or not seg.analysis:
        return {"error": f"Song not found: {song_id}"}

    a = seg.analysis
    bpm = a.estimated_bpm
    beats = a.time_sig[0]
    ppq = timeline.master_ppq
    bar_ticks = ppq * beats
    offset = seg.master_start_tick - a.trim_start_tick

    last_bars = 4
    end_local = a.trim_end_tick or seg.master_end_tick - offset
    last_start = max(a.trim_start_tick, end_local - last_bars * bar_ticks)
    last_notes = [
        n
        for t in a.tracks
        for n in t.notes
        if last_start <= n.start_tick < end_local
    ]

    return {
        "song_id": song_id,
        "loop_boundaries": [
            {
                "local_tick": tick,
                "master_tick": tick + offset,
                "bar": ticks_to_bars(tick + offset, ppq, bpm, beats),
            }
            for tick in a.loop_boundaries
        ],
        "last_bars": last_bars,
        "last_bar_region": {
            "local_start_tick": last_start,
            "local_end_tick": end_local,
            "master_start_tick": last_start + offset,
            "master_end_tick": end_local + offset,
            "note_count": len(last_notes),
        },
    }


def measure_region(
    timeline: MasterTimeline,
    *,
    start_bar: float | None = None,
    end_bar: float | None = None,
    start_tick: int | None = None,
    end_tick: int | None = None,
    song_id: str | None = None,
) -> dict[str, Any]:
    """Verify helper: counts and span metrics after edits."""
    result = query_notes(
        timeline,
        start_bar=start_bar,
        end_bar=end_bar,
        start_tick=start_tick,
        end_tick=end_tick,
        song_id=song_id,
        limit=MAX_NOTES_PER_QUERY,
    )
    bpm = _default_bpm(timeline)
    beats = _beats_per_bar(timeline)
    span_bars = result["end_bar"] - result["start_bar"]

    gap_bars: float | None = None
    if len(timeline.segments) >= 2:
        s0 = timeline.segments[0]
        s1 = timeline.segments[1]
        gap_ticks = max(0, s1.master_start_tick - s0.master_end_tick)
        gap_bars = ticks_to_bars(gap_ticks, timeline.master_ppq, bpm, beats)

    return {
        "note_count": result["total"],
        "span_bars": span_bars,
        "start_bar": result["start_bar"],
        "end_bar": result["end_bar"],
        "gap_between_first_two_songs_bars": gap_bars,
        "total_project_bars": timeline.total_bars,
    }
