from __future__ import annotations

import copy
import uuid

from midiweaver.models import (
    AnalysisSnapshot,
    MasterTimeline,
    NoteEvent,
    SongSegment,
    TempoEvent,
    TrackData,
    TransitionConfig,
)


def resample_tick(tick: int, from_ppq: int, to_ppq: int) -> int:
    if from_ppq == to_ppq:
        return tick
    return int(round(tick * to_ppq / from_ppq))


def normalize_analysis(analysis: AnalysisSnapshot, master_ppq: int) -> AnalysisSnapshot:
    """Resample all tick values to master PPQ."""
    if analysis.ppq == master_ppq:
        return analysis

    ratio_from = analysis.ppq
    data = analysis.model_copy(deep=True)
    data.ppq = master_ppq

    def rt(t: int) -> int:
        return resample_tick(t, ratio_from, master_ppq)

    data.trim_start_tick = rt(data.trim_start_tick)
    if data.trim_end_tick is not None:
        data.trim_end_tick = rt(data.trim_end_tick)
    data.loop_boundaries = [rt(b) for b in data.loop_boundaries]
    data.tempo_events = [
        TempoEvent(tick=rt(e.tick), bpm=e.bpm) for e in data.tempo_events
    ]

    new_tracks: list[TrackData] = []
    for track in data.tracks:
        notes = [
            NoteEvent(
                pitch=n.pitch,
                start_tick=rt(n.start_tick),
                duration_ticks=max(1, rt(n.start_tick + n.duration_ticks) - rt(n.start_tick)),
                velocity=n.velocity,
                channel=n.channel,
            )
            for n in track.notes
        ]
        new_tracks.append(track.model_copy(update={"notes": notes}))
    data.tracks = new_tracks
    return data


def segment_duration_ticks(analysis: AnalysisSnapshot) -> int:
    start = analysis.trim_start_tick
    end = analysis.trim_end_tick
    if end is None:
        if analysis.tracks:
            end = max(n.start_tick + n.duration_ticks for t in analysis.tracks for n in t.notes)
        else:
            end = int(analysis.bar_count * analysis.ppq * analysis.time_sig[0])
    return max(0, end - start)


def build_master_timeline(
    segments: list[SongSegment],
    master_ppq: int = 480,
    transitions: list[TransitionConfig] | None = None,
) -> MasterTimeline:
    """Place song segments on a shared master clock."""
    timeline = MasterTimeline(master_ppq=master_ppq, transitions=transitions or [])
    cursor = 0
    tempo_events: list[TempoEvent] = []

    for seg in segments:
        if seg.analysis is None:
            continue
        norm = normalize_analysis(seg.analysis, master_ppq)
        duration = segment_duration_ticks(norm)
        seg_copy = seg.model_copy(
            update={
                "analysis": norm,
                "master_start_tick": cursor,
                "master_end_tick": cursor + duration,
            }
        )
        timeline.segments.append(seg_copy)

        for te in norm.tempo_events:
            tempo_events.append(
                TempoEvent(tick=cursor + te.tick - norm.trim_start_tick, bpm=te.bpm)
            )
        cursor += duration

    timeline.tempo_events = sorted(tempo_events, key=lambda e: e.tick)
    timeline.total_ticks = cursor
    beats_per_bar = 4
    if segments and segments[0].analysis:
        beats_per_bar = segments[0].analysis.time_sig[0]
    bpm = 120.0
    if segments and segments[0].analysis:
        bpm = segments[0].analysis.estimated_bpm
    timeline.total_bars = (cursor / master_ppq) * (bpm / 60.0) / beats_per_bar

    # Wire transition bar ranges
    for i, trans in enumerate(timeline.transitions):
        if i < len(timeline.segments) - 1:
            from_seg = timeline.segments[i]
            to_seg = timeline.segments[i + 1]
            trans.master_start_bar = ticks_to_bars(
                from_seg.master_end_tick - int(trans.mix_out_bars * master_ppq * 4),
                master_ppq,
                bpm,
                beats_per_bar,
            )
            trans.master_end_bar = ticks_to_bars(
                to_seg.master_start_tick + int(trans.mix_in_bars * master_ppq * 4),
                master_ppq,
                bpm,
                beats_per_bar,
            )

    return timeline


def ticks_to_bars(tick: int, ppq: int, bpm: float, beats_per_bar: int = 4) -> float:
    beats = (tick / ppq) * (bpm / 60.0)
    return beats / beats_per_bar


def bars_to_ticks(bar: float, ppq: int, bpm: float, beats_per_bar: int = 4) -> int:
    beats = bar * beats_per_bar
    seconds = beats * 60.0 / bpm
    return int(seconds * ppq * bpm / 60.0)


def collect_master_notes(timeline: MasterTimeline) -> list[dict]:
    """Flatten all notes onto master timeline with offsets."""
    notes: list[dict] = []
    for seg in timeline.segments:
        if not seg.analysis:
            continue
        offset = seg.master_start_tick - seg.analysis.trim_start_tick
        for track in seg.analysis.tracks:
            for n in track.notes:
                if seg.analysis.trim_end_tick and n.start_tick >= seg.analysis.trim_end_tick:
                    continue
                if n.start_tick < seg.analysis.trim_start_tick:
                    continue
                notes.append(
                    {
                        "song_id": seg.id,
                        "track_id": track.track_id,
                        "master_track_id": track.master_track_id or track.track_id,
                        "track_name": track.name,
                        "pitch": n.pitch,
                        "start_tick": n.start_tick + offset,
                        "duration_ticks": n.duration_ticks,
                        "velocity": n.velocity,
                        "channel": n.channel if n.channel is not None else track.channel,
                        "program": track.program,
                        "is_drum": track.is_drum,
                    }
                )
    return sorted(notes, key=lambda x: (x["start_tick"], x["pitch"]))


def apply_tempo_ramp(
    timeline: MasterTimeline,
    start_tick: int,
    end_tick: int,
    start_bpm: float,
    end_bpm: float,
    policy: str = "linear_ramp",
) -> MasterTimeline:
    """Insert tempo ramp events into master tempo track."""
    result = copy.deepcopy(timeline)
    steps = max(1, (end_tick - start_tick) // result.master_ppq)
    new_events: list[TempoEvent] = []

    for i in range(steps + 1):
        t = start_tick + int((end_tick - start_tick) * i / steps)
        if policy == "step_at_boundary" and i < steps:
            bpm = start_bpm
        elif policy == "exponential_ramp":
            ratio = i / steps if steps else 1
            bpm = start_bpm * ((end_bpm / start_bpm) ** ratio)
        elif policy == "hold_song1_then_ramp" and i < steps // 2:
            bpm = start_bpm
        else:
            ratio = i / steps if steps else 1
            bpm = start_bpm + (end_bpm - start_bpm) * ratio
        new_events.append(TempoEvent(tick=t, bpm=bpm))

    # Replace events in range
    kept = [e for e in result.tempo_events if e.tick < start_tick or e.tick > end_tick]
    result.tempo_events = sorted(kept + new_events, key=lambda e: e.tick)
    return result


def create_transition_config(from_song_id: str, to_song_id: str) -> TransitionConfig:
    return TransitionConfig(
        id=str(uuid.uuid4()),
        from_song_id=from_song_id,
        to_song_id=to_song_id,
    )
