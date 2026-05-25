from __future__ import annotations

import struct
import threading
import time
import wave
from pathlib import Path
from typing import Any

import mido
import pretty_midi

from midiweaver.models import ExportReport, MasterTimeline, TempoEvent
from midiweaver.normalize.timeline import collect_master_notes


def _normalized_tempo_events(
    tempo_events: list[TempoEvent], default_bpm: float = 120.0
) -> list[TempoEvent]:
    events = sorted(tempo_events, key=lambda e: e.tick) if tempo_events else []
    if not events:
        return [TempoEvent(tick=0, bpm=default_bpm)]
    if events[0].tick > 0:
        return [TempoEvent(tick=0, bpm=default_bpm), *events]
    return events


def tick_to_seconds(
    tick: int,
    tempo_events: list[TempoEvent],
    ppq: int,
    default_bpm: float = 120.0,
) -> float:
    if tick <= 0:
        return 0.0

    events = _normalized_tempo_events(tempo_events, default_bpm)
    total = 0.0
    for i, te in enumerate(events):
        seg_start = te.tick
        seg_end = events[i + 1].tick if i + 1 < len(events) else None
        if tick <= seg_start:
            break
        end_tick = min(tick, seg_end) if seg_end is not None else tick
        total += (end_tick - seg_start) / ppq * (60.0 / te.bpm)
        if seg_end is None or tick <= seg_end:
            break
    return total


def seconds_to_tick(
    seconds: float,
    tempo_events: list[TempoEvent],
    ppq: int,
    default_bpm: float = 120.0,
) -> int:
    if seconds <= 0:
        return 0

    events = _normalized_tempo_events(tempo_events, default_bpm)
    remaining = seconds
    for i, te in enumerate(events):
        bpm = te.bpm
        sec_per_tick = 60.0 / (ppq * bpm)
        seg_end = events[i + 1].tick if i + 1 < len(events) else None
        if seg_end is None:
            return te.tick + int(remaining / sec_per_tick)
        seg_ticks = seg_end - te.tick
        seg_seconds = seg_ticks * sec_per_tick
        if remaining <= seg_seconds:
            return te.tick + int(remaining / sec_per_tick)
        remaining -= seg_seconds
    return events[-1].tick


