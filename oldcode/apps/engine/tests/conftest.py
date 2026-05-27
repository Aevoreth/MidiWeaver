"""Pytest fixtures and MIDI generators."""

from __future__ import annotations

import sys
import types
from pathlib import Path

# Stub broken optional fluidsynth wheel before pretty_midi imports it.
if "fluidsynth" not in sys.modules:
    _stub = types.ModuleType("fluidsynth")

    class _Synth:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

        def sfload(self, *args, **kwargs):
            return 0

        def program_select(self, *args, **kwargs):
            pass

        def delete(self):
            pass

    _stub.Synth = _Synth
    sys.modules["fluidsynth"] = _stub

import mido
import pytest


def write_simple_midi(path: Path, bpm: float = 120.0, note_count: int = 8) -> None:
    mid = mido.MidiFile(type=1, ticks_per_beat=480)
    tempo = mido.bpm2tempo(bpm)

    meta = mido.MidiTrack()
    meta.append(mido.MetaMessage("set_tempo", tempo=tempo, time=0))
    meta.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
    mid.tracks.append(meta)

    drums = mido.MidiTrack()
    drums.append(mido.MetaMessage("track_name", name="Drums", time=0))
    t = 0
    for i in range(note_count):
        drums.append(mido.Message("note_on", channel=9, note=36 + (i % 3), velocity=90, time=t))
        drums.append(mido.Message("note_off", channel=9, note=36 + (i % 3), velocity=0, time=240))
        t = 240
    mid.tracks.append(drums)

    melody = mido.MidiTrack()
    melody.append(mido.MetaMessage("track_name", name="Melody", time=0))
    melody.append(mido.Message("program_change", channel=0, program=33, time=0))
    t = 0
    pitches = [60, 62, 64, 65, 67, 69, 71, 72]
    for i, pitch in enumerate(pitches[:note_count]):
        melody.append(mido.Message("note_on", channel=0, note=pitch, velocity=80, time=t))
        melody.append(mido.Message("note_off", channel=0, note=pitch, velocity=0, time=480))
        t = 0
    mid.tracks.append(melody)

    path.parent.mkdir(parents=True, exist_ok=True)
    mid.save(str(path))


@pytest.fixture
def fixture_dir(tmp_path: Path) -> Path:
    d = tmp_path / "fixtures"
    write_simple_midi(d / "song_a.mid", bpm=120)
    write_simple_midi(d / "song_b.mid", bpm=140)
    return d


@pytest.fixture
def project_bundle(tmp_path: Path, fixture_dir: Path) -> Path:
    from midiweaver.project.store import create_project

    bundle = tmp_path / "TestSet.midiweaver"
    store = create_project(bundle, "Test Set")
    store.import_midi(fixture_dir / "song_a.mid", "Song A")
    store.import_midi(fixture_dir / "song_b.mid", "Song B")
    return bundle


@pytest.fixture
def isolated_settings(tmp_path: Path):
    from midiweaver import main as main_module
    from midiweaver.settings_store import load_settings, set_config_dir

    config_dir = tmp_path / "config"
    set_config_dir(config_dir)
    main_module._settings = load_settings()
    yield config_dir
    set_config_dir(None)
    main_module._settings = load_settings()
