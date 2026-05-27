from __future__ import annotations

from typing import Any

import httpx

# Models that reject tools/system prompts on /chat/completions.
_NO_TOOLS_PREFIXES = ("o1", "o3", "gpt-5-pro")


def validate_chat_model(model: str, *, tools: bool = False) -> None:
    name = (model or "").strip()
    if not name:
        raise ValueError("AI model is not configured. Set ai_model in Settings.")
    lower = name.lower()
    if tools:
        for prefix in _NO_TOOLS_PREFIXES:
            if lower.startswith(prefix):
                raise ValueError(
                    f"Model '{name}' does not support tool calling on Chat Completions. "
                    "Use gpt-4o-mini or gpt-4o for Agent/Ask mode."
                )


def chat_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def parse_api_error(response: httpx.Response) -> str:
    try:
        data = response.json()
        err = data.get("error")
        if isinstance(err, dict):
            message = str(err.get("message") or "").strip()
            param = err.get("param")
            code = err.get("code")
            typ = err.get("type")
            parts = [message] if message else []
            if typ:
                parts.append(f"type={typ}")
            if param:
                parts.append(f"param={param}")
            if code:
                parts.append(f"code={code}")
            if parts:
                return " | ".join(parts)
    except Exception:
        pass
    text = response.text.strip()
    return text[:500] if text else (response.reason_phrase or "Unknown error")


def format_http_status_error(exc: httpx.HTTPStatusError) -> str:
    status = exc.response.status_code
    detail = parse_api_error(exc.response)
    if status == 401:
        return f"AI API authentication failed (401). {detail}"
    if status == 404:
        return f"AI API endpoint not found (404). {detail}"
    if status == 429:
        return f"AI API rate limit exceeded (429). {detail}"
    return f"AI API request failed ({status}): {detail}"


def sanitize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize stored messages before sending them back to the API."""
    cleaned: list[dict[str, Any]] = []
    for raw in messages:
        msg = dict(raw)
        if msg.get("role") == "assistant" and msg.get("tool_calls") and msg.get("content") is None:
            msg["content"] = None
        cleaned.append(msg)
    return cleaned


async def post_chat_completion(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    tools: bool = False,
    tool_defs: list[dict[str, Any]] | None = None,
    response_format: dict[str, Any] | None = None,
    max_tokens: int | None = None,
    timeout: float = 120.0,
) -> dict[str, Any]:
    validate_chat_model(model, tools=tools)
    payload: dict[str, Any] = {
        "model": model.strip(),
        "messages": sanitize_messages(messages),
    }
    if tools:
        if not tool_defs:
            raise ValueError("tools=True requires tool_defs")
        payload["tools"] = tool_defs
    if response_format:
        payload["response_format"] = response_format
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers=chat_headers(api_key),
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.TimeoutException as e:
        raise ValueError(f"AI API timed out connecting to {base_url}") from e
    except httpx.ConnectError as e:
        raise ValueError(f"Could not connect to AI API at {base_url}: {e}") from e
    except httpx.HTTPStatusError as e:
        raise ValueError(format_http_status_error(e)) from e
