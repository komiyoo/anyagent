from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from anyagent.plugins.hooks import HookContext
from anyagent.tool_runtime.models import ToolDefinition


EVENTS: list[dict[str, Any]] = []


async def echo(args: dict[str, Any], context: dict[str, Any]) -> str:
    text = str(args.get("text", ""))
    return f"[lifecycle_echo] {text} ({context.get('agent_id')}/{context.get('session_key')})"


def _record(event: str, context: HookContext) -> None:
    payload = {
        "event": event,
        "agent_id": context.agent_id,
        "session_key": context.session_key,
        "response_id": context.response_id,
        "metadata": context.metadata or {},
    }
    EVENTS.append(payload)
    path = os.getenv("ANYAGENT_LIFECYCLE_ECHO_EVENTS_FILE")
    if path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def on_agent_start(context: HookContext) -> None:
    _record("on_agent_start", context)


def on_agent_end(context: HookContext) -> None:
    _record("on_agent_end", context)


def register(api: Any) -> None:
    if api.host_kind not in {"gateway", "tool_runtime"}:
        return
    api.registerTool(
        ToolDefinition(
            name="app.lifecycle_echo.echo",
            description="Echo text from the AnyAgent lifecycle reference plugin.",
            category="app",
            kind="command",
            parameters={
                "type": "object",
                "additionalProperties": False,
                "required": ["text"],
                "properties": {
                    "text": {"type": "string", "description": "Text to echo."}
                },
            },
        ),
        echo,
    )
