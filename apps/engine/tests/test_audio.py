"""Audio engine playback and tempo conversion tests."""

from __future__ import annotations

import time

import mido
import pytest

from midiweaver.audio.engine import AudioEngine, seconds_to_tick, tick_to_seconds
from midiweaver.models import TempoEvent
from midiweaver.project.store import open_project


class FakePort:
    def __init__(self) -> None:
        self.messages: list[mido.Message] = []

    def send(self, msg: mido.Message) -> None:
        self.messages.append(msg)

    def close(self) -> None:
        pass


def test_tick_to_seconds_with_tempo_map() -> None:
    events = [TempoEvent(tick=0, bpm=120.0), TempoEvent(tick=480, bpm=240.0)]
    assert tick_to_seconds(0, events, 480) == 0.0
    assert tick_to_seconds(480, events, 480) == pytest.approx(0.5)
    assert tick_to_seconds(960, events, 480) == pytest.approx(0.75)


def test_seconds_to_tick_round_trip() -> None:
    events = [TempoEvent(tick=0, bpm=120.0), TempoEvent(tick=480, bpm=240.0)]
    for tick in (0, 240, 480, 720, 960):
        seconds = tick_to_seconds(tick, events, 480)
        assert seconds_to_tick(seconds, events, 480) == tick


def test_playback_sends_midi_messages(monkeypatch: pytest.MonkeyPatch, project_bundle) -> None:
    fake = FakePort()
    monkeypatch.setattr("mido.get_output_names", lambda: ["Fake Synth"])
    monkeypatch.setattr("mido.open_output", lambda name=None: fake)

    store = open_project(project_bundle)
    engine = AudioEngine()
    engine.play(store.timeline, 0)

    deadline = time.time() + 2.0
    while time.time() < deadline and engine.transport_state()["playing"]:
        time.sleep(0.05)

    engine.stop()

    note_ons = [m for m in fake.messages if m.type == "note_on"]
    assert note_ons, "Expected note_on messages during playback"
    assert any(m.velocity > 0 for m in note_ons)


def test_playback_without_timeline_sets_error() -> None:
    engine = AudioEngine()
    engine.play(None, 0)
    state = engine.transport_state()
    assert state["playing"] is False
    assert state["error"] == "No timeline loaded for playback"
