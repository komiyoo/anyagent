from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx
import jsonschema

from anyagent.tool_runtime.models import ToolDefinition
from anyagent.tool_runtime.registry import ToolRegistry

from .idempotency import ToolResult
from .policy import is_allowed_by_policy


class Router:
    def __init__(self, registry: ToolRegistry, *, allow_sandbox: bool, output_max_bytes: int) -> None:
        self._registry = registry
        self._allow_sandbox = allow_sandbox
        self._output_max_bytes = output_max_bytes

    @staticmethod
    def _parse_arguments(arguments_json: Any) -> dict[str, Any]:
        if isinstance(arguments_json, dict):
            return arguments_json
        if isinstance(arguments_json, str):
            obj = json.loads(arguments_json)
            if not isinstance(obj, dict):
                raise ValueError("arguments_json must decode to an object")
            return obj
        raise ValueError("arguments_json must be string or object")

    @staticmethod
    def _validate_args(schema: dict[str, Any], args: dict[str, Any]) -> None:
        jsonschema.validate(instance=args, schema=schema)

    def _truncate(self, s: str) -> tuple[str, bool]:
        b = s.encode("utf-8", errors="replace")
        if len(b) <= self._output_max_bytes:
            return s, False
        cut = b[: self._output_max_bytes]
        return cut.decode("utf-8", errors="replace"), True

    async def execute(
        self,
        *,
        tool_name: str,
        arguments_json: Any,
        context: dict[str, Any],
        deadline_ms: int | None = None,
    ) -> ToolResult:
        rt = self._registry.get_tool(tool_name)
        if rt is None:
            return ToolResult(
                status="error",
                output=None,
                error={
                    "type": "tool_not_found",
                    "code": "tool_not_found",
                    "message": f"Unknown tool: {tool_name}",
                    "retryable": False,
                },
                meta={"duration_ms": 0, "output_truncated": False, "audit_ref": None},
            )

        td: ToolDefinition = rt.definition
        allowed, reason = is_allowed_by_policy(
            tool_name=td.name,
            category=td.category,
            context=context,
            allow_sandbox=self._allow_sandbox,
        )
        if not allowed:
            return ToolResult(
                status="error",
                output=None,
                error={
                    "type": "tool_authorization_error",
                    "code": reason,
                    "message": "tool is not allowed by policy",
                    "retryable": False,
                },
                meta={"duration_ms": 0, "output_truncated": False, "audit_ref": None},
            )

        started = time.time()
        try:
            args = self._parse_arguments(arguments_json)
            self._validate_args(td.parameters, args)
            if deadline_ms is not None:
                async with asyncio.timeout(deadline_ms / 1000.0):
                    output = await rt.handler(args, context)
            else:
                output = await rt.handler(args, context)
            out, truncated = self._truncate(output)
            return ToolResult(
                status="completed",
                output=out,
                error=None,
                meta={
                    "duration_ms": int((time.time() - started) * 1000),
                    "output_truncated": truncated,
                    "audit_ref": None,
                },
            )
        except TimeoutError:
            return ToolResult(
                status="error",
                output=None,
                error={
                    "type": "tool_execution_error",
                    "code": "deadline_exceeded",
                    "message": "tool execution exceeded deadline_ms",
                    "retryable": True,
                },
                meta={"duration_ms": int((time.time() - started) * 1000), "audit_ref": None, "output_truncated": False},
            )
        except (json.JSONDecodeError, ValueError) as e:
            return ToolResult(
                status="error",
                output=None,
                error={
                    "type": "tool_input_error",
                    "code": "invalid_arguments_json",
                    "message": str(e),
                    "retryable": False,
                },
                meta={"duration_ms": int((time.time() - started) * 1000), "audit_ref": None, "output_truncated": False},
            )
        except jsonschema.ValidationError as e:
            return ToolResult(
                status="error",
                output=None,
                error={
                    "type": "tool_input_error",
                    "code": "schema_validation_failed",
                    "message": str(e.message),
                    "retryable": False,
                },
                meta={"duration_ms": int((time.time() - started) * 1000), "audit_ref": None, "output_truncated": False},
            )
        except Exception as e:  # noqa: BLE001
            return ToolResult(
                status="error",
                output=None,
                error={
                    "type": "tool_execution_error",
                    "code": "exception",
                    "message": str(e),
                    "retryable": False,
                },
                meta={"duration_ms": int((time.time() - started) * 1000), "audit_ref": None, "output_truncated": False},
            )


async def register_builtin_core_tools(registry: ToolRegistry) -> None:
    """
    v0：内置 core.* 工具也必须走同一注册路径（registry 单一真源）。
    这里先提供最小可用的 core.web_fetch；core.web_search 需要外部搜索能力，后续再补。
    """

    async def web_fetch(args: dict[str, Any], context: dict[str, Any]) -> str:
        url = args["url"]
        timeout_ms = int(args.get("timeout_ms", 15000))

        # SSRF 基线：禁止访问本机与 link-local（v0 最小保护）
        if isinstance(url, str) and (
            url.startswith("http://127.")
            or url.startswith("http://localhost")
            or url.startswith("http://169.254.")
            or url.startswith("https://127.")
            or url.startswith("https://localhost")
        ):
            raise ValueError("forbidden url")

        async with httpx.AsyncClient(timeout=timeout_ms / 1000.0, follow_redirects=True) as client:
            r = await client.get(url, headers={"user-agent": "AnyAgent/0"})
            text = r.text
            # 输出为 JSON string，便于上层处理
            return json.dumps(
                {
                    "status": r.status_code,
                    "headers": dict(list(r.headers.items())[:50]),
                    "text": text,
                    "url": str(r.url),
                },
                ensure_ascii=False,
            )

    registry.register_tool(
        tool=ToolDefinition(
            name="core.web_fetch",
            description="Fetch a URL and return text content (SSRF-protected, limited).",
            category="core",
            parameters={
                "type": "object",
                "additionalProperties": False,
                "required": ["url"],
                "properties": {
                    "url": {"type": "string"},
                    "timeout_ms": {"type": "integer", "minimum": 1000, "maximum": 60000},
                },
            },
        ),
        handler=web_fetch,
    )
