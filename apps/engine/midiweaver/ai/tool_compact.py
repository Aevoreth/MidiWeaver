from __future__ import annotations

import json
from typing import Any

MAX_TOOL_RESULT_CHARS = 16_000
MAX_NOTES_IN_TOOL_RESPONSE = 24
MAX_DIFF_SAMPLE = 5
MAX_DENSITY_BARS = 32
MAX_TEMPO_EVENTS = 8


def _estimate_chars(value: Any) -> int:
    return len(json.dumps(value, default=str))


def compact_tool_result(tool_name: str, result: dict[str, Any]) -> dict[str, Any]:
    """Shrink tool output before sending it back to the LLM."""
    if result.get("error"):
        return result
    if tool_name in ("apply_op", "dry_run_ops"):
        compact = compact_diff_result(result)
    elif tool_name == "query_notes":
        compact = compact_query_notes(result)
    elif tool_name == "get_timeline_summary":
        compact = compact_timeline_summary(result)
    elif tool_name == "analyze_region":
        compact = compact_analyze_region(result)
    elif tool_name == "get_transition_context":
        compact = dict(result)
    elif tool_name == "get_loop_candidates":
        compact = dict(result)
        compact.pop("loop_boundaries", None)
    else:
        compact = dict(result)

    if _estimate_chars(compact) > MAX_TOOL_RESULT_CHARS:
        compact = {
            "truncated": True,
            "tool": tool_name,
            "summary": _summarize_compact(compact),
            "hint": "Use narrower ranges or inspect one transition/song at a time.",
        }
    return compact


def compact_diff_result(result: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in result.items() if k != "diff"}
    diff = result.get("diff") or {}
    added = diff.get("added_notes") or []
    removed = diff.get("removed_notes") or []
    moved = diff.get("moved_notes") or []
    out["diff"] = {
        "added_count": len(added),
        "removed_count": len(removed),
        "moved_count": len(moved),
        "added_sample": added[:MAX_DIFF_SAMPLE],
        "removed_sample": removed[:MAX_DIFF_SAMPLE],
        "moved_sample": moved[:MAX_DIFF_SAMPLE],
    }
    return out


def compact_query_notes(result: dict[str, Any]) -> dict[str, Any]:
    notes = result.get("notes") or []
    total = int(result.get("total", len(notes)))
    out = {k: v for k, v in result.items() if k != "notes"}
    out["notes"] = notes[:MAX_NOTES_IN_TOOL_RESPONSE]
    out["notes_returned"] = len(out["notes"])
    if total > len(out["notes"]):
        out["truncated"] = True
        out["hint"] = "Narrow start_bar/end_bar or filter by song_id/track_id."
    return out


def compact_timeline_summary(result: dict[str, Any]) -> dict[str, Any]:
    songs = []
    for song in result.get("songs") or []:
        songs.append(
            {
                "id": song.get("id"),
                "display_name": song.get("display_name"),
                "estimated_bpm": song.get("estimated_bpm"),
                "bar_count": song.get("bar_count"),
                "master_start_bar": song.get("master_start_bar"),
                "master_end_bar": song.get("master_end_bar"),
                "loop_boundary_count": len(song.get("loop_boundaries") or []),
                "tracks": [
                    {
                        "track_id": track.get("track_id"),
                        "name": track.get("name"),
                        "is_drum": track.get("is_drum"),
                        "note_count": track.get("note_count"),
                    }
                    for track in (song.get("track_summaries") or [])
                ],
            }
        )
    return {
        "master_ppq": result.get("master_ppq"),
        "total_ticks": result.get("total_ticks"),
        "total_bars": result.get("total_bars"),
        "songs": songs,
        "transitions": result.get("transitions") or [],
        "track_mapping": result.get("track_mapping") or [],
        "tempo_events": (result.get("tempo_events") or [])[-MAX_TEMPO_EVENTS:],
    }


def compact_analyze_region(result: dict[str, Any]) -> dict[str, Any]:
    density = result.get("density_per_bar") or []
    hist = result.get("pitch_histogram") or {}
    top_pitches = sorted(hist.items(), key=lambda kv: kv[1], reverse=True)[:12]
    return {
        "bar_range": result.get("bar_range"),
        "start_tick": result.get("start_tick"),
        "end_tick": result.get("end_tick"),
        "total_notes": result.get("total_notes"),
        "tracks": result.get("tracks"),
        "density_per_bar": density[:MAX_DENSITY_BARS],
        "density_bars_omitted": max(0, len(density) - MAX_DENSITY_BARS),
        "top_pitches": [{"pitch": int(k), "count": v} for k, v in top_pitches],
    }


def compact_plan_for_prompt(plan: Any) -> str:
    steps = []
    for step in plan.steps:
        steps.append(
            {
                "id": step.id,
                "description": step.description[:160],
                "tool": step.suggested_tool,
                "params": step.suggested_params,
            }
        )
    return json.dumps(
        {
            "plan_summary": plan.plan_summary,
            "steps": steps,
        },
        default=str,
    )


def trim_conversation(messages: list[dict[str, Any]], *, max_chars: int = 500_000) -> list[dict[str, Any]]:
    """Drop oldest non-system messages when the payload is still too large."""
    if _estimate_chars(messages) <= max_chars:
        return messages

    system_msgs = [m for m in messages if m.get("role") == "system"]
    other = [m for m in messages if m.get("role") != "system"]
    if not other:
        return messages

    kept = other[-12:]
    dropped = len(other) - len(kept)
    notice = {
        "role": "user",
        "content": (
            f"[Context trimmed: omitted {dropped} earlier message(s) to stay within model limits. "
            "Re-call inspect tools if you need fresh timeline details.]"
        ),
    }
    trimmed = [*system_msgs, notice, *kept]
    if _estimate_chars(trimmed) > max_chars and len(kept) > 4:
        kept = other[-4:]
        notice["content"] = (
            f"[Context heavily trimmed: omitted {len(other) - len(kept)} earlier message(s). "
            "Use get_timeline_summary / get_transition_context again.]"
        )
        trimmed = [*system_msgs, notice, *kept]
    return trimmed


def _summarize_compact(result: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in ("revision_id", "op_type", "valid", "total", "total_notes", "total_bars", "gap_bars"):
        if key in result:
            summary[key] = result[key]
    diff = result.get("diff")
    if isinstance(diff, dict):
        summary["diff"] = {
            k: diff.get(k)
            for k in ("added_count", "removed_count", "moved_count")
            if k in diff
        }
    return summary
