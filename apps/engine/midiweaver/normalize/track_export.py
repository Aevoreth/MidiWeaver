"""Resolve per-song tracks into export merge groups."""

from __future__ import annotations

from typing import Any


def song_scoped_track_id(song_id: str, track_id: str) -> str:
    return f"{song_id}:{track_id}"


def build_mapping_lookup(track_mapping: list[Any] | None) -> dict[tuple[str, str], dict[str, Any]]:
    """Map (song_id, track_id) -> mapping entry dict."""
    lookup: dict[tuple[str, str], dict[str, Any]] = {}
    if not track_mapping:
        return lookup
    for entry in track_mapping:
        data = entry.model_dump() if hasattr(entry, "model_dump") else dict(entry)
        for song_id, track_id in (data.get("song_track_ids") or {}).items():
            if track_id:
                lookup[(song_id, track_id)] = data
    return lookup


def resolve_note_export_track(
    note: dict[str, Any],
    mapping_lookup: dict[tuple[str, str], dict[str, Any]],
    song_names: dict[str, str] | None = None,
) -> tuple[str, str, bool]:
    """Return (export_group_id, display_name, is_mapped)."""
    song_id = note.get("song_id", "")
    track_id = note.get("track_id", "")
    track_name = note.get("track_name") or track_id
    song_names = song_names or {}

    entry = mapping_lookup.get((song_id, track_id))
    if entry:
        group_id = entry.get("master_track_id") or entry.get("role", "").lower().replace(" ", "_")
        display = entry.get("role") or group_id
        return group_id, display, True

    group_id = song_scoped_track_id(song_id, track_id)
    song_label = song_names.get(song_id, song_id)
    return group_id, f"{song_label} / {track_name}", False


def apply_export_track_mapping(
    notes: list[dict[str, Any]],
    track_mapping: list[Any] | None,
    song_names: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Annotate notes with export grouping; return unmapped song-scoped track ids."""
    mapping_lookup = build_mapping_lookup(track_mapping)
    unmapped: set[str] = set()
    result: list[dict[str, Any]] = []

    for note in notes:
        group_id, display, is_mapped = resolve_note_export_track(note, mapping_lookup, song_names)
        if not is_mapped:
            unmapped.add(group_id)
        result.append(
            {
                **note,
                "export_group_id": group_id,
                "export_track_name": display,
            }
        )

    return result, sorted(unmapped)
