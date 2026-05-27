from __future__ import annotations

import copy
from typing import Any, Literal

from midiweaver.models import AnalysisSnapshot, NoteEvent, SongSegment, TrackData
from midiweaver.normalize.notes import ensure_note_id
from midiweaver.normalize.timeline import build_master_timeline, sync_segment_trim_bounds

Placement = Literal["intro", "outro", "both"]
Style = Literal["four_on_floor", "build_up", "phrase_repeat"]
Source = Literal["auto", "selection", "template"]

KICK = 36
SNARE = 38
CLOSED_HH = 42
OPEN_HH = 46
DEFAULT_VEL = 90


def find_drum_track(analysis: AnalysisSnapshot) -> TrackData | None:
    for track in analysis.tracks:
        if track.is_drum:
            return track
    best: TrackData | None = None
    best_count = 0
    for track in analysis.tracks:
        ch9 = sum(1 for n in track.notes if n.channel == 9)
        if ch9 > best_count:
            best_count = ch9
            best = track
    return best


def ensure_drum_track(analysis: AnalysisSnapshot) -> TrackData:
    track = find_drum_track(analysis)
    if track:
        track.is_drum = True
        track.channel = 9
        return track
    new_track = TrackData(
        track_id=f"dj_drums_{len(analysis.tracks)}",
        name="DJ Drums",
        channel=9,
        is_drum=True,
        notes=[],
    )
    analysis.tracks.append(new_track)
    return new_track


def extract_phrase(notes: list[NoteEvent], start_tick: int, end_tick: int) -> list[NoteEvent]:
    phrase: list[NoteEvent] = []
    for n in notes:
        if start_tick <= n.start_tick < end_tick:
            phrase.append(
                ensure_note_id(
                    NoteEvent(
                        pitch=n.pitch,
                        start_tick=n.start_tick - start_tick,
                        duration_ticks=n.duration_ticks,
                        velocity=n.velocity,
                        channel=n.channel or 9,
                    )
                )
            )
    return phrase


def _bar_ticks(analysis: AnalysisSnapshot, ppq: int) -> int:
    return ppq * analysis.time_sig[0]


def phrase_from_auto(seg: SongSegment, which: Literal["intro", "outro"], bars: int, ppq: int) -> list[NoteEvent]:
    if not seg.analysis:
        return []
    a = seg.analysis
    track = find_drum_track(a)
    if not track or not track.notes:
        return []
    bar_ticks = _bar_ticks(a, ppq)
    span = bars * bar_ticks
    if which == "intro":
        start = a.trim_start_tick
        end = min(start + span, a.trim_end_tick or start + span)
    else:
        end_local = a.trim_end_tick or (seg.master_end_tick - (seg.master_start_tick - a.trim_start_tick))
        end = end_local
        start = max(a.trim_start_tick, end - span)
    return extract_phrase(track.notes, start, end)


def phrase_from_selection(
    seg: SongSegment,
    master_bar_range: list[float],
    timeline_ppq: int,
    bpm: float,
    beats: int,
) -> list[NoteEvent]:
    from midiweaver.normalize.timeline import bars_to_ticks

    if not seg.analysis:
        return []
    a = seg.analysis
    track = find_drum_track(a)
    if not track:
        return []
    offset = seg.master_start_tick - a.trim_start_tick
    start_master = bars_to_ticks(float(master_bar_range[0]), timeline_ppq, bpm, beats)
    end_master = bars_to_ticks(float(master_bar_range[1]), timeline_ppq, bpm, beats)
    start_local = start_master - offset
    end_local = end_master - offset
    return extract_phrase(track.notes, start_local, end_local)


