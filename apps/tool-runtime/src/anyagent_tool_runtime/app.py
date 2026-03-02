from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from anyagent.plugins import load_plugins_from_roots
from anyagent.gateway.session import SessionBindingError
from anyagent.gateway.session import session_partition_key as build_session_partition_key
from anyagent.tool_runtime.models import ToolDefinition
from anyagent.tool_runtime.registry import ToolRegistry
from anyagent.tool_runtime.plugins import ToolRuntimePluginAPI

from .api_models import ExecuteRequest, ManifestDecision, ManifestRequest
from .auth import check_internal_auth
from .errors import tool_error
from .executors import Router, register_builtin_core_tools
from .idempotency import InMemoryIdempotencyStore, ToolResult
from .manifest import build_manifest
from .settings import Settings


logger = logging.getLogger("anyagent.tool_runtime")


def create_app(settings: Settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        registry = ToolRegistry()
        await register_builtin_core_tools(registry)

        roots = [Path(p.strip()) for p in (settings.plugin_roots or "").split(",") if p.strip()]
        if roots:
            loaded, errors = load_plugins_from_roots(
                roots,
                api_factory=lambda manifest, _plugin_dir, config: ToolRuntimePluginAPI(
                    host_kind="tool_runtime",
                    plugin_id=manifest.plugin_id,
                    config=config,
                    registry=registry,
                ),
            )
            for p, reason in errors:
                logger.error("plugin load error: %s: %s", p, reason)
            if errors and not settings.plugins_fail_open:
                raise RuntimeError(f"plugin load failed ({len(errors)} errors); set TOOL_RUNTIME_PLUGINS_FAIL_OPEN=1 to ignore")
            if loaded:
                logger.info("plugins loaded: %s", ", ".join(sorted({lp.manifest.plugin_id for lp in loaded})))

        app.state.settings = settings
        app.state.registry = registry
        app.state.router = Router(registry, allow_sandbox=settings.allow_sandbox, output_max_bytes=settings.output_max_bytes)
        app.state.idem = InMemoryIdempotencyStore()
        yield

    app = FastAPI(lifespan=lifespan)

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    @app.post("/internal/tools/manifest")
    async def tools_manifest(request: Request) -> Response:
        auth_err = await check_internal_auth(request, settings)
        if auth_err is not None:
            return auth_err

        try:
            body = await request.json()
        except Exception:
            return tool_error(
                status_code=400,
                type_="tool_input_error",
                code="invalid_json",
                message="invalid json body",
                retryable=False,
            )

        try:
            req = ManifestRequest.model_validate(body)
        except ValidationError as e:
            return tool_error(
                status_code=400,
                type_="tool_input_error",
                code="invalid_request",
                message=str(e),
                retryable=False,
            )

        tools, decisions_raw = build_manifest(
            registry=request.app.state.registry,
            requested_tool_names=req.requested_tool_names,
            allow_sandbox=settings.allow_sandbox,
            context=req.context.model_dump(exclude_none=True),
        )

        decisions: list[ManifestDecision] | None = None
        if req.requested_tool_names is not None:
            decisions = []
            # 先填充 build_manifest 的 allow/deny 结果
            for name, decision, reason in (decisions_raw or []):
                decisions.append(ManifestDecision(tool_name=name, decision=decision, reason=reason))

            # 再补充：requested 但 registry 不存在的工具名
            for name in req.requested_tool_names:
                if (
                    isinstance(name, str)
                    and name.strip()
                    and "*" not in name
                    and "?" not in name
                    and "[" not in name
                    and request.app.state.registry.get_tool(name) is None
                ):
                    decisions.append(ManifestDecision(tool_name=name, decision="deny", reason="tool_not_found"))

        return JSONResponse(
            status_code=200,
            content={
                "tools": tools,
                "toolset_version": request.app.state.registry.toolset_version,
                "decisions": [d.model_dump() for d in decisions] if decisions is not None else None,
            },
        )

    @app.post("/internal/tools/execute")
    async def tools_execute(request: Request) -> Response:
        auth_err = await check_internal_auth(request, settings)
        if auth_err is not None:
            return auth_err

        try:
            body = await request.json()
        except Exception:
            return tool_error(
                status_code=400,
                type_="tool_input_error",
                code="invalid_json",
                message="invalid json body",
                retryable=False,
            )

        try:
            req = ExecuteRequest.model_validate(body)
        except ValidationError as e:
            return tool_error(
                status_code=400,
                type_="tool_input_error",
                code="invalid_request",
                message=str(e),
                retryable=False,
            )

        if req.toolset_version is not None and req.toolset_version != request.app.state.registry.toolset_version:
            return tool_error(
                status_code=409,
                type_="tool_input_error",
                code="toolset_version_mismatch",
                message=(
                    f"toolset_version mismatch: expected={request.app.state.registry.toolset_version} got={req.toolset_version}"
                ),
                retryable=True,
            )

        tool_name = req.tool_name
        response_id = req.response_id
        tool_call_id = req.tool_call_id
        try:
            session_partition_key = build_session_partition_key(agent_id=req.agent_id, session_key=req.session_key)
        except SessionBindingError as e:
            return tool_error(
                status_code=400,
                type_="tool_input_error",
                code="invalid_session_binding",
                message=str(e),
                retryable=False,
            )
        trace_id = req.context.trace.trace_id if req.context.trace is not None else None

        logger.info(
            "tool_execute.begin",
            extra={
                "trace_id": trace_id,
                "tenant_id": req.tenant_id,
                "agent_id": req.agent_id,
                "session_key": req.session_key,
                "session_partition_key": session_partition_key,
                "response_id": response_id,
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
            },
        )

        idem_key = f"{response_id}:{tool_call_id}:{tool_name}"
        done = await request.app.state.idem.get_done(idem_key)
        if done is not None:
            logger.info(
                "tool_execute.cache_hit",
                extra={
                    "trace_id": trace_id,
                    "agent_id": req.agent_id,
                    "session_partition_key": session_partition_key,
                    "response_id": response_id,
                    "tool_call_id": tool_call_id,
                    "tool_name": tool_name,
                    "status": done.status,
                },
            )
            return JSONResponse(status_code=200, content=_to_execute_response(done))

        inflight = await request.app.state.idem.get_inflight(idem_key)
        if inflight is not None:
            return tool_error(
                status_code=409,
                type_="tool_in_progress",
                code="in_progress",
                message="tool call in progress",
                retryable=True,
                meta={"duration_ms": 0, "audit_ref": None, "output_truncated": False},
            )

        async def run() -> ToolResult:
            return await request.app.state.router.execute(
                tool_name=tool_name,
                arguments_json=req.arguments_json,
                context=req.context.model_dump(exclude_none=True),
                deadline_ms=req.deadline_ms,
            )

        task = asyncio.create_task(run())
        await request.app.state.idem.set_inflight(idem_key, task)
        try:
            result = await task
        except asyncio.CancelledError:
            result = ToolResult(
                status="cancelled",
                output=None,
                error={
                    "type": "tool_cancelled",
                    "code": "cancelled",
                    "message": "cancelled",
                    "retryable": False,
                },
                meta={"duration_ms": 0, "output_truncated": False, "audit_ref": None},
            )
        await request.app.state.idem.set_done(idem_key, result)
        logger.info(
            "tool_execute.done",
            extra={
                "trace_id": trace_id,
                "tenant_id": req.tenant_id,
                "agent_id": req.agent_id,
                "session_key": req.session_key,
                "session_partition_key": session_partition_key,
                "response_id": response_id,
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "status": result.status,
                "duration_ms": result.meta.get("duration_ms"),
                "output_truncated": result.meta.get("output_truncated"),
                "audit_ref": result.meta.get("audit_ref"),
            },
        )
        return JSONResponse(status_code=200, content=_to_execute_response(result))

    @app.post("/internal/tools/cancel")
    async def tools_cancel(request: Request) -> Response:
        auth_err = await check_internal_auth(request, settings)
        if auth_err is not None:
            return auth_err

        try:
            body = await request.json()
        except Exception:
            return JSONResponse(status_code=400, content={"ok": False})
        if not isinstance(body, dict):
            return JSONResponse(status_code=400, content={"ok": False})

        required = ["response_id", "tool_call_id", "tool_name"]
        if any(k not in body for k in required):
            return JSONResponse(status_code=400, content={"ok": False})

        idem_key = f"{body['response_id']}:{body['tool_call_id']}:{body['tool_name']}"
        ok = await request.app.state.idem.cancel(idem_key)
        return JSONResponse(status_code=200, content={"ok": ok})

    @app.get("/internal/tools/list")
    async def tools_list(request: Request) -> Response:
        auth_err = await check_internal_auth(request, settings)
        if auth_err is not None:
            return auth_err
        tools: list[ToolDefinition] = request.app.state.registry.list_tools()
        return JSONResponse(status_code=200, content={"tools": [t.model_dump() for t in tools]})

    return app


def _to_execute_response(result: ToolResult) -> dict[str, Any]:
    if result.status == "completed":
        return {
            "status": "completed",
            "output": result.output or "",
            "meta": result.meta,
        }
    if result.status == "cancelled":
        return {
            "status": "cancelled",
            "error": result.error,
            "meta": result.meta,
        }
    return {
        "status": "error",
        "error": result.error,
        "meta": result.meta,
    }
