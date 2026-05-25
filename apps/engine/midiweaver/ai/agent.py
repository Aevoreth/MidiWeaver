from __future__ import annotations

import json
from typing import Any

from midiweaver.ai.openai_http import post_chat_completion
from midiweaver.ai.tool_compact import compact_plan_for_prompt, compact_tool_result, trim_conversation
from midiweaver.ai.tools import AgentSessionStore, ToolExecutor, agent_session_store, plan_store, tool_schemas
from midiweaver.models import AgentStepLog, ArrangementPlan, Operation, PlanStep
from midiweaver.ops.executor import OpExecutor


class ArrangementAgent:
    """Tool-calling agent with step_commit revisions."""

    SYSTEM_PROMPT = """You are MidiWeaver's arrangement agent. Execute transition edits using tools.
Always inspect before editing: get_timeline_summary, get_transition_context, get_loop_candidates, query_notes.
Use apply_op to commit one operation at a time. Each apply_op creates an undoable revision.

Transition workflow when gap_bars is 0:
1) insert_master_gap — after_song_id = outgoing song, bars = transition length (e.g. 16–31)
2) loop_region — use loop_region_params from get_loop_candidates (song-local bars, NOT master bars)
3) copy_notes — layer drums using copy_notes_params from get_loop_candidates (master bars)
4) tempo_ramp — start_bar/end_bar from transition context, duration_bars for ramp length

Param spaces (critical):
- loop_region source_start_bar/source_end_bar = song-local (0 = trimmed song start)
- copy_notes source_* = master timeline bars or ticks
- insert_master_gap creates space; shift_song moves notes within one song (does not create gap)

Shortcuts: loop_region use_last_bars:true, copy_notes master_source_start_bar, shift_song delta_bars.
If apply_op returns resolved_params, fix params and retry. Call measure_region to verify after edits.
When done, respond with a brief summary and stop calling tools."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        max_steps: int = 25,
        session_store: AgentSessionStore | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.max_steps = max_steps
        self.session_store = session_store or agent_session_store
        self.executor = OpExecutor()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    async def run(
        self,
        *,
        store: Any,
        prompt: str,
        selection: dict[str, Any],
        session_id: str | None = None,
        plan_id: str | None = None,
        mock: bool = False,
    ) -> dict[str, Any]:
        if mock or not self.api_key:
            return await self._mock_run(store, prompt, plan_id, session_id, selection)

        tool_executor = ToolExecutor(store, self.executor, selection=selection)
        plan = plan_store.get(plan_id) if plan_id else None
        context = self._build_context(selection, plan)

        if session_id:
            session = self.session_store.get(session_id)
            if not session:
                raise ValueError(f"Session not found: {session_id}")
        else:
            session = {
                "status": "running",
                "messages": [],
                "steps": [],
                "plan_id": plan_id,
            }
            session_id = self.session_store.create(session)

        user_content = f"{context}\n\nUser request: {prompt}"
        if plan:
            user_content += f"\n\nArrangement plan to execute:\n{compact_plan_for_prompt(plan)}"

        convo: list[dict[str, Any]] = trim_conversation(
            [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                *session.get("messages", []),
                {"role": "user", "content": user_content},
            ]
        )

        tools = tool_schemas(include_write=True)
        steps: list[dict[str, Any]] = list(session.get("steps", []))

        for step_idx in range(self.max_steps):
            if self.session_store.is_cancelled(session_id):
                session["status"] = "cancelled"
                break

            data = await post_chat_completion(
                base_url=self.base_url,
                api_key=self.api_key,
                model=self.model,
                messages=trim_conversation(convo),
                tools=True,
                tool_defs=tools,
            )
            msg = data["choices"][0]["message"]

            if not msg.get("tool_calls"):
                convo.append(msg)
                session["status"] = "done"
                session["messages"] = trim_conversation([m for m in convo if m["role"] != "system"])
                session["steps"] = steps
                session["summary"] = msg.get("content", "")
                self.session_store.update(session_id, session)
                return {
                    "session_id": session_id,
                    "status": "done",
                    "summary": msg.get("content", ""),
                    "steps": steps,
                    "timeline": store.timeline.model_dump(),
                }

            convo.append(msg)
            for tc in msg["tool_calls"]:
                fn = tc["function"]
                name = fn["name"]
                args = json.loads(fn.get("arguments") or "{}")
                result = tool_executor.execute(name, args)
                step_log = AgentStepLog(
                    step_index=len(steps),
                    tool_name=name,
                    tool_args=args,
                    result=result if "error" not in result else {"error": result["error"]},
                    revision_id=result.get("revision_id"),
                    error=result.get("error") if isinstance(result.get("error"), str) else None,
                )
                if isinstance(result.get("error"), list):
                    step_log.error = "; ".join(result["error"])
                steps.append(step_log.model_dump())
                llm_result = compact_tool_result(name, result)
                convo.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(llm_result),
                    }
                )

        session["status"] = session.get("status", "running")
        if session["status"] == "running":
            session["status"] = "max_steps"
        session["messages"] = trim_conversation([m for m in convo if m["role"] != "system"])
        session["steps"] = steps
        self.session_store.update(session_id, session)
        return {
            "session_id": session_id,
            "status": session["status"],
            "steps": steps,
            "timeline": store.timeline.model_dump(),
        }

    def _build_context(self, selection: dict[str, Any], plan: ArrangementPlan | None) -> str:
        parts = [f"Selection: {json.dumps(selection)}"]
        if plan:
            parts.append(f"Plan summary: {plan.plan_summary}")
        return "\n".join(parts)

    async def _mock_run(
        self,
        store: Any,
        prompt: str,
        plan_id: str | None,
        session_id: str | None,
        selection: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        tool_executor = ToolExecutor(store, self.executor, selection=selection or {})
        steps: list[dict[str, Any]] = []
        seg = store.timeline.segments[0] if store.timeline.segments else None
        if seg:
            op = Operation(
                op_type="extend_drums",
                params={"song_id": seg.id, "bars": 1},
                description="Mock agent: extend drums 1 bar",
            )
            result = tool_executor.execute(
                "apply_op",
                {"op_type": op.op_type, "params": op.params, "description": op.description},
            )
            steps.append(
                AgentStepLog(
                    step_index=0,
                    tool_name="apply_op",
                    tool_args=op.model_dump(),
                    result=result,
                    revision_id=result.get("revision_id"),
                ).model_dump()
            )

        session = {
            "status": "done",
            "messages": [],
            "steps": steps,
            "plan_id": plan_id,
            "summary": f"Mock agent completed. Prompt: {prompt[:120]}",
        }
        sid = session_id or self.session_store.create(session)
        self.session_store.update(sid, session)
        return {
            "session_id": sid,
            "status": "done",
            "summary": session["summary"],
            "steps": steps,
            "mode": "mock",
            "timeline": store.timeline.model_dump(),
        }


class ArrangementPlanner:
    """Plan mode: inspect then emit ArrangementPlan."""

    SYSTEM_PROMPT = """You are MidiWeaver's arrangement planner. Return ONLY valid JSON for ArrangementPlan:
{ "plan_summary": "...", "steps": [ { "id": "step_1", "description": "...", "intent": "...",
  "suggested_tool": "loop_region", "suggested_params": {}, "verify": {} } ],
  "tempo_options": [ { "label": "...", "policy": "linear_ramp", "duration_bars": 8,
  "start_bpm": 120, "end_bpm": 140 } ], "constraints_applied": {} }
