from midiweaver.models import TrackMappingEntry
from midiweaver.normalize.track_export import apply_export_track_mapping, song_scoped_track_id


def test_song_scoped_track_id():
    assert song_scoped_track_id("song_a", "track_004") == "song_a:track_004"


def test_unmapped_notes_stay_song_scoped():
    notes = [
        {
            "song_id": "song_a",
            "track_id": "track_001",
            "track_name": "Drums",
            "master_track_id": "song_a:track_001",
        },
        {
            "song_id": "song_b",
            "track_id": "track_001",
            "track_name": "Drums",
            "master_track_id": "song_b:track_001",
        },
    ]
    mapped, unmapped = apply_export_track_mapping(notes, [], {"song_a": "Song A", "song_b": "Song B"})
    groups = {n["export_group_id"] for n in mapped}
    assert groups == {"song_a:track_001", "song_b:track_001"}
    assert len(unmapped) == 2


def test_mapping_merges_different_track_indices():
    notes = [
        {
            "song_id": "song_a",
            "track_id": "track_004",
            "track_name": "Nylon Guitar",
            "master_track_id": "song_a:track_004",
        },
        {
            "song_id": "song_b",
            "track_id": "track_012",
            "track_name": "Nylon Guitar",
            "master_track_id": "song_b:track_012",
        },
    ]
    mapping = [
        TrackMappingEntry(
            master_track_id="nylon_guitar",
            role="Nylon Guitar",
            song_track_ids={"song_a": "track_004", "song_b": "track_012"},
        )
    ]
    mapped, unmapped = apply_export_track_mapping(notes, mapping)
    groups = {n["export_group_id"] for n in mapped}
    names = {n["export_track_name"] for n in mapped}
    assert groups == {"nylon_guitar"}
    assert names == {"Nylon Guitar"}
    assert unmapped == []
