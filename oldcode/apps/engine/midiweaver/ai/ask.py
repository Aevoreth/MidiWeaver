from __future__ import annotations

import json
from typing import Any

import httpx

from midiweaver.ai.openai_http import post_chat_completion
from midiweaver.ai.tool_compact import compact_tool_result, trim_conversation
from midiweaver.ai.tools import ToolExecutor, tool_schemas
from midiweaver.models import Operation


class AskAssistant:
    """Read-only chat with inspect tools."""

    SYSTEM_PROMPT = """You are MidiWeaver's arrangement assistant in Ask mode.
Use tools to inspect the project timeline, transitions, and MIDI notes.
Answer clearly with bar numbers and song names. Do NOT modify the project.
When the user asks about a region, call query_notes or analyze_region first."""

    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tool_executor: ToolExecutor,
        mock: bool = False,
        max_tool_rounds: int = 5,
    ) -> dict[str, Any]:
        if mock or not self.api_key:
            return self._mock_response(messages, tool_executor)

        tools = tool_schemas(include_write=False)
        convo = trim_conversation([{"role": "system", "content": self.SYSTEM_PROMPT}, *messages])
        tool_calls_made: list[dict[str, Any]] = []

        for _ in range(max_tool_rounds):
            data = await post_chat_completion(
                base_url=self.base_url,
                api_key=self.api_key,
                model=self.model,
                messages=trim_conversation(convo),
                tools=True,
                tool_defs=tools,
                timeout=90.0,
            )
            msg = data["choices"][0]["message"]

            if not msg.get("tool_calls"):
                return {
                    "message": msg.get("content", ""),
                    "tool_calls": tool_calls_made,
                    "mode": "live",
                }

            convo.append(msg)
            for tc in msg["tool_calls"]:
                fn = tc["function"]
                name = fn["name"]
                args = json.loads(fn.get("arguments") or "{}")
                result = tool_executor.execute(name, args)
                tool_calls_made.append({"name": name, "args": args, "result": result})
                llm_result = compact_tool_result(name, result)
                convo.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(llm_result),
                    }
                )

        return {
            "message": convo[-1].get("content", "Reached tool call limit."),
            "tool_calls": tool_calls_made,
            "mode": "live",
        }

    def _mock_response(
        self, messages: list[dict[str, Any]], tool_executor: ToolExecutor
    ) -> dict[str, Any]:
        summary = tool_executor.execute("get_timeline_summary", {})
        song_count = len(summary.get("songs", []))
        last_user = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        return {
            "message": (
                f"Mock Ask response. Project has {song_count} song(s). "
                f"You asked: {last_user[:200]}"
            ),
            "tool_calls": [{"name": "get_timeline_summary", "args": {}, "result": summary}],
            "mode": "mock",
        }
