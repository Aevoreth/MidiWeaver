from midiweaver.analysis.analyzer import analyze_midi
from midiweaver.models import SongSegment
from midiweaver.normalize.timeline import (
    build_master_timeline,
    normalize_analysis,
    resample_tick,
    segment_duration_ticks,
)


def test_resample_tick():
    assert resample_tick(480, 480, 960) == 960
    assert resample_tick(480, 480, 480) == 480


def test_normalize_ppq(fixture_dir):
    snap = analyze_midi(fixture_dir / "song_a.mid", "a")
    norm = normalize_analysis(snap, 960)
    assert norm.ppq == 960
    if snap.tracks[0].notes:
        orig = snap.tracks[0].notes[0].start_tick
        assert norm.tracks[0].notes[0].start_tick == resample_tick(orig, 480, 960)


def test_build_master_timeline(fixture_dir):
    snap_a = analyze_midi(fixture_dir / "song_a.mid", "a")
    snap_b = analyze_midi(fixture_dir / "song_b.mid", "b")
    segs = [
        SongSegment(id="a", display_name="A", source_filename="a.mid", analysis=snap_a),
        SongSegment(id="b", display_name="B", source_filename="b.mid", analysis=snap_b),
    ]
    tl = build_master_timeline(segs, master_ppq=480)
    assert len(tl.segments) == 2
    assert tl.segments[1].master_start_tick == tl.segments[0].master_end_tick
    assert tl.total_ticks > 0
    assert segment_duration_ticks(snap_a) > 0
