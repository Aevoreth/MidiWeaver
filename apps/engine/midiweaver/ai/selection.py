from __future__ import annotations

from typing import Any


def normalize_selection(selection: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize UI selection payload (track_ids -> tracks, defaults)."""
    sel = dict(selection or {})
    track_ids = sel.get("track_ids") or sel.get("tracks") or []
    if track_ids and not sel.get("tracks"):
        sel["tracks"] = list(track_ids)
    sel.setdefault("scope", "transition")
    sel.setdefault("master_bar_range", [0.0, 4.0])
    return sel
