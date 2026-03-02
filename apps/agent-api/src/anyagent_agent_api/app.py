from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from anyagent.agent_packs import AgentCatalog, AgentPack, AgentPackError, load_agent_catalog
from anyagent.agent_runtime import inject_skills_into_responses_body
from anyagent.gateway.session import SessionBindingError
from anyagent.gateway.session import session_partition_key as build_session_partition_key
from anyagent.protocol.tool_runtime import PolicyHint, ToolContext
from anyagent.skills import (
    SkillEnablement,
    apply_skills_permissions_to_tool_context,
    canonical_skill_md_path,
    default_skill_roots,
    discover_skills,
    extract_user_texts_from_responses_request,
    load_skills_from_root,
    requested_tool_names_for_skill,
    requested_tool_names_for_skills,
    select_skills,
)
from anyagent.skills.models import SkillPackage

from .auth import check_api_key
from .errors import openai_error
from .keyed_sequencer import KeyedSequencer
from .manifest_cache import ManifestCache
from .openai_client import create_responses_json, create_responses_sse_events
from .openai_proxy import proxy_responses
from .settings import Settings
from .tool_runtime_client import ToolsetVersionMismatch, execute_tool, fetch_manifest


logger = logging.getLogger("anyagent.agent_api")


def _dedupe_strs(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for v in values:
        if not isinstance(v, str):
            continue
        s = v.strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _build_agents_md_injection_text(pack: AgentPack) -> str:
    body = (pack.agents_md_text or "").rstrip()
    return "\n".join(
        [
            "[AnyAgent Agent Pack]",
            f"agent_id: {pack.agent_id}",
            f"path: {pack.agents_md_path}",
            f"sha256: {pack.agents_md_sha256}",
            "",
            "[AGENTS_BODY]",
            body,
        ]
    ).rstrip()


def _inject_text_into_responses_body(*, body: dict[str, Any], text: str, role: str = "developer") -> dict[str, Any]:
    """
    将一段文本以 developer/system 角色注入到 OpenAI Responses 风格 body.input 中。
    注入位置：在第一个非 system/developer message 之前。
    """
    if not isinstance(text, str) or not text.strip():
        return body

    body2 = dict(body)
    injection_msg = {"role": role, "content": text}
    inp = body2.get("input")

    # input is a string => interpret as a single user message
    if isinstance(inp, str):
        body2["input"] = [injection_msg, {"role": "user", "content": inp}]
        return body2

    # input is missing => create a new list
    if inp is None:
        body2["input"] = [injection_msg]
        return body2

    # input is a list => insert before first non-(system/developer) message
    if isinstance(inp, list):
        out = list(inp)
        insert_at = 0
        for i, item in enumerate(out):
            if isinstance(item, dict) and isinstance(item.get("role"), str):
                r = item["role"]
                if r in {"system", "developer"}:
                    insert_at = i + 1
                    continue
            break
        out.insert(insert_at, injection_msg)
        body2["input"] = out
        return body2

    return body


def _get_agent_id(request: Request, metadata: dict[str, Any] | None) -> str:
    v = (metadata or {}).get("agent_id")
    if isinstance(v, str) and v.strip():
        return v.strip()

    h = request.headers.get("x-agent-id")
    if h and h.strip():
        return h.strip()

    return "main"


def _get_session_key(metadata: dict[str, Any] | None) -> str | None:
    v = (metadata or {}).get("session_key")
    if isinstance(v, str) and v.strip():
        return v.strip()
    return None


def _extract_requested_tool_names(tools: Any) -> list[str] | None:
    if tools is None:
        return None
    if not isinstance(tools, list):
        return None
    out: list[str] = []
    for t in tools:
        if not isinstance(t, dict):
            continue
        if t.get("type") != "function":
            continue
        fn = t.get("function")
        if not isinstance(fn, dict):
            continue
        name = fn.get("name")
        if isinstance(name, str) and name.strip():
            out.append(name.strip())
    return out


def _validate_tool_choice(tool_choice: Any, allowed_tool_names: set[str]) -> str | None:
    if tool_choice is None:
        return None
    if isinstance(tool_choice, str) and tool_choice in {"auto", "none", "required"}:
        return None
    if isinstance(tool_choice, dict) and tool_choice.get("type") == "function":
        fn = tool_choice.get("function")
        if isinstance(fn, dict) and isinstance(fn.get("name"), str):
            name = fn["name"].strip()
            if name in allowed_tool_names:
                return None
            return f"tool_choice function name not allowed: {name}"
    return "invalid tool_choice"


def _extract_function_calls(response_json: dict[str, Any]) -> list[dict[str, Any]]:
    output = response_json.get("output")
    if not isinstance(output, list):
        return []
    out: list[dict[str, Any]] = []
    for item in output:
        if isinstance(item, dict) and item.get("type") == "function_call":
            out.append(item)
    return out


def _normalize_response_id(payload: Any, canonical_response_id: str) -> None:
    if isinstance(payload, dict):
        if payload.get("object") == "response" and isinstance(payload.get("id"), str):
            payload["id"] = canonical_response_id
        if isinstance(payload.get("response_id"), str):
            payload["response_id"] = canonical_response_id
        resp = payload.get("response")
        if isinstance(resp, dict) and isinstance(resp.get("id"), str):
            resp["id"] = canonical_response_id
        for v in payload.values():
            _normalize_response_id(v, canonical_response_id)
    elif isinstance(payload, list):
        for v in payload:
            _normalize_response_id(v, canonical_response_id)


def _encode_sse_event(event: str | None, data: str) -> bytes:
    parts: list[str] = []
    if event:
        parts.append(f"event: {event}")
    for line in data.splitlines() or [""]:
        parts.append(f"data: {line}")
    parts.append("")
    return ("\n".join(parts) + "\n").encode("utf-8")


def create_app(settings: Settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.sequencer = KeyedSequencer()
        app.state.http = httpx.AsyncClient(timeout=None)
        app.state.manifest_cache = ManifestCache(ttl_seconds=settings.manifest_cache_ttl_seconds)
        app.state.workspace_dir = Path(settings.workspace_dir).expanduser().resolve()

        try:
            catalog = load_agent_catalog(workspace_dir=app.state.workspace_dir)
        except AgentPackError as e:
            raise RuntimeError(f"agent catalog load failed: {e}") from e

        main_pack = catalog.get("main")
        if main_pack is None:
            raise RuntimeError("agent catalog invalid: missing required agent_id=main")
        if not main_pack.spec.exposed:
            raise RuntimeError("agent catalog invalid: default agent_id=main must be exposed=true")

        # Skills discovery is restart-based in v0: read once at startup.
        global_roots = default_skill_roots(workspace_dir=app.state.workspace_dir)
        global_skills, global_skill_errors = discover_skills(global_roots)

        agent_skills: dict[str, list[SkillPackage]] = {}
        agent_skill_errors: dict[str, list[tuple[str, str]]] = {}
        for agent_id, pack in catalog.packs.items():
            skills, errors = load_skills_from_root(pack.skills_dir, scope="agent")
            agent_skills[agent_id] = skills
            agent_skill_errors[agent_id] = errors

        app.state.agent_catalog = catalog
        app.state.global_skills = global_skills
        app.state.global_skill_errors = global_skill_errors
        app.state.agent_skills = agent_skills
        app.state.agent_skill_errors = agent_skill_errors

        logger.info(
            "agent packs loaded",
            extra={
                "workspace_dir": str(app.state.workspace_dir),
                "agents_root": str(catalog.root_dir),
                "agents": sorted(catalog.packs.keys()),
                "global_skills": len(global_skills),
                "global_skill_errors": len(global_skill_errors),
            },
        )
        try:
            yield
        finally:
            await app.state.http.aclose()

    app = FastAPI(lifespan=lifespan)

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    @app.get("/readyz")
    async def readyz():
        return {"ok": True}

    @app.post("/v1/responses")
    async def v1_responses(request: Request) -> Response:
        auth_err = await check_api_key(request, settings)
        if auth_err is not None:
            return auth_err

        try:
            body = await request.json()
        except Exception:
            return openai_error(400, message="Invalid JSON body", type_="invalid_request_error")

        if not isinstance(body, dict):
            return openai_error(400, message="Request body must be a JSON object", type_="invalid_request_error")

        metadata = body.get("metadata")
        if metadata is not None and not isinstance(metadata, dict):
            return openai_error(400, message="metadata must be an object", type_="invalid_request_error")

        agent_id = _get_agent_id(request, metadata)

        catalog: AgentCatalog = request.app.state.agent_catalog
        pack = catalog.get(agent_id)
        if pack is None:
            return openai_error(404, message=f"unknown agent_id: {agent_id}", type_="invalid_request_error")
        if not pack.spec.exposed:
            return openai_error(403, message=f"agent_id not exposed: {agent_id}", type_="invalid_request_error")

        session_key = _get_session_key(metadata)
        if session_key is None:
            # req-4-3: no stable session provided => generate a temporary session key for this response only
            session_key = f"ephemeral::{uuid4().hex}"
        try:
            session_partition_key = build_session_partition_key(agent_id=agent_id, session_key=session_key)
        except SessionBindingError as e:
            return openai_error(400, message=str(e), type_="invalid_request_error")
        stream = bool(body.get("stream") is True)

        logger.info(
            "incoming /v1/responses",
            extra={
                "agent_id": agent_id,
                "session_key": session_key,
                "session_partition_key": session_partition_key,
                "stream": stream,
                "idempotency_key": request.headers.get("idempotency-key"),
            },
        )

        # --- skills selection (restart-based discovery; per-run selection) ---
        all_skills: list[SkillPackage] = list(request.app.state.global_skills) + list(request.app.state.agent_skills.get(agent_id, []))
        disabled: set[str] = set()
        for raw in pack.spec.skills.disabled_paths or []:
            if not isinstance(raw, str) or not raw.strip():
                continue
            s = raw.strip()
            if s.startswith("skill://"):
                s = s[len("skill://") :]
            p = Path(s).expanduser()
            # only accept explicit SKILL.md paths (avoid guessing names)
            if p.name != "SKILL.md":
                continue
            disabled.add(canonical_skill_md_path(p))

        enablement = SkillEnablement(user_disabled_paths=frozenset(disabled))
        user_texts = extract_user_texts_from_responses_request(body)
        selected_skills, skill_decisions = select_skills(
            skills=all_skills,
            enablement=enablement,
            metadata=metadata if isinstance(metadata, dict) else None,
            user_texts=user_texts,
            default_selected=pack.spec.skills.default_selected,
            allow_implicit_invocation=False,
        )
        enabled_skills = [s.stable_id for s in selected_skills]

        # --- tool visibility request set (union) ---
        requested_from_request = _extract_requested_tool_names(body.get("tools")) or []
        requested_from_agent = pack.spec.tools.requested_tool_names or []
        requested_from_skills = requested_tool_names_for_skills(selected_skills)
        requested_tool_names = _dedupe_strs([*requested_from_agent, *requested_from_skills, *requested_from_request])

        requested_tools = body.get("tools") if isinstance(body.get("tools"), list) else None

        # --- tool context policy (server-generated; ignore caller policy) ---
        raw_context = metadata.get("context") if isinstance(metadata, dict) else None
        raw_context = raw_context if isinstance(raw_context, dict) else {}
        raw_context = dict(raw_context)
        raw_context.pop("policy", None)  # critical: ignore caller-provided policy (req-2-2)

        try:
            tool_context = ToolContext.model_validate(raw_context)
        except Exception:  # noqa: BLE001
            tool_context = ToolContext()

        pol = pack.spec.tools.policy
        if pol is not None:
            allow = _dedupe_strs(pol.allow_tools or [])
            deny = _dedupe_strs(pol.deny_tools or [])
            if allow or deny:
                tool_context = ToolContext.model_validate(
                    {
                        **tool_context.model_dump(exclude_none=True),
                        "policy": PolicyHint(allow_tools=allow or None, deny_tools=deny or None).model_dump(exclude_none=True),
                    }
                )

        tool_context = apply_skills_permissions_to_tool_context(tool_context, skills=selected_skills)
        context = tool_context.model_dump(exclude_none=True)

        cached = request.app.state.manifest_cache.get(
            agent_id=agent_id,
            session_key=session_key,
            enabled_skills=enabled_skills or None,
            requested_tool_names=requested_tool_names,
            context=context,
        )
        if cached is not None:
            manifest_tools, toolset_version = cached
        else:
            try:
                manifest_tools, toolset_version = await fetch_manifest(
                    client=request.app.state.http,
                    settings=settings,
                    agent_id=agent_id,
                    session_key=session_key,
                    enabled_skills=enabled_skills or None,
                    requested_tool_names=requested_tool_names,
                    requested_tools=requested_tools,
                    context=context,
                )
            except httpx.HTTPError as e:
                return openai_error(502, message=f"Tool Runtime manifest error: {e}", type_="upstream_error")
            except Exception as e:  # noqa: BLE001
                return openai_error(502, message=f"Tool Runtime manifest error: {e}", type_="upstream_error")

            request.app.state.manifest_cache.put(
                agent_id=agent_id,
                session_key=session_key,
                enabled_skills=enabled_skills or None,
                requested_tool_names=requested_tool_names,
                context=context,
                tools=manifest_tools,
                toolset_version=toolset_version,
            )

        allowed_tool_names = {
            t.get("function", {}).get("name")
            for t in manifest_tools
            if isinstance(t, dict) and t.get("type") == "function" and isinstance(t.get("function"), dict)
        }
        allowed_tool_names = {n for n in allowed_tool_names if isinstance(n, str)}
        err = _validate_tool_choice(body.get("tool_choice"), allowed_tool_names)
        if err is not None:
            return openai_error(400, message=err, type_="invalid_request_error")

        body["tools"] = manifest_tools

        # --- inject Agent Pack instructions + selected skills (developer role) ---
        body = _inject_text_into_responses_body(body=body, text=_build_agents_md_injection_text(pack), role="developer")
        body, skill_injection_warnings = inject_skills_into_responses_body(body=body, selected_skills=selected_skills, role="developer")
        if skill_decisions or skill_injection_warnings:
            logger.info(
                "skills.selected",
                extra={
                    "agent_id": agent_id,
                    "session_partition_key": session_partition_key,
                    "selected_skills": [s.frontmatter.name for s in selected_skills],
                    "decisions": [d.__dict__ for d in skill_decisions],
                    "injection_warnings": [w.__dict__ for w in skill_injection_warnings],
                },
            )

        async def _refresh_manifest_for_session() -> tuple[list[dict[str, Any]], int]:
            manifest_tools2, toolset_version2 = await fetch_manifest(
                client=request.app.state.http,
                settings=settings,
                agent_id=agent_id,
                session_key=session_key,
                enabled_skills=enabled_skills or None,
                requested_tool_names=requested_tool_names,
                requested_tools=requested_tools,
                context=context,
            )
            request.app.state.manifest_cache.put(
                agent_id=agent_id,
                session_key=session_key,
                enabled_skills=enabled_skills or None,
                requested_tool_names=requested_tool_names,
                context=context,
                tools=manifest_tools2,
                toolset_version=toolset_version2,
            )
            return manifest_tools2, toolset_version2

        async def _execute_with_version_retry(
            *,
            response_id: str,
            tool_call_id: str,
            tool_name: str,
            arguments_json: Any,
            deadline_ms: int | None,
        ) -> tuple[dict[str, Any], int, list[dict[str, Any]]]:
            try:
                tr = await execute_tool(
                    client=request.app.state.http,
                    settings=settings,
                    agent_id=agent_id,
                    session_key=session_key,
                    response_id=response_id,
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    arguments_json=arguments_json,
                    context=context,
                    deadline_ms=deadline_ms,
                    toolset_version=toolset_version,
                )
                return tr, toolset_version, manifest_tools
            except ToolsetVersionMismatch:
                request.app.state.manifest_cache.invalidate_all()
                manifest_tools2, toolset_version2 = await _refresh_manifest_for_session()
                tr2 = await execute_tool(
                    client=request.app.state.http,
                    settings=settings,
                    agent_id=agent_id,
                    session_key=session_key,
                    response_id=response_id,
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    arguments_json=arguments_json,
                    context=context,
                    deadline_ms=deadline_ms,
                    toolset_version=toolset_version2,
                )
                return tr2, toolset_version2, manifest_tools2

        async def do_work() -> Response:
            nonlocal manifest_tools, toolset_version

            if stream:
                max_iters = 8
                all_events: list[list[tuple[str | None, str]]] = []

                status_code, events, completed, raw_text = await create_responses_sse_events(
                    client=request.app.state.http,
                    request=request,
                    settings=settings,
                    body=body,
                    forward_idempotency_key=True,
                )
                if status_code >= 400 or completed is None:
                    return Response(content=raw_text.encode("utf-8"), status_code=status_code, media_type="text/event-stream")

                canonical_response_id = completed.get("id") if isinstance(completed.get("id"), str) else "resp_anyagent"
                all_events.append(events)

                iters = 0
                resp_json = completed
                while iters < max_iters:
                    iters += 1
                    response_id = resp_json.get("id")
                    if not isinstance(response_id, str) or not response_id:
                        break
                    calls = _extract_function_calls(resp_json)
                    if not calls:
                        break

                    tool_outputs: list[dict[str, Any]] = []
                    for call in calls:
                        call_id = call.get("call_id")
                        tool_name = call.get("name")
                        arguments = call.get("arguments")
                        if not isinstance(call_id, str) or not isinstance(tool_name, str):
                            continue
                        try:
                            tr, toolset_version, manifest_tools = await _execute_with_version_retry(
                                response_id=response_id,
                                tool_call_id=call_id,
                                tool_name=tool_name,
                                arguments_json=arguments,
                                deadline_ms=30_000,
                            )
                        except httpx.HTTPError as e:
                            tr = {"status": "error", "error": {"type": "tool_runtime_error", "message": str(e)}}
                        except ToolsetVersionMismatch as e:
                            tr = {
                                "status": "error",
                                "error": {
                                    "type": "tool_runtime_error",
                                    "code": "toolset_version_mismatch",
                                    "message": str(e),
                                    "retryable": True,
                                },
                            }
                        except Exception as e:  # noqa: BLE001
                            tr = {"status": "error", "error": {"type": "tool_runtime_error", "message": str(e)}}

                        if tr.get("status") == "completed" and isinstance(tr.get("output"), str):
                            output_str = tr["output"]
                        else:
                            output_str = str({"error": tr.get("error"), "status": tr.get("status")})

                        tool_outputs.append({"type": "function_call_output", "call_id": call_id, "output": output_str})

                    if not tool_outputs:
                        break

                    next_body: dict[str, Any] = {
                        "model": body.get("model"),
                        "previous_response_id": response_id,
                        "input": tool_outputs,
                        "tools": manifest_tools,
                        "metadata": body.get("metadata"),
                        "stream": True,
                    }
                    if body.get("tool_choice") is not None:
                        next_body["tool_choice"] = body.get("tool_choice")

                    status_code, events, completed, raw_text = await create_responses_sse_events(
                        client=request.app.state.http,
                        request=request,
                        settings=settings,
                        body=next_body,
                        forward_idempotency_key=False,
                    )
                    if status_code >= 400 or completed is None:
                        break
                    all_events.append(events)
                    resp_json = completed

                async def iter_sse() -> Any:
                    for i, batch in enumerate(all_events):
                        is_last = i == len(all_events) - 1
                        for ev, data in batch:
                            if data.strip() == "[DONE]":
                                continue
                            if ev == "response.completed" and not is_last:
                                continue
                            if ev is None and not data:
                                continue
                            # best-effort rewrite response_id / response.id
                            try:
                                payload = json.loads(data)
                            except Exception:  # noqa: BLE001
                                yield _encode_sse_event(ev, data)
                                continue
                            _normalize_response_id(payload, canonical_response_id)
                            yield _encode_sse_event(ev, json.dumps(payload, ensure_ascii=False, separators=(",", ":")))

                    yield _encode_sse_event(None, "[DONE]")

                return StreamingResponse(iter_sse(), media_type="text/event-stream")

            max_iters = 8
            status_code, resp_json = await create_responses_json(
                client=request.app.state.http,
                request=request,
                settings=settings,
                body=body,
                forward_idempotency_key=True,
            )
            if status_code >= 400 or not isinstance(resp_json, dict):
                if isinstance(resp_json, dict):
                    return JSONResponse(status_code=status_code, content=resp_json)
                return openai_error(status_code, message="Upstream error", type_="upstream_error")

            iters = 0
            while iters < max_iters:
                iters += 1
                response_id = resp_json.get("id")
                if not isinstance(response_id, str) or not response_id:
                    break
                calls = _extract_function_calls(resp_json)
                if not calls:
                    break

                tool_outputs: list[dict[str, Any]] = []
                for call in calls:
                    call_id = call.get("call_id")
                    tool_name = call.get("name")
                    arguments = call.get("arguments")
                    if not isinstance(call_id, str) or not isinstance(tool_name, str):
                        continue
                    try:
                        tr, toolset_version, manifest_tools = await _execute_with_version_retry(
                            response_id=response_id,
                            tool_call_id=call_id,
                            tool_name=tool_name,
                            arguments_json=arguments,
                            deadline_ms=30_000,
                        )
                    except httpx.HTTPError as e:
                        tr = {"status": "error", "error": {"type": "tool_runtime_error", "message": str(e)}}
                    except ToolsetVersionMismatch as e:
                        tr = {
                            "status": "error",
                            "error": {
                                "type": "tool_runtime_error",
                                "code": "toolset_version_mismatch",
                                "message": str(e),
                                "retryable": True,
                            },
                        }
                    except Exception as e:  # noqa: BLE001
                        tr = {"status": "error", "error": {"type": "tool_runtime_error", "message": str(e)}}

                    if tr.get("status") == "completed" and isinstance(tr.get("output"), str):
                        output_str = tr["output"]
                    else:
                        output_str = str({"error": tr.get("error"), "status": tr.get("status")})

                    tool_outputs.append({"type": "function_call_output", "call_id": call_id, "output": output_str})

                if not tool_outputs:
                    break

                next_body: dict[str, Any] = {
                    "model": body.get("model"),
                    "previous_response_id": response_id,
                    "input": tool_outputs,
                    "tools": manifest_tools,
                    "metadata": body.get("metadata"),
                }
                if body.get("tool_choice") is not None:
                    next_body["tool_choice"] = body.get("tool_choice")

                status_code, resp_json = await create_responses_json(
                    client=request.app.state.http,
                    request=request,
                    settings=settings,
                    body=next_body,
                    forward_idempotency_key=False,
                )
                if status_code >= 400 or not isinstance(resp_json, dict):
                    break

            return JSONResponse(status_code=status_code, content=resp_json)

        if settings.enable_keyed_serialization:
            return await request.app.state.sequencer.run(session_partition_key, do_work)
        return await do_work()

    @app.get("/internal/skills/list")
    async def internal_skills_list(request: Request, agent_id: str = "main") -> Response:
        auth_err = await check_api_key(request, settings)
        if auth_err is not None:
            return auth_err

        catalog: AgentCatalog = request.app.state.agent_catalog
        pack = catalog.get(agent_id)
        if pack is None:
            return openai_error(404, message=f"unknown agent_id: {agent_id}", type_="invalid_request_error")

        all_skills: list[SkillPackage] = list(request.app.state.global_skills) + list(request.app.state.agent_skills.get(agent_id, []))

        disabled_paths: set[str] = set()
        for raw in pack.spec.skills.disabled_paths or []:
            if not isinstance(raw, str) or not raw.strip():
                continue
            s = raw.strip()
            if s.startswith("skill://"):
                s = s[len("skill://") :]
            p = Path(s).expanduser()
            if p.name != "SKILL.md":
                continue
            disabled_paths.add(canonical_skill_md_path(p))

        enablement = SkillEnablement(user_disabled_paths=frozenset(disabled_paths))

        skills_out: list[dict[str, Any]] = []
        for s in all_skills:
            short_description = None
            if s.frontmatter.metadata is not None:
                short_description = s.frontmatter.metadata.short_description
            skills_out.append(
                {
                    "stable_id": s.stable_id,
                    "name": s.frontmatter.name,
                    "description": s.frontmatter.description,
                    "short_description": short_description,
                    "scope": s.scope,
                    "enabled": enablement.is_enabled(s),
                    "requested_tool_names": requested_tool_names_for_skill(s),
                }
            )

        load_errors: list[dict[str, Any]] = []
        for path, reason in request.app.state.global_skill_errors:
            load_errors.append({"scope": "global", "path": path, "reason": reason})
        for path, reason in request.app.state.agent_skill_errors.get(agent_id, []):
            load_errors.append({"scope": "agent", "path": path, "reason": reason})

        return JSONResponse(
            status_code=200,
            content={
                "agent_id": agent_id,
                "disabled_paths": sorted(disabled_paths),
                "load_errors": load_errors,
                "skills": skills_out,
            },
        )

    return app