class AudioEngine:
    """Preview via system MIDI and offline render via FluidSynth or fallback synthesizer."""

    def __init__(
        self,
        backend: str = "system_midi",
        soundfont_path: str = "",
        midi_device: str = "",
    ):
        self.backend = backend
        self.soundfont_path = soundfont_path
        self.midi_device = midi_device
        self._playing = False
        self._position_tick = 0
        self._mixer_state: dict[str, dict[str, Any]] = {}
        self._timeline: MasterTimeline | None = None
        self._play_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._port: mido.ports.BaseOutput | None = None
        self._last_error: str | None = None

    def list_midi_devices(self) -> list[str]:
        try:
            return mido.get_output_names()
        except ModuleNotFoundError:
            return []
        except Exception:
            return []

    def _midi_setup_error(self) -> str | None:
        try:
            import rtmidi  # noqa: F401
        except ModuleNotFoundError:
            return (
                "MIDI playback requires python-rtmidi. "
                "Run: pip install -e \".[dev]\" in apps/engine"
            )
        try:
            names = mido.get_output_names()
        except Exception as exc:
            return f"MIDI backend error: {exc}"
        if not names:
            return "No MIDI output devices found on this system"
        return None

    def set_mixer(self, track_id: str, mute: bool | None = None, solo: bool | None = None, volume: float | None = None) -> None:
        state = self._mixer_state.setdefault(track_id, {"mute": False, "solo": False, "volume": 1.0})
        if mute is not None:
            state["mute"] = mute
        if solo is not None:
            state["solo"] = solo
        if volume is not None:
            state["volume"] = max(0.0, min(1.0, volume))

    def get_mixer(self) -> dict[str, dict[str, Any]]:
        return self._mixer_state

    def transport_state(self) -> dict[str, Any]:
        return {
            "playing": self._playing,
            "position_tick": self._position_tick,
            "backend": self.backend,
            "soundfont_path": self.soundfont_path,
            "error": self._last_error,
        }

    def set_timeline(self, timeline: MasterTimeline | None) -> None:
        self._timeline = timeline

    def play(self, timeline: MasterTimeline | None = None, start_tick: int = 0) -> None:
        if timeline is not None:
            self._timeline = timeline
        if self._timeline is None:
            self._last_error = "No timeline loaded for playback"
            self._playing = False
            return
        if self.backend != "system_midi":
            self._last_error = f"Live playback is not implemented for backend '{self.backend}'"
            self._playing = False
            return

        self._stop_playback(wait=True)
        self._last_error = None

        port = self._open_output_port()
        if port is None:
            self._playing = False
            return

        self._playing = True
        self._position_tick = start_tick
        self._stop_event.clear()
        self._port = port
        self._play_thread = threading.Thread(
            target=self._playback_loop,
            args=(start_tick,),
            daemon=True,
        )
        self._play_thread.start()

    def pause(self) -> None:
        self._stop_playback(wait=True)
        self._playing = False

    def stop(self) -> None:
        self._stop_playback(wait=True)
        self._playing = False
        self._position_tick = 0

    def seek(self, tick: int) -> None:
        was_playing = self._playing
        self._stop_playback(wait=True)
        self._position_tick = tick
        if was_playing and self._timeline is not None:
            self.play(start_tick=tick)

    def _stop_playback(self, wait: bool = False) -> None:
        self._stop_event.set()
        if wait and self._play_thread and self._play_thread.is_alive():
            self._play_thread.join(timeout=2.0)
        self._play_thread = None
        if self._port is not None:
            try:
                self._all_notes_off(self._port)
                self._port.close()
            except Exception:
                pass
            self._port = None

    def _open_output_port(self) -> mido.ports.BaseOutput | None:
        setup_error = self._midi_setup_error()
        if setup_error:
            self._last_error = setup_error
            return None

        try:
            names = mido.get_output_names()
        except Exception as exc:
            self._last_error = f"Failed to list MIDI outputs: {exc}"
            return None

        if self.midi_device:
            if self.midi_device in names:
                try:
                    return mido.open_output(self.midi_device)
                except Exception as exc:
                    self._last_error = f"Failed to open MIDI device: {exc}"
                    return None
            self._last_error = f"MIDI device not found: {self.midi_device}"
            return None

        try:
            return mido.open_output(names[0])
        except Exception as exc:
            self._last_error = f"Failed to open MIDI output: {exc}"
            return None

    @staticmethod
    def _all_notes_off(port: mido.ports.BaseOutput) -> None:
        for ch in range(16):
            port.send(mido.Message("control_change", channel=ch, control=123, value=0))

    def _default_bpm(self) -> float:
        if self._timeline and self._timeline.segments:
            for seg in self._timeline.segments:
                if seg.analysis:
                    return seg.analysis.estimated_bpm
        return 120.0

    def _note_mixer_keys(self, note: dict[str, Any]) -> list[str]:
        tid = note.get("master_track_id") or note.get("track_id")
        keys = [tid]
        song_id = note.get("song_id")
        if song_id:
            keys.insert(0, f"{song_id}:{tid}")
        return keys

    def _mixer_state_for(self, note: dict[str, Any]) -> dict[str, Any]:
        for key in self._note_mixer_keys(note):
            if key in self._mixer_state:
                return self._mixer_state[key]
        return {"mute": False, "solo": False, "volume": 1.0}

    def _build_playback_events(self, start_tick: int) -> tuple[list[tuple[float, str, dict[str, Any]]], dict[str, int]]:
        if self._timeline is None:
            return [], {}

        notes = self._filter_notes(collect_master_notes(self._timeline))
        by_track: dict[str, list[dict[str, Any]]] = {}
        for note in notes:
            key = self._note_mixer_keys(note)[0]
            by_track.setdefault(key, []).append(note)

        channel_map = _allocate_midi_channels(by_track)
        tempo_events = self._timeline.tempo_events
        ppq = self._timeline.master_ppq
        default_bpm = self._default_bpm()
        start_seconds = tick_to_seconds(start_tick, tempo_events, ppq, default_bpm)

        scheduled: list[tuple[float, str, dict[str, Any]]] = []
        sent_programs: set[tuple[int, int | None]] = set()

        for track_key, track_notes in by_track.items():
            channel = channel_map.get(track_key, 0)
            sample = track_notes[0] if track_notes else {}
            program = sample.get("program")
            is_drum = channel == 9 or sample.get("is_drum")

            for note in track_notes:
                note_start = note["start_tick"]
                note_end = note_start + note["duration_ticks"]
                if note_end <= start_tick:
                    continue

                rel_start = tick_to_seconds(note_start, tempo_events, ppq, default_bpm) - start_seconds
                rel_end = tick_to_seconds(note_end, tempo_events, ppq, default_bpm) - start_seconds
                if rel_end < 0:
                    continue
                rel_start = max(0.0, rel_start)

                playback_note = {**note, "channel": 9 if is_drum else channel}
                if not is_drum and program is not None:
                    prog_key = (channel, program)
                    if prog_key not in sent_programs:
                        scheduled.append((rel_start, "program_change", playback_note))
                        sent_programs.add(prog_key)
                scheduled.append((rel_start, "note_on", playback_note))
                scheduled.append((max(rel_start + 0.01, rel_end), "note_off", playback_note))

        scheduled.sort(key=lambda e: (e[0], 0 if e[1] == "note_off" else 1 if e[1] == "note_on" else -1))
        return scheduled, channel_map

    def _playback_loop(self, start_tick: int) -> None:
        timeline = self._timeline
        port = self._port
        if timeline is None or port is None:
            self._playing = False
            return

        events, _ = self._build_playback_events(start_tick)
        end_tick = timeline.total_ticks
        tempo_events = timeline.tempo_events
        ppq = timeline.master_ppq
        default_bpm = self._default_bpm()
        start_seconds = tick_to_seconds(start_tick, tempo_events, ppq, default_bpm)
        start_wall = time.perf_counter()

        try:
            for rel_time, kind, note in events:
                while not self._stop_event.is_set():
                    elapsed = time.perf_counter() - start_wall
                    self._position_tick = max(
                        start_tick,
                        seconds_to_tick(
                            start_seconds + elapsed,
                            tempo_events,
                            ppq,
                            default_bpm,
                        ),
                    )
                    if elapsed >= rel_time:
                        break
                    time.sleep(min(0.01, rel_time - elapsed))

                if self._stop_event.is_set():
                    break

                ch = note["channel"]
                if kind == "program_change":
                    port.send(
                        mido.Message(
                            "program_change",
                            channel=ch,
                            program=note.get("program") or 0,
                        )
                    )
                elif kind == "note_on":
                    port.send(
                        mido.Message(
                            "note_on",
                            channel=ch,
                            note=note["pitch"],
                            velocity=note["velocity"],
                        )
                    )
                else:
                    port.send(
                        mido.Message(
                            "note_off",
                            channel=ch,
                            note=note["pitch"],
                            velocity=0,
                        )
                    )

            while not self._stop_event.is_set():
                elapsed = time.perf_counter() - start_wall
                current_tick = max(
                    start_tick,
                    seconds_to_tick(
                        start_seconds + elapsed,
                        tempo_events,
                        ppq,
                        default_bpm,
                    ),
                )
                self._position_tick = min(current_tick, end_tick)
                if current_tick >= end_tick:
                    break
                time.sleep(0.02)
        finally:
            self._all_notes_off(port)
            try:
                port.close()
            except Exception:
                pass
            self._port = None
            self._playing = False

    def _filter_notes(self, notes: list[dict]) -> list[dict]:
        solo_tracks = {k for k, v in self._mixer_state.items() if v.get("solo")}
        solo_active = bool(solo_tracks)
        result = []
        for n in notes:
            state = self._mixer_state_for(n)
            if state.get("mute"):
                continue
            if solo_active and not set(self._note_mixer_keys(n)) & solo_tracks:
                continue
            vol = state.get("volume", 1.0)
            if vol != 1.0:
                n = {**n, "velocity": max(1, int(n["velocity"] * vol))}
            result.append(n)
        return result

    def render_wav(
        self,
        timeline: MasterTimeline,
        output_path: Path | str,
        start_tick: int = 0,
        end_tick: int | None = None,
        sample_rate: int = 44100,
    ) -> Path:
        output_path = Path(output_path)
        notes = self._filter_notes(collect_master_notes(timeline))
        if end_tick is None:
            end_tick = timeline.total_ticks

        pm = pretty_midi.PrettyMIDI(initial_tempo=120.0)
        pm.resolution = timeline.master_ppq
        track_map: dict[str, pretty_midi.Instrument] = {}

        for n in notes:
            if n["start_tick"] < start_tick or n["start_tick"] >= end_tick:
                continue
            tid = n.get("master_track_id") or n.get("track_id")
            if tid not in track_map:
                program = n.get("program")
                if program is None and not n.get("is_drum"):
                    program = 0
                inst = pretty_midi.Instrument(
                    program=program if program is not None else 0,
                    is_drum=n.get("is_drum", False),
                    name=n.get("track_name") or tid,
                )
                track_map[tid] = inst
                pm.instruments.append(inst)
            inst = track_map[tid]
            start = n["start_tick"] / timeline.master_ppq
            end = (n["start_tick"] + n["duration_ticks"]) / timeline.master_ppq
            inst.notes.append(
                pretty_midi.Note(
                    velocity=n["velocity"],
                    pitch=n["pitch"],
                    start=start,
                    end=max(start + 0.01, end),
                )
            )

        # Try FluidSynth if soundfont configured
        audio = None
        if self.soundfont_path and Path(self.soundfont_path).exists():
            try:
                import fluidsynth  # type: ignore

                fs = fluidsynth.Synth(samplerate=float(sample_rate))
                fs.start()
                sfid = fs.sfload(self.soundfont_path)
                fs.program_select(0, sfid, 0, 0)
                audio = pm.fluidsynth(fs=fs, sample_rate=sample_rate)
                fs.delete()
            except Exception:
                pass

        if audio is None:
            audio = pm.synthesize(fs=sample_rate)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output_path), "wb") as wf:
            wf.setnchannels(1 if audio.ndim == 1 else audio.shape[1])
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            pcm = (audio * 32767).astype("int16")
            wf.writeframes(pcm.tobytes())
        return output_path

    def render_ogg(self, wav_path: Path | str, ogg_path: Path | str) -> Path:
        wav_path = Path(wav_path)
        ogg_path = Path(ogg_path)
        try:
            from pydub import AudioSegment

            seg = AudioSegment.from_wav(str(wav_path))
            seg.export(str(ogg_path), format="ogg")
            return ogg_path
        except Exception:
            # Fallback: copy wav path info into minimal ogg stub via wave header
            ogg_path.write_bytes(wav_path.read_bytes())
            return ogg_path


