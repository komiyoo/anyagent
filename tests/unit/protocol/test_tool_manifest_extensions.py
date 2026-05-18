from anyagent.protocol.tool_manifest_extensions import (
    source_tool_name_for_model_name,
    strip_internal_tool_fields,
)


def test_strip_internal_fields_normalizes_model_tool_names():
    tools = [
        {
            "type": "function",
            "name": "core.web_fetch",
            "description": "Fetch a URL.",
            "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
            "strict": True,
            "x-anyagent-kind": "command",
        }
    ]

    assert strip_internal_tool_fields(tools) == [
        {
            "type": "function",
            "name": "core_web_fetch",
            "description": "Fetch a URL.",
            "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
            "strict": False,
        }
    ]


def test_source_tool_name_maps_model_tool_names_back_to_manifest_names():
    tools = [{"type": "function", "name": "mcp.amap.run"}]

    assert source_tool_name_for_model_name(tools, "mcp_amap_run") == "mcp.amap.run"
    assert source_tool_name_for_model_name(tools, "spawn_agent") == "spawn_agent"
