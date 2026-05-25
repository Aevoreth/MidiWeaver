from __future__ import annotations

import time
import uuid
from typing import Any

from midiweaver.models import ArrangementPlan, Operation
from midiweaver.ops.executor import OpExecutor
from midiweaver.project.store import ProjectStore
from midiweaver.query.context import (
    analyze_region,
    get_loop_candidates,
    get_timeline_summary,
    get_transition_context,
    measure_region,
    query_notes,
)

READ_TOOLS = {
    "get_timeline_summary",
    "get_transition_context",
    "query_notes",
    "analyze_region",
    "get_loop_candidates",
    "dry_run_ops",
    "measure_region",
}

WRITE_TOOLS = {"apply_op"}

ALL_TOOLS = READ_TOOLS | WRITE_TOOLS


class PlanStore:
    """In-memory arrangement plan storage (~30 min TTL)."""

    def __init__(self, ttl_seconds: int = 1800) -> None:
        self._plans: dict[str, tuple[float, ArrangementPlan]] = {}
        self._ttl = ttl_seconds

    def put(self, plan: ArrangementPlan) -> str:
        plan_id = str(uuid.uuid4())
        self._plans[plan_id] = (time.time(), plan)
        self._purge()
        return plan_id

    def get(self, plan_id: str) -> ArrangementPlan | None:
        self._purge()
        entry = self._plans.get(plan_id)
        if not entry:
            return None
        return entry[1]

    def _purge(self) -> None:
        now = time.time()
        expired = [k for k, (ts, _) in self._plans.items() if now - ts > self._ttl]
        for k in expired:
            del self._plans[k]


class AgentSessionStore:
    """In-memory agent session storage."""

    def __init__(self, ttl_seconds: int = 3600) -> None:
        self._sessions: dict[str, tuple[float, dict[str, Any]]] = {}
        self._cancelled: set[str] = set()
        self._ttl = ttl_seconds

    def create(self, session: dict[str, Any]) -> str:
        sid = str(uuid.uuid4())
        self._sessions[sid] = (time.time(), session)
        return sid

    def get(self, session_id: str) -> dict[str, Any] | None:
        self._purge()
        entry = self._sessions.get(session_id)
        return entry[1] if entry else None

    def update(self, session_id: str, session: dict[str, Any]) -> None:
        self._sessions[session_id] = (time.time(), session)

    def cancel(self, session_id: str) -> None:
        self._cancelled.add(session_id)

    def is_cancelled(self, session_id: str) -> bool:
        return session_id in self._cancelled

    def _purge(self) -> None:
        now = time.time()
        expired = [k for k, (ts, _) in self._sessions.items() if now - ts > self._ttl]
        for k in expired:
            del self._sessions[k]
            self._cancelled.discard(k)


plan_store = PlanStore()
agent_session_store = AgentSessionStore()


def tool_schemas(include_write: bool = True) -> list[dict[str, Any]]:
    schemas: list[dict[str, Any]] = [
        {
            "type": "function",
            "function": {
                "name": "get_timeline_summary",
                "description": "Get songs, transitions, track mapping, and tempo events.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_transition_context",
                "description": "Get mix in/out, gap size, and tick ranges for a transition.",
                "parameters": {
                    "type": "object",
                    "properties": {"transition_id": {"type": "string"}},
                    "required": ["transition_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "query_notes",
                "description": "Query notes in a master bar or tick range (paginated, max 500).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "start_bar": {"type": "number"},
                        "end_bar": {"type": "number"},
                        "start_tick": {"type": "integer"},
                        "end_tick": {"type": "integer"},
                        "song_id": {"type": "string"},
                        "track_id": {"type": "string"},
                        "limit": {"type": "integer"},
                        "offset": {"type": "integer"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "analyze_region",
                "description": "Per-bar note density and pitch histogram in a bar range.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "start_bar": {"type": "number"},
                        "end_bar": {"type": "number"},
                    },
                    "required": ["start_bar", "end_bar"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_loop_candidates",
                "description": "Loop boundaries and last-bar region for a song.",
                "parameters": {
                    "type": "object",
                    "properties": {"song_id": {"type": "string"}},
                    "required": ["song_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "dry_run_ops",
                "description": "Simulate ops and return diff without committing.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "ops": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "op_type": {"type": "string"},
                                    "params": {"type": "object"},
                                    "description": {"type": "string"},
                                },
                                "required": ["op_type", "params"],
                            },
                        }
                    },
                    "required": ["ops"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "measure_region",
                "description": "Count notes and measure span/gap after edits.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "start_bar": {"type": "number"},
                        "end_bar": {"type": "number"},
                        "song_id": {"type": "string"},
                    },
                },
            },
        },
    ]
    if include_write:
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": "apply_op",
                    "description": "Apply a single validated operation (commits as one revision).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "op_type": {"type": "string"},
                            "params": {"type": "object"},
                            "description": {"type": "string"},
                        },
                        "required": ["op_type", "params"],
                    },
                },
            }
        )
    return schemas


class ToolExecutor:
    def __init__(self, store: ProjectStore, executor: OpExecutor | None = None) -> None:
        self.store = store
        self.executor = executor or OpExecutor()
        import json
        from midiweaver.models import ProjectMetadata

        meta = ProjectMetadata(**json.loads(store.project_json.read_text(encoding="utf-8")))
        self.track_mapping = meta.track_mapping

    def execute(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        timeline = self.store.timeline
        if name == "get_timeline_summary":
            return get_timeline_summary(timeline, self.track_mapping)
        if name == "get_transition_context":
            return get_transition_context(timeline, args["transition_id"])
        if name == "query_notes":
            return query_notes(timeline, **{k: v for k, v in args.items() if v is not None})
        if name == "analyze_region":
            return analyze_region(timeline, [args["start_bar"], args["end_bar"]])
        if name == "get_loop_candidates":
            return get_loop_candidates(timeline, args["song_id"])
        if name == "measure_region":
            return measure_region(timeline, **{k: v for k, v in args.items() if v is not None})
        if name == "dry_run_ops":
            ops = [Operation(**op) for op in args.get("ops", [])]
            errors: list[str] = []
            for op in ops:
                errors.extend(self.executor.validate_op(op))
            if errors:
                return {"error": errors}
            ctx = self.store.get_context()
            diff = self.executor.dry_run(ctx, ops)
            return {"diff": diff.model_dump(), "valid": True}
        if name == "apply_op":
            op = Operation(
                op_type=args["op_type"],
                params=args.get("params", {}),
                description=args.get("description", ""),
            )
            errors = self.executor.validate_op(op)
            if errors:
                return {"error": errors}
            rev = self.store.apply_ops([op], label=op.description[:80] or f"Agent: {op.op_type}")
            return {
                "revision_id": rev.id,
                "diff": rev.diff.model_dump() if rev.diff else {},
                "timeline_total_bars": self.store.timeline.total_bars,
            }
        return {"error": f"Unknown tool: {name}"}