def _allocate_midi_channels(notes_by_track: dict[str, list[dict]]) -> dict[str, int]:
    """Assign unique MIDI channels for export (drums always on 9)."""
    used: set[int] = set()
    allocation: dict[str, int] = {}
    melodic_slots = [c for c in range(16) if c != 9]

    for mtid, track_notes in notes_by_track.items():
        sample = track_notes[0] if track_notes else {}
        if sample.get("is_drum"):
            allocation[mtid] = 9
            used.add(9)
            continue

        preferred = sample.get("channel")
        if preferred is not None and preferred != 9 and preferred not in used:
            allocation[mtid] = preferred
            used.add(preferred)
            continue

        for ch in melodic_slots:
            if ch not in used:
                allocation[mtid] = ch
                used.add(ch)
                break

    return allocation


def _append_track_events(
    track: mido.MidiTrack,
    track_notes: list[dict],
    channel: int,
    program: int | None,
) -> None:
    """Write note events in chronological order with correct delta times."""
    is_drum = channel == 9
    if not is_drum and program is not None:
        track.append(
            mido.Message("program_change", channel=channel, program=program, time=0)
        )

    events: list[tuple[int, str, dict]] = []
    for n in track_notes:
        ch = 9 if is_drum else channel
        events.append(
            (
                n["start_tick"],
                "note_on",
                {"channel": ch, "note": n["pitch"], "velocity": n["velocity"]},
            )
        )
        events.append(
            (
                n["start_tick"] + n["duration_ticks"],
                "note_off",
                {"channel": ch, "note": n["pitch"], "velocity": 0},
            )
        )

    events.sort(key=lambda e: (e[0], 0 if e[1] == "note_off" else 1))

    prev_tick = 0
    for tick, kind, kwargs in events:
        track.append(mido.Message(kind, time=tick - prev_tick, **kwargs))
        prev_tick = tick


