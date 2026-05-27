from pathlib import Path

from midiweaver.analysis.analyzer import analyze_midi


def test_analyze_midi(fixture_dir: Path):
    path = fixture_dir / "song_a.mid"
    snap = analyze_midi(path, "song_a")
    assert snap.ppq == 480
    assert snap.estimated_bpm == 120.0
    assert len(snap.tracks) >= 2
    assert snap.trim_start_tick >= 0
    assert snap.bar_count > 0


def test_track_summaries(fixture_dir: Path):
    snap = analyze_midi(fixture_dir / "song_a.mid", "song_a")
    assert any(t.is_drum for t in snap.track_summaries)
    assert all(t.note_count >= 0 for t in snap.track_summaries)


def test_analyze_preserves_channel_and_program(fixture_dir: Path):
    snap = analyze_midi(fixture_dir / "song_a.mid", "song_a")
    melody = next(t for t in snap.tracks if t.name == "Melody")
    drums = next(t for t in snap.tracks if t.is_drum)
    assert melody.channel == 0
    assert melody.program == 33
    assert drums.channel == 9
    if melody.notes:
        assert melody.notes[0].start_tick == 0
