from __future__ import annotations

import io
from pathlib import Path

import mido
import pretty_midi

from midiweaver.models import (
    AnalysisSnapshot,
    NoteEvent,
    TempoEvent,
    TimeSignatureEvent,
    TrackData,
    TrackSummary,
)


def _detect_key(pm: pretty_midi.PrettyMIDI) -> str | None:
    try:
        from music21 import converter, key

        buf = io.BytesIO()
        pm.write(buf)
        buf.seek(0)
        score = converter.parse(buf)
        detected = score.analyze("key")
        if isinstance(detected, key.Key):
            return str(detected)
    except Exception:
        pass
    return None


def _estimate_bpm_from_tempo_events(tempo_events: list[TempoEvent]) -> tuple[float, tuple[float, float]]:
    if not tempo_events:
        return 120.0, (120.0, 120.0)
    values = [e.bpm for e in tempo_events]
    avg = sum(values) / len(values)
    return avg, (min(values), max(values))


def _bar_count_from_ticks(end_tick: int, ppq: int, bpm: float, beats_per_bar: int) -> float:
    beats = (end_tick / ppq) * (bpm / 60.0)
    return beats / beats_per_bar


def _find_silence_trim(
    tracks: list[TrackData], ppq: int, threshold: float = 0.05
) -> tuple[int, int]:
    all_notes = [n for t in tracks for n in t.notes]
    if not all_notes:
        return 0, ppq * 16

    end_tick = max(n.start_tick + n.duration_ticks for n in all_notes)
    start_tick = min(n.start_tick for n in all_notes)

    bar_ticks = ppq * 4
    refined_start = start_tick
    for tick in range(0, start_tick + bar_ticks, bar_ticks // 4 or 1):
        activity = sum(
            1
            for n in all_notes
            if n.start_tick < tick + bar_ticks and n.start_tick + n.duration_ticks > tick
        )
        if activity > 0:
            refined_start = max(0, tick - bar_ticks // 4)
            break

    return refined_start, end_tick


def _loop_boundaries(tracks: list[TrackData], ppq: int) -> list[int]:
    all_notes = [n for t in tracks for n in t.notes]
    if not all_notes:
        return []

    end_tick = max(n.start_tick + n.duration_ticks for n in all_notes)
    bar_ticks = ppq * 4
    if end_tick < bar_ticks * 2:
        return []

    boundaries: list[int] = []
    prev_density = 0.0
    for bar in range(1, end_tick // bar_ticks):
        tick = bar * bar_ticks
        count = sum(
            1 for n in all_notes if tick <= n.start_tick < tick + bar_ticks
        )
        density = count / 4.0
        if prev_density > 2 and density < prev_density * 0.5:
            boundaries.append(tick)
        prev_density = density
    return boundaries


def _parse_mido_track(
    mid_track: mido.MidiTrack,
    track_index: int,
    default_name: str,
) -> tuple[TrackData | None, list[TempoEvent], list[TimeSignatureEvent]]:
    """Extract notes, tempo, and time-signature meta from one SMF track."""
    abs_tick = 0
    track_name = default_name
    channel_program: dict[int, int] = {}
    channel_notes: dict[int, list[NoteEvent]] = {}
    active: dict[tuple[int, int], tuple[int, int]] = {}
    tempo_events: list[TempoEvent] = []
    time_sig_events: list[TimeSignatureEvent] = []

    for msg in mid_track:
        abs_tick += msg.time
        if msg.is_meta:
            if msg.type == "track_name":
                track_name = msg.name or track_name
            elif msg.type == "set_tempo":
                tempo_events.append(
                    TempoEvent(tick=abs_tick, bpm=float(mido.tempo2bpm(msg.tempo)))
                )
            elif msg.type == "time_signature":
                time_sig_events.append(
                    TimeSignatureEvent(
                        tick=abs_tick,
                        numerator=msg.numerator,
                        denominator=msg.denominator,
                    )
                )
            continue

        if not hasattr(msg, "channel"):
            continue

        ch = msg.channel
        if msg.type == "program_change":
            channel_program[ch] = msg.program
            continue

        if msg.type == "note_on" and msg.velocity > 0:
            active[(ch, msg.note)] = (abs_tick, msg.velocity)
            continue

        if msg.type in ("note_off", "note_on") and (
            msg.type == "note_off" or msg.velocity == 0
        ):
            key = (ch, msg.note)
            if key not in active:
                continue
            start_tick, velocity = active.pop(key)
            channel_notes.setdefault(ch, []).append(
                NoteEvent(
                    pitch=msg.note,
                    start_tick=start_tick,
                    duration_ticks=max(1, abs_tick - start_tick),
                    velocity=velocity,
                    channel=ch,
                )
            )

    if not channel_notes:
        return None, tempo_events, time_sig_events

    # Prefer a single channel per SMF track; split only when multiple channels carry notes.
    if len(channel_notes) == 1:
        ch = next(iter(channel_notes))
        is_drum = ch == 9
        program = channel_program.get(ch, 0 if not is_drum else None)
        return (
            TrackData(
                track_id=f"track_{track_index:03d}",
                name=track_name,
                channel=ch,
                program=program if not is_drum else None,
                is_drum=is_drum,
                notes=sorted(channel_notes[ch], key=lambda n: n.start_tick),
            ),
            tempo_events,
            time_sig_events,
        )

    # Multiple melodic channels in one track — keep the busiest channel as primary.
    ch = max(channel_notes, key=lambda c: len(channel_notes[c]))
    is_drum = ch == 9
    program = channel_program.get(ch, 0 if not is_drum else None)
    return (
        TrackData(
            track_id=f"track_{track_index:03d}",
            name=track_name,
            channel=ch,
            program=program if not is_drum else None,
            is_drum=is_drum,
            notes=sorted(channel_notes[ch], key=lambda n: n.start_tick),
        ),
        tempo_events,
        time_sig_events,
    )


def _parse_type0_by_channel(mid: mido.MidiFile) -> list[TrackData]:
    """Type 0 files use one track; split notes by MIDI channel."""
    if not mid.tracks:
        return []

    abs_tick = 0
    channel_program: dict[int, int] = {}
    channel_notes: dict[int, list[NoteEvent]] = {}
    channel_names: dict[int, str] = {}
    active: dict[tuple[int, int], tuple[int, int]] = {}

    for msg in mid.tracks[0]:
        abs_tick += msg.time
        if msg.is_meta:
            if msg.type == "track_name":
                for ch in range(16):
                    channel_names.setdefault(ch, msg.name)
            continue

        if not hasattr(msg, "channel"):
            continue

        ch = msg.channel
        if msg.type == "program_change":
            channel_program[ch] = msg.program
            continue

        if msg.type == "note_on" and msg.velocity > 0:
            active[(ch, msg.note)] = (abs_tick, msg.velocity)
            continue

        if msg.type in ("note_off", "note_on") and (
            msg.type == "note_off" or msg.velocity == 0
        ):
            key = (ch, msg.note)
            if key not in active:
                continue
            start_tick, velocity = active.pop(key)
            channel_notes.setdefault(ch, []).append(
                NoteEvent(
                    pitch=msg.note,
                    start_tick=start_tick,
                    duration_ticks=max(1, abs_tick - start_tick),
                    velocity=velocity,
                    channel=ch,
                )
            )

    tracks: list[TrackData] = []
    idx = 0
    for ch in sorted(channel_notes):
        if not channel_notes[ch]:
            continue
        is_drum = ch == 9
        program = channel_program.get(ch, 0 if not is_drum else None)
        name = channel_names.get(ch) or ("Drums" if is_drum else f"Channel {ch + 1}")
        tracks.append(
            TrackData(
                track_id=f"track_{idx:03d}",
                name=name,
                channel=ch,
                program=program if not is_drum else None,
                is_drum=is_drum,
                notes=sorted(channel_notes[ch], key=lambda n: n.start_tick),
            )
        )
        idx += 1
    return tracks


def _extract_tracks_mido(path: Path) -> tuple[
    int,
    list[TrackData],
    list[TempoEvent],
    list[TimeSignatureEvent],
    tuple[int, int],
]:
    mid = mido.MidiFile(str(path))
    ppq = mid.ticks_per_beat
    all_tempo: list[TempoEvent] = []
    all_ts: list[TimeSignatureEvent] = []
    tracks: list[TrackData] = []

    if mid.type == 0:
        tracks = _parse_type0_by_channel(mid)
        for msg in mid.tracks[0]:
            if msg.is_meta and msg.type == "set_tempo":
                pass  # collected below via full scan
        abs_tick = 0
        for msg in mid.tracks[0]:
            abs_tick += msg.time
            if msg.is_meta and msg.type == "set_tempo":
                all_tempo.append(
                    TempoEvent(tick=abs_tick, bpm=float(mido.tempo2bpm(msg.tempo)))
                )
            elif msg.is_meta and msg.type == "time_signature":
                all_ts.append(
                    TimeSignatureEvent(
                        tick=abs_tick,
                        numerator=msg.numerator,
                        denominator=msg.denominator,
                    )
                )
    else:
        for i, mid_track in enumerate(mid.tracks):
            parsed, tempo, ts = _parse_mido_track(
                mid_track, i, default_name=f"Track {i + 1}"
            )
            all_tempo.extend(tempo)
            all_ts.extend(ts)
            if parsed is not None:
                tracks.append(parsed)

    if not all_tempo:
        all_tempo.append(TempoEvent(tick=0, bpm=120.0))

    time_sig = (4, 4)
    if all_ts:
        time_sig = (all_ts[0].numerator, all_ts[0].denominator)

    return ppq, tracks, sorted(all_tempo, key=lambda e: e.tick), all_ts, time_sig


def analyze_midi(
    path: Path | str,
    song_id: str,
    silence_threshold: float = 0.05,
) -> AnalysisSnapshot:
    path = Path(path)
    ppq, tracks, tempo_events, time_sig_events, time_sig = _extract_tracks_mido(path)
    bpm, bpm_range = _estimate_bpm_from_tempo_events(tempo_events)
    trim_start, trim_end = _find_silence_trim(tracks, ppq, silence_threshold)

    summaries: list[TrackSummary] = []
    bar_count = _bar_count_from_ticks(trim_end, ppq, bpm, time_sig[0])

    for track in tracks:
        pitches = [n.pitch for n in track.notes]
        summaries.append(
            TrackSummary(
                track_id=track.track_id,
                name=track.name,
                channel=track.channel,
                program=track.program,
                is_drum=track.is_drum,
                note_min=min(pitches) if pitches else None,
                note_max=max(pitches) if pitches else None,
                note_count=len(track.notes),
                density_per_bar=len(track.notes) / max(bar_count, 1),
            )
        )

    key: str | None = None
    try:
        pm = pretty_midi.PrettyMIDI(str(path))
        key = _detect_key(pm)
    except Exception:
        pass

    warnings: list[str] = []
    if len(tempo_events) > 1:
        warnings.append("Multiple tempo changes detected")

    return AnalysisSnapshot(
        song_id=song_id,
        source_filename=path.name,
        ppq=ppq,
        bar_count=bar_count,
        estimated_bpm=bpm,
        bpm_range=bpm_range,
        time_sig=time_sig,
        key=key,
        tempo_events=tempo_events,
        time_sig_events=time_sig_events,
        track_summaries=summaries,
        tracks=tracks,
        trim_start_tick=trim_start,
        trim_end_tick=trim_end,
        loop_boundaries=_loop_boundaries(tracks, ppq),
        warnings=warnings,
    )


def read_midi_meta(path: Path | str) -> dict:
    mid = mido.MidiFile(str(path))
    return {
        "type": mid.type,
        "ticks_per_beat": mid.ticks_per_beat,
        "track_count": len(mid.tracks),
        "length": mid.length,
    }