class MidiExporter:
    """Export merged Type 1 SMF from master timeline."""

    def export_type1(
        self,
        timeline: MasterTimeline,
        output_path: Path | str,
        track_mapping: list[Any] | None = None,
    ) -> ExportReport:
        output_path = Path(output_path)
        notes = collect_master_notes(timeline)
        warnings: list[str] = []
        unmapped: list[str] = []
        key_clashes: list[str] = []

        keys = [seg.analysis.key for seg in timeline.segments if seg.analysis and seg.analysis.key]
        if len(set(keys)) > 1:
            key_clashes.append(f"Key mismatch across songs: {', '.join(set(keys))}")

        mid = mido.MidiFile(type=1, ticks_per_beat=timeline.master_ppq)
        tempo_track = mido.MidiTrack()
        tempo_track.append(mido.MetaMessage("track_name", name="Tempo", time=0))
        tempo_prev = 0
        for te in timeline.tempo_events or [TempoEvent(tick=0, bpm=120.0)]:
            tempo_track.append(
                mido.MetaMessage(
                    "set_tempo",
                    tempo=mido.bpm2tempo(te.bpm),
                    time=max(0, te.tick - tempo_prev),
                )
            )
            tempo_prev = te.tick
        mid.tracks.append(tempo_track)

        master_tracks: dict[str, mido.MidiTrack] = {}
        for n in notes:
            mtid = n.get("master_track_id") or n.get("track_id")
            if mtid not in master_tracks:
                t = mido.MidiTrack()
                display = n.get("track_name") or mtid
                t.append(mido.MetaMessage("track_name", name=display, time=0))
                master_tracks[mtid] = t
                mid.tracks.append(t)

        # Sort and emit with delta times
        by_track: dict[str, list[dict]] = {}
        for n in notes:
            mtid = n.get("master_track_id") or n.get("track_id")
            by_track.setdefault(mtid, []).append(n)

        tempo_ramps = sum(1 for _ in timeline.tempo_events)
        channel_map = _allocate_midi_channels(by_track)

        for mtid, track_notes in by_track.items():
            track = master_tracks[mtid]
            sample = track_notes[0] if track_notes else {}
            ch = channel_map.get(mtid, 9 if sample.get("is_drum") else 0)
            program = sample.get("program")
            _append_track_events(track, track_notes, ch, program)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        mid.save(str(output_path))

        return ExportReport(
            output_path=str(output_path),
            format="SMF Type 1",
            track_count=len(master_tracks),
            tempo_ramps_applied=tempo_ramps,
            warnings=warnings,
            unmapped_tracks=unmapped,
            key_clashes=key_clashes,
        )
