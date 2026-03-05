from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any
from uuid import uuid4

import httpx
import jsonschema

from anyagent.tool_runtime.models import ToolDefinition
from anyagent.tool_runtime.registry import ToolRegistry
from anyagent.protocol.tool_runtime import AuthRef
from anyagent.protocol.credential_vault import CredentialScope

from .idempotency import ToolResult
from .policy import is_allowed_by_policy
from .credential_store import CredentialStore


logger = logging.getLogger("anyagent.tool_runtime")


class Router:
    def __init__(
        self,
        registry: ToolRegistry,
        *,
        allow_sandbox: bool,
        output_max_bytes: int,
        credential_store: CredentialStore,
    ) -> None:
        self._registry = registry
        self._allow_sandbox = allow_sandbox
        self._output_max_bytes = output_max_bytes
        self._credential_store = credential_store

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
        agent_id: str | None = None,
        deadline_ms: int | None = None,
    ) -> ToolResult:
        audit_ref = f"aud_{uuid4().hex}"
        if agent_id is not None:
            # Do not trust caller-provided agent_id; always use server-side binding.
            context = {**context, "agent_id": agent_id}
        context = {**context, "_audit_ref": audit_ref}
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
                meta={"duration_ms": 0, "output_truncated": False, "audit_ref": audit_ref},
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
                meta={"duration_ms": 0, "output_truncated": False, "audit_ref": audit_ref},
            )

        creds_err, enriched_context = await self._maybe_inject_credentials(
            tool_definition=td,
            context=context,
            agent_id=agent_id,
            audit_ref=audit_ref,
        )
        if creds_err is not None:
            return creds_err

        started = time.time()
        try:
            args = self._parse_arguments(arguments_json)
            self._validate_args(td.parameters, args)
            if deadline_ms is not None:
                async with asyncio.timeout(deadline_ms / 1000.0):
                    output = await rt.handler(args, enriched_context)
            else:
                output = await rt.handler(args, enriched_context)
            out, truncated = self._truncate(output)
            return ToolResult(
                status="completed",
                output=out,
                error=None,
                meta={
                    "duration_ms": int((time.time() - started) * 1000),
                    "output_truncated": truncated,
                    "audit_ref": audit_ref,
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
                meta={
                    "duration_ms": int((time.time() - started) * 1000),
                    "audit_ref": audit_ref,
                    "output_truncated": False,
                },
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
                meta={
                    "duration_ms": int((time.time() - started) * 1000),
                    "audit_ref": audit_ref,
                    "output_truncated": False,
                },
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
                meta={
                    "duration_ms": int((time.time() - started) * 1000),
                    "audit_ref": audit_ref,
                    "output_truncated": False,
                },
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
                meta={
                    "duration_ms": int((time.time() - started) * 1000),
                    "audit_ref": audit_ref,
                    "output_truncated": False,
                },
            )

    async def _maybe_inject_credentials(
        self,
        *,
        tool_definition: ToolDefinition,
        context: dict[str, Any],
        agent_id: str | None,
        audit_ref: str,
    ) -> tuple[ToolResult | None, dict[str, Any]]:
        if not tool_definition.credentials:
            return None, context

        auth_ref_ref = _extract_auth_ref_ref(context)
        resolved: dict[str, str] = {}

        for cred_spec in tool_definition.credentials:
            ref = AuthRef(kind=cred_spec.ref_kind, ref=auth_ref_ref)
            value = await self._credential_store.resolve(ref, scope_context={"agent_id": agent_id})
            if value is None and cred_spec.required:
                return (
                    ToolResult(
                        status="error",
                        output=None,
                        error={
                            "type": "tool_authorization_error",
                            "code": "credential_not_found",
                            "message": f"required credential kind={cred_spec.ref_kind} not configured",
                            "retryable": False,
                        },
                        meta={"duration_ms": 0, "output_truncated": False, "audit_ref": audit_ref},
                    ),
                    context,
                )
            if value is None:
                continue
            formatted = cred_spec.format.replace("{value}", value)
            resolved[cred_spec.injection_target] = formatted

        if not resolved:
            return None, context
        return None, {**context, "_credentials": resolved}


def _extract_auth_ref_ref(context: dict[str, Any]) -> str | None:
    auth_ref = context.get("auth_ref")
    if isinstance(auth_ref, dict):
        ref = auth_ref.get("ref")
    else:
        ref = None
    if not isinstance(ref, str) or not ref.strip():
        return None
    return ref.strip()


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
            r = await client.get(url, headers={"user-agent": "anyagent/0"})
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


async def register_privileged_core_tools(*, registry: ToolRegistry, credential_store: CredentialStore) -> None:
    """
    Register privileged core tools that require explicit allowlist in policy.

    These tools are dangerous by nature (write-only credential ops) and must never be
    enabled by default. Policy enforcement is handled in runtime/policy.py.
    """

    async def credential_set(args: dict[str, Any], context: dict[str, Any]) -> str:
        credential_id = args["credential_id"]
        kind = args["kind"]
        value = args["value"]

        scope_raw = args.get("scope")
        agent_id = context.get("agent_id") if isinstance(context.get("agent_id"), str) else None
        if scope_raw is None:
            if agent_id:
                scope = CredentialScope(level="agent", agent_id=agent_id)
            else:
                scope = CredentialScope(level="global")
        else:
            scope = CredentialScope.model_validate(scope_raw)

        metadata = args.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise ValueError("metadata must be an object")

        await credential_store.set(
            credential_id=str(credential_id).strip(),
            kind=str(kind).strip(),
            value=str(value),
            scope=scope,
            metadata=dict(metadata),
        )

        logger.info(
            "credential_agent.set",
            extra={
                "audit_ref": context.get("_audit_ref"),
                "actor": f"agent:{agent_id}" if agent_id else "agent:unknown",
                "operation": "set",
                "credential_id": str(credential_id).strip(),
                "kind": str(kind).strip(),
                "scope_level": scope.level,
                "scope_agent_id": scope.agent_id,
            },
        )

        return json.dumps(
            {
                "ok": True,
                "credential_id": str(credential_id).strip(),
                "kind": str(kind).strip(),
                "scope": scope.model_dump(exclude_none=True),
                "metadata": dict(metadata),
            },
            ensure_ascii=False,
        )

    registry.register_tool(
        tool=ToolDefinition(
            name="admin.credential_set",
            description="Privileged: write-only set credential (no get). Requires explicit allowlist.",
            category="core",
            parameters={
                "type": "object",
                "additionalProperties": False,
                "required": ["credential_id", "kind", "value"],
                "properties": {
                    "credential_id": {"type": "string", "minLength": 1},
                    "kind": {"type": "string", "minLength": 1},
                    "value": {"type": "string", "minLength": 1},
                    "scope": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["level"],
                        "properties": {
                            "level": {"type": "string", "enum": ["global", "agent"]},
                            "agent_id": {"type": "string"},
                        },
                    },
                    "metadata": {"type": "object"},
                },
            },
        ),
        handler=credential_set,
    )