Use inspect context provided. Do not output raw MIDI."""

    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    async def plan(
        self,
        payload: dict[str, Any],
        tool_executor: ToolExecutor,
        mock: bool = False,
    ) -> ArrangementPlan:
        if mock or not self.api_key:
            return self._mock_plan(payload)

        summary = tool_executor.execute("get_timeline_summary", {})
        inspect = json.dumps({"payload": payload, "timeline": summary})

        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": inspect + "\n\nRespond with ArrangementPlan JSON only."},
        ]
        data = await post_chat_completion(
            base_url=self.base_url,
            api_key=self.api_key,
            model=self.model,
            messages=messages,
            response_format={"type": "json_object"},
            timeout=90.0,
        )
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        return ArrangementPlan(**parsed)

    def _mock_plan(self, payload: dict[str, Any]) -> ArrangementPlan:
        from midiweaver.models import TempoOption

        songs = payload.get("global", {}).get("songs", [])
        start_bpm = songs[0]["bpm_range"][0] if songs else 120.0
        end_bpm = songs[1]["bpm_range"][0] if len(songs) > 1 else start_bpm
        bar_range = payload.get("selection", {}).get("master_bar_range", [0, 4])
        song_id = songs[0]["id"] if songs else "song_1"

        return ArrangementPlan(
            plan_summary="Mock arrangement: loop outro, insert gap, drum bridge, tempo ramp",
            steps=[
                PlanStep(
                    id="step_1",
                    description="Loop last 4 bars of Song 1 into a 16-bar outro",
                    intent="loop_outro",
                    suggested_tool="loop_region",
                    suggested_params={
                        "song_id": song_id,
                        "source_start_bar": max(0, bar_range[1] - 4),
                        "source_end_bar": bar_range[1],
                        "target_total_bars": 16,
                    },
                    verify={"min_bars_added": 12},
                ),
                PlanStep(
                    id="step_2",
                    description="Insert 8-bar gap before Song 2",
                    intent="insert_gap",
                    suggested_tool="insert_master_gap",
                    suggested_params={"after_song_id": song_id, "bars": 8},
                ),
                PlanStep(
                    id="step_3",
                    description="Apply tempo ramp across transition",
                    intent="tempo_ramp",
                    suggested_tool="tempo_ramp",
                    suggested_params={"duration_bars": 8},
                ),
            ],
            tempo_options=[
                TempoOption(
                    label="Linear ramp",
                    policy="linear_ramp",
                    duration_bars=bar_range[1] - bar_range[0],
                    start_bpm=start_bpm,
                    end_bpm=end_bpm,
                )
            ],
            constraints_applied=payload.get("constraints", {}),
        )
