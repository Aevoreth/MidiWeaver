from midiweaver.ai.tool_compact import compact_diff_result, compact_query_notes, compact_tool_result


def test_compact_diff_result_counts_only():
    added = [{"pitch": i, "start_tick": i * 10, "track_id": "t1", "song_id": "s1"} for i in range(200)]
    compact = compact_diff_result({"revision_id": 1, "diff": {"added_notes": added, "removed_notes": [], "moved_notes": []}})
    assert compact["diff"]["added_count"] == 200
    assert len(compact["diff"]["added_sample"]) == 5


def test_compact_query_notes_limits_page():
    notes = [{"pitch": 36, "start_tick": i} for i in range(100)]
    compact = compact_query_notes({"total": 100, "notes": notes, "start_bar": 0, "end_bar": 4})
    assert compact["notes_returned"] == 24
    assert compact["truncated"] is True


def test_compact_tool_result_apply_op():
    added = [{"pitch": i, "start_tick": i, "track_id": "drums", "song_id": "song_1"} for i in range(500)]
    compact = compact_tool_result(
        "apply_op",
        {"revision_id": 9, "op_type": "copy_notes", "diff": {"added_notes": added, "removed_notes": [], "moved_notes": []}},
    )
    assert compact["diff"]["added_count"] == 500
    assert len(compact["diff"]["added_sample"]) == 5