def render_pattern(style: Style, bars: int, ppq: int, beats_per_bar: int = 4) -> list[NoteEvent]:
    bar_ticks = ppq * beats_per_bar
    notes: list[NoteEvent] = []
    for bar in range(bars):
        base = bar * bar_ticks
        if style == "four_on_floor":
            for beat in range(beats_per_bar):
                t = base + beat * ppq
                notes.append(
                    NoteEvent(pitch=KICK, start_tick=t, duration_ticks=ppq // 2, velocity=DEFAULT_VEL, channel=9)
                )
                notes.append(
                    NoteEvent(
                        pitch=CLOSED_HH,
                        start_tick=t + ppq // 2,
                        duration_ticks=ppq // 4,
                        velocity=70,
                        channel=9,
                    )
                )
            if bar == bars - 1:
                notes.append(
                    NoteEvent(
                        pitch=OPEN_HH,
                        start_tick=base + bar_ticks - ppq // 2,
                        duration_ticks=ppq // 2,
                        velocity=80,
                        channel=9,
                    )
                )
        elif style == "build_up":
            for eighth in range(beats_per_bar * 2):
                t = base + eighth * (ppq // 2)
                vel = 60 + min(40, eighth * 3 + bar * 5)
                notes.append(
                    NoteEvent(
                        pitch=CLOSED_HH,
                        start_tick=t,
                        duration_ticks=ppq // 4,
                        velocity=vel,
                        channel=9,
                    )
                )
            if bar >= bars - 1:
                notes.append(
                    NoteEvent(
                        pitch=SNARE,
                        start_tick=base + int(bar_ticks * 0.5),
                        duration_ticks=ppq,
                        velocity=100,
                        channel=9,
                    )
                )
                notes.append(
                    NoteEvent(
                        pitch=SNARE,
                        start_tick=base + int(bar_ticks * 0.75),
                        duration_ticks=ppq,
                        velocity=110,
                        channel=9,
                    )
                )
        elif style == "phrase_repeat":
            for beat in range(beats_per_bar):
                t = base + beat * ppq
                notes.append(
                    NoteEvent(pitch=KICK, start_tick=t, duration_ticks=ppq // 2, velocity=DEFAULT_VEL, channel=9)
                )
    return [ensure_note_id(n) for n in notes]


def _tile_phrase(
    phrase: list[NoteEvent],
    dest_base: int,
    total_bars: int,
    bar_ticks: int,
    ppq: int,
) -> list[NoteEvent]:
    if not phrase:
        return render_pattern("four_on_floor", total_bars, ppq)
    phrase_len = max((n.start_tick + n.duration_ticks for n in phrase), default=bar_ticks)
    phrase_len = max(phrase_len, bar_ticks)
    out: list[NoteEvent] = []
    rep = 0
    while rep * phrase_len < total_bars * bar_ticks:
        for n in phrase:
            tick = dest_base + rep * phrase_len + n.start_tick
            if tick >= dest_base + total_bars * bar_ticks:
                break
            out.append(
                ensure_note_id(
                    NoteEvent(
                        pitch=n.pitch,
                        start_tick=tick,
                        duration_ticks=n.duration_ticks,
                        velocity=n.velocity,
                        channel=n.channel,
                    )
                )
            )
        rep += 1
    return out


def apply_intro(
    seg: SongSegment,
    phrase: list[NoteEvent],
    bars: int,
    ppq: int,
) -> None:
    if not seg.analysis:
        return
    a = seg.analysis
    bar_ticks = _bar_ticks(a, ppq)
    shift = bars * bar_ticks
    track = ensure_drum_track(a)
    for n in track.notes:
        n.start_tick += shift
    intro_notes = _tile_phrase(phrase, a.trim_start_tick, bars, bar_ticks, ppq)
    track.notes.extend(intro_notes)
    sync_segment_trim_bounds(a)
    seg.trim_start_ticks = a.trim_start_tick
    seg.trim_end_ticks = a.trim_end_tick


def apply_outro(
    seg: SongSegment,
    phrase: list[NoteEvent],
    bars: int,
    ppq: int,
    dest_tick: int | None = None,
) -> None:
    if not seg.analysis:
        return
    a = seg.analysis
    bar_ticks = _bar_ticks(a, ppq)
    dest_base = dest_tick if dest_tick is not None else (a.trim_end_tick or a.trim_start_tick)
    track = ensure_drum_track(a)
    outro_notes = _tile_phrase(phrase, dest_base, bars, bar_ticks, ppq)
    track.notes.extend(outro_notes)
    sync_segment_trim_bounds(a)
    seg.trim_start_ticks = a.trim_start_tick
    seg.trim_end_ticks = a.trim_end_tick


def _resolve_phrase(
    seg: SongSegment,
    params: dict[str, Any],
    timeline,
    which: Literal["intro", "outro"],
) -> list[NoteEvent]:
    style = params.get("style", "phrase_repeat")
    bars = int(params.get("intro_bars" if which == "intro" else "outro_bars", params.get("bars", 4)))
    source = params.get("source", "auto")
    ppq = timeline.master_ppq
    bpm = 120.0
    beats = 4
    if seg.analysis:
        bpm = seg.analysis.estimated_bpm
        beats = seg.analysis.time_sig[0]

    if source == "selection" and params.get("master_bar_range"):
        phrase = phrase_from_selection(seg, params["master_bar_range"], ppq, bpm, beats)
        if phrase:
            return phrase
    if source != "template" and style == "phrase_repeat":
        phrase = phrase_from_auto(seg, which, bars, ppq)
        if phrase:
            return phrase
    return render_pattern(style if style != "phrase_repeat" else "four_on_floor", bars, ppq, beats)


def apply_dj_drums_to_context(ctx, params: dict[str, Any]):
    """Mutate ctx.timeline segments for add_dj_drums op."""
    new_ctx = copy.deepcopy(ctx)
    song_id = params["song_id"]
    placement = params.get("placement", "outro")
    ppq = new_ctx.timeline.master_ppq

    for seg in new_ctx.timeline.segments:
        if seg.id != song_id:
            continue
        if placement in ("intro", "both"):
            intro_bars = int(params.get("intro_bars", params.get("bars", 4)))
            phrase = _resolve_phrase(seg, params, new_ctx.timeline, "intro")
            apply_intro(seg, phrase, intro_bars, ppq)
        if placement in ("outro", "both"):
            outro_bars = int(params.get("outro_bars", params.get("bars", 4)))
            phrase = _resolve_phrase(seg, params, new_ctx.timeline, "outro")
            dest = params.get("dest_start_tick")
            if dest is not None:
                dest = int(dest)
            apply_outro(seg, phrase, outro_bars, ppq, dest_tick=dest)

    new_ctx.timeline = build_master_timeline(
        new_ctx.timeline.segments,
        new_ctx.timeline.master_ppq,
        new_ctx.timeline.transitions,
    )
    return new_ctx
