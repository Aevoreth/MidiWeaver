import json

import httpx
import pytest

from midiweaver.ai.openai_http import format_http_status_error, parse_api_error, validate_chat_model
from midiweaver.ai.tools import tool_schemas


def test_tool_schemas_have_additional_properties():
    for schema in tool_schemas(include_write=True):
        params = schema["function"]["parameters"]
        assert params["type"] == "object"
        assert "additionalProperties" in params


def test_validate_chat_model_rejects_o1_with_tools():
    with pytest.raises(ValueError, match="does not support tool calling"):
        validate_chat_model("o1-preview", tools=True)


def test_parse_api_error_extracts_message():
    response = httpx.Response(
        400,
        json={
            "error": {
                "message": "Invalid schema for function 'apply_op'",
                "type": "invalid_request_error",
                "param": "tools[8].function.parameters",
                "code": "invalid_function_parameters",
            }
        },
    )
    text = parse_api_error(response)
    assert "Invalid schema for function 'apply_op'" in text
    assert "param=tools[8].function.parameters" in text


def test_format_http_status_error():
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(
        400,
        request=request,
        json={"error": {"message": "you must provide a model parameter"}},
    )
    exc = httpx.HTTPStatusError("bad", request=request, response=response)
    msg = format_http_status_error(exc)
    assert "400" in msg
    assert "model parameter" in msg
