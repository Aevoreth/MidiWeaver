"""Tests for query helpers and inspect API."""

from __future__ import annotations

from midiweaver.models import Operation
from midiweaver.query.context import (
    analyze_region,
    get_timeline_summary,
    get_transition_context,
    measure_region,
    query_notes,
)


def test_get_timeline_summary(project_bundle):
    from midiweaver.project.store import get_project

    store = get_project(str(project_bundle))
    summary = get_timeline_summary(store.timeline, [])
    assert len(summary["songs"]) == 2
    assert summary["master_ppq"] == 480


def test_query_notes_pagination(project_bundle):
    from midiweaver.project.store import get_project

    store = get_project(str(project_bundle))
    result = query_notes(store.timeline, start_bar=0, end_bar=8, limit=10, offset=0)
    assert "notes" in result
    assert result["total"] >= 0
    assert len(result["notes"]) <= 10


def test_analyze_region(project_bundle):
    from midiweaver.project.store import get_project

    store = get_project(str(project_bundle))
    result = analyze_region(store.timeline, [0, 4])
    assert "density_per_bar" in result
    assert result["bar_range"] == [0, 4]


def test_transition_context(project_bundle):
    from midiweaver.project.store import get_project

    store = get_project(str(project_bundle))
    trans = store.timeline.transitions[0]
    ctx = get_transition_context(store.timeline, trans.id)
    assert ctx["from_song_id"] == trans.from_song_id
    assert "gap_bars" in ctx


def test_measure_region(project_bundle):
    from midiweaver.project.store import get_project

    store = get_project(str(project_bundle))
    result = measure_region(store.timeline, start_bar=0, end_bar=4)
    assert "note_count" in result
