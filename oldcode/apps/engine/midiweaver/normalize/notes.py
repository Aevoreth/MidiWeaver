from __future__ import annotations

import uuid

from midiweaver.models import AnalysisSnapshot, MasterTimeline, NoteEvent


def ensure_note_id(note: NoteEvent) -> NoteEvent:
    if not note.note_id:
        return note.model_copy(update={"note_id": str(uuid.uuid4())})
    return note


def ensure_analysis_note_ids(analysis: AnalysisSnapshot) -> None:
    for track in analysis.tracks:
        track.notes = [ensure_note_id(n) for n in track.notes]


def ensure_timeline_note_ids(timeline: MasterTimeline) -> None:
    for seg in timeline.segments:
        if seg.analysis:
            ensure_analysis_note_ids(seg.analysis)
