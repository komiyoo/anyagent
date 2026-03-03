from __future__ import annotations

import asyncio
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
from anyagent.protocol.openai_responses import FunctionToolParam, ToolChoiceFunctionParam
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
from .clients.openai_client import create_responses_json
from .clients.openai_proxy import _pick_upstream_headers, proxy_responses  # noqa: PLC2701
from .clients.tool_runtime_client import ToolsetVersionMismatch, execute_tool, fetch_manifest
from .errors import openai_error
from .internal import create_internal_events_router, create_internal_skills_router
from .keyed_sequencer import KeyedSequencer
from .manifest_cache import ManifestCache
from .multiagent.manager import MultiAgentManager, stable_root_thread_id
from .sse import encode_sse_event
from .settings import Settings
from .storage import create_storage_runtime


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


def _validate_tool_choice(tool_choice: Any, allowed_tool_names: set[str]) -> str | None:
    if tool_choice is None:
        return None
    if isinstance(tool_choice, str) and tool_choice in {"auto", "none", "required"}:
        return None
    if isinstance(tool_choice, dict) and tool_choice.get("type") == "function":
        try:
            tc = ToolChoiceFunctionParam.model_validate(tool_choice)
        except Exception:  # noqa: BLE001
            return "invalid tool_choice"
        if tc.name in allowed_tool_names:
            return None
        return f"tool_choice function name not allowed: {tc.name}"
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


def create_app(settings: Settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.sequencer = KeyedSequencer()
        app.state.http = httpx.AsyncClient(timeout=None)
        app.state.manifest_cache = ManifestCache(ttl_seconds=settings.manifest_cache_ttl_seconds)
        app.state.multiagent = MultiAgentManager()
        app.state.storage = await create_storage_runtime(settings)
        app.state.storage_tasks: set[asyncio.Task[object]] = set()
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
            try:
                await app.state.storage.aclose()
            except Exception:  # noqa: BLE001
                pass
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

        root_thread_id = stable_root_thread_id(session_partition_key)
        thread_id = root_thread_id
        thread_depth = 0
        if isinstance(metadata, dict):
            mtid = metadata.get("thread_id")
            if isinstance(mtid, str) and mtid.strip():
                thread_id = mtid.strip()
            mdepth = metadata.get("thread_depth")
            if isinstance(mdepth, int) and mdepth >= 0:
                thread_depth = mdepth

        logger.info(
            "incoming /v1/responses",
            extra={
                "agent_id": agent_id,
                "session_key": session_key,
                "session_partition_key": session_partition_key,
                "thread_id": thread_id,
                "thread_depth": thread_depth,
                "stream": stream,
                "idempotency_key": request.headers.get("idempotency-key"),
            },
        )

        storage = request.app.state.storage
        idem_raw = request.headers.get("idempotency-key")
        idempotency_key = idem_raw.strip() if isinstance(idem_raw, str) else ""
        idempotency_key = idempotency_key if idempotency_key else None
        if idempotency_key is not None and len(idempotency_key) > 256:
            return openai_error(400, message="Idempotency-Key too long (max 256)", type_="invalid_request_error")

        idem_created = False
        idem_response_id: str | None = None

        async def _iter_sse_from_store(*, response_id: str) -> Any:
            after_seq = 0
            while True:
                events = await storage.event_store.list(response_id=response_id, after_seq=after_seq, limit=200)
                if events:
                    for ev in events:
                        after_seq = int(ev.seq)
                        yield encode_sse_event(ev.event, ev.data)
                        if ev.event is None and ev.data.strip() == "[DONE]":
                            return
                    continue

                run = await storage.run_store.get(response_id)
                if run is not None and run.status in {"completed", "errored"}:
                    if isinstance(run.final_response_json, dict):
                        data = json.dumps(run.final_response_json, ensure_ascii=False, separators=(",", ":"))
                        yield encode_sse_event("response.completed", data)
                    yield encode_sse_event(None, "[DONE]")
                    return

                if hasattr(storage.event_store, "wait_new"):
                    await storage.event_store.wait_new(response_id=response_id, after_seq=after_seq, timeout_s=1.0)
                else:
                    await asyncio.sleep(0.25)

        async def _wait_run_final(*, response_id: str, timeout_s: float) -> dict[str, Any] | None:
            deadline = asyncio.get_event_loop().time() + timeout_s
            while asyncio.get_event_loop().time() < deadline:
                run = await storage.run_store.get(response_id)
                if run is not None and run.status in {"completed", "errored"} and isinstance(run.final_response_json, dict):
                    return run.final_response_json
                await asyncio.sleep(0.25)
            return None

        if idempotency_key is not None:
            candidate_response_id = f"resp_anyagent_{uuid4().hex}"
            idem_created, run = await storage.run_store.try_create_started(
                response_id=candidate_response_id,
                session_partition_key=session_partition_key,
                idempotency_key=idempotency_key,
                stream=stream,
            )
            if run.session_partition_key != session_partition_key:
                return openai_error(
                    409,
                    message="Idempotency-Key conflict (session mismatch)",
                    type_="invalid_request_error",
                    code="idempotency_key_conflict",
                )

            idem_response_id = run.response_id

            if not idem_created:
                if stream:
                    return StreamingResponse(_iter_sse_from_store(response_id=idem_response_id), media_type="text/event-stream")

                if run.status in {"completed", "errored"} and isinstance(run.final_response_json, dict):
                    return JSONResponse(status_code=200, content=run.final_response_json)

                final = await _wait_run_final(response_id=idem_response_id, timeout_s=60.0)
                if final is not None:
                    return JSONResponse(status_code=200, content=final)
                return openai_error(504, message="Idempotent request still in progress", type_="timeout_error")

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
        raw_tools = body.get("tools")
        request_tools: list[FunctionToolParam] | None = None
        if raw_tools is not None:
            if not isinstance(raw_tools, list):
                return openai_error(400, message="tools must be a list", type_="invalid_request_error")
            parsed: list[FunctionToolParam] = []
            for i, t in enumerate(raw_tools):
                try:
                    parsed.append(FunctionToolParam.model_validate(t))
                except Exception as e:  # noqa: BLE001
                    return openai_error(400, message=f"invalid tools[{i}]: {e}", type_="invalid_request_error")
            request_tools = parsed

        requested_from_request = [t.name for t in (request_tools or [])]
        requested_from_agent = pack.spec.tools.requested_tool_names or []
        requested_from_skills = requested_tool_names_for_skills(selected_skills)
        requested_tool_names = _dedupe_strs([*requested_from_agent, *requested_from_skills, *requested_from_request])

        requested_tools = [t.model_dump(exclude_none=True) for t in (request_tools or [])] or None

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

        system_tools = request.app.state.multiagent.system_tools_for_pack(pack)
        if system_tools:
            manifest_tools = [*manifest_tools, *[t.model_dump(exclude_none=True) for t in system_tools]]
        system_tool_names = {t.name for t in system_tools}

        allowed_tool_names: set[str] = set()
        for t in manifest_tools:
            if not isinstance(t, dict) or t.get("type") != "function":
                continue
            name = t.get("name")
            if isinstance(name, str) and name.strip():
                allowed_tool_names.add(name.strip())
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
            if system_tools:
                manifest_tools2 = [*manifest_tools2, *[t.model_dump(exclude_none=True) for t in system_tools]]
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

        async def _execute_system_tool(
            *,
            tool_name: str,
            arguments_json: Any,
            tool_call_id: str,
        ) -> dict[str, Any]:
            event_base = {
                "event_source": "anyagent.multiagent",
                "event_tool_name": tool_name,
                "tool_call_id": tool_call_id,
                "agent_id": agent_id,
                "session_key": session_key,
                "session_partition_key": session_partition_key,
                "root_thread_id": root_thread_id,
                "parent_thread_id": thread_id,
                "parent_thread_depth": thread_depth,
            }

            if tool_name == "spawn_agent":
                logger.info("collab_agent_spawn_begin", extra=event_base)
            elif tool_name == "send_input":
                logger.info("collab_agent_interaction_begin", extra=event_base)
            elif tool_name == "wait":
                logger.info("collab_waiting_begin", extra=event_base)
            elif tool_name == "close_agent":
                logger.info("collab_close_begin", extra=event_base)
            elif tool_name == "resume_agent":
                logger.info("collab_resume_begin", extra=event_base)

            try:
                if tool_name == "spawn_agent":
                    catalog2: AgentCatalog = request.app.state.agent_catalog
                    out = request.app.state.multiagent.spawn_agent(
                        catalog=catalog2,
                        parent_pack=pack,
                        parent_thread_id=thread_id,
                        parent_depth=thread_depth,
                        root_thread_id=root_thread_id,
                        arguments_json=arguments_json,
                    )
                elif tool_name == "send_input":
                    out = request.app.state.multiagent.send_input(
                        parent_thread_id=thread_id,
                        parent_depth=thread_depth,
                        root_thread_id=root_thread_id,
                        arguments_json=arguments_json,
                    )
                elif tool_name == "wait":
                    out = await request.app.state.multiagent.wait(
                        parent_thread_id=thread_id,
                        parent_depth=thread_depth,
                        root_thread_id=root_thread_id,
                        arguments_json=arguments_json,
                    )
                elif tool_name == "close_agent":
                    out = request.app.state.multiagent.close_agent(
                        parent_thread_id=thread_id,
                        parent_depth=thread_depth,
                        root_thread_id=root_thread_id,
                        arguments_json=arguments_json,
                    )
                elif tool_name == "resume_agent":
                    out = request.app.state.multiagent.resume_agent(
                        parent_thread_id=thread_id,
                        parent_depth=thread_depth,
                        root_thread_id=root_thread_id,
                        arguments_json=arguments_json,
                    )
                else:
                    raise ValueError(f"unknown system tool: {tool_name}")
                extra2 = dict(event_base)
                child_thread_id = None
                if tool_name == "spawn_agent" and isinstance(out, str):
                    try:
                        j = json.loads(out)
                    except Exception:  # noqa: BLE001
                        j = None
                    if isinstance(j, dict) and isinstance(j.get("thread_id"), str):
                        child_thread_id = j["thread_id"]
                        extra2["child_thread_id"] = child_thread_id

                if tool_name == "spawn_agent":
                    logger.info("collab_agent_spawn_end", extra=extra2)
                elif tool_name == "send_input":
                    logger.info("collab_agent_interaction_end", extra=extra2)
                elif tool_name == "wait":
                    logger.info("collab_waiting_end", extra=extra2)
                elif tool_name == "close_agent":
                    logger.info("collab_close_end", extra=extra2)
                elif tool_name == "resume_agent":
                    logger.info("collab_resume_end", extra=extra2)

                return {"status": "completed", "output": out}
            except Exception as e:  # noqa: BLE001
                code = str(e) if str(e) else "system_tool_error"
                extra2 = dict(event_base)
                extra2["error_code"] = code
                extra2["error_message"] = str(e)

                if tool_name == "spawn_agent":
                    logger.info("collab_agent_spawn_end", extra=extra2)
                elif tool_name == "send_input":
                    logger.info("collab_agent_interaction_end", extra=extra2)
                elif tool_name == "wait":
                    logger.info("collab_waiting_end", extra=extra2)
                elif tool_name == "close_agent":
                    logger.info("collab_close_end", extra=extra2)
                elif tool_name == "resume_agent":
                    logger.info("collab_resume_end", extra=extra2)
                return {
                    "status": "error",
                    "error": {
                        "type": "system_tool_error",
                        "code": code,
                        "message": str(e),
                        "retryable": False,
                    },
                }

        async def do_work() -> Response:
            nonlocal manifest_tools, toolset_version

            if stream:
                if idempotency_key is not None and idem_created and isinstance(idem_response_id, str) and idem_response_id:
                    upstream_headers0 = _pick_upstream_headers(request, settings)

                    async def _run_stream_to_store() -> None:
                        nonlocal manifest_tools, toolset_version

                        max_iters = 8
                        canonical_response_id = idem_response_id
                        cur_body: dict[str, Any] = json.loads(json.dumps(body))
                        forward_idempotency_key = True

                        async def _append_event(ev: str | None, data: str) -> None:
                            try:
                                seq = await storage.event_store.append(
                                    response_id=canonical_response_id,
                                    session_partition_key=session_partition_key,
                                    event=ev,
                                    data=data,
                                )
                                if hasattr(storage.run_store, "set_last_event_seq"):
                                    await storage.run_store.set_last_event_seq(response_id=canonical_response_id, last_event_seq=int(seq))
                            except Exception:  # noqa: BLE001
                                return

                        async def _with_lease(fn):  # type: ignore[no-untyped-def]
                            if getattr(storage, "mode", "none") != "external":
                                return await fn()

                            owner = canonical_response_id
                            handle = await storage.lease_lock.acquire(
                                key=session_partition_key,
                                owner=owner,
                                ttl_ms=30_000,
                                wait_timeout_ms=30_000,
                            )
                            if handle is None:
                                raise RuntimeError("lease_lock_unavailable")

                            renew_task: asyncio.Task[object] | None = None

                            async def _renew_loop() -> None:
                                while True:
                                    await asyncio.sleep(10.0)
                                    ok = await storage.lease_lock.renew(key=session_partition_key, owner=owner, ttl_ms=30_000)
                                    if not ok:
                                        raise RuntimeError("lease_lock_lost")

                            try:
                                renew_task = asyncio.create_task(_renew_loop())
                                return await fn()
                            finally:
                                if renew_task is not None:
                                    renew_task.cancel()
                                await storage.lease_lock.release(key=session_partition_key, owner=owner)

                        async def _openai_stream_response(*, body2: dict[str, Any]) -> httpx.Response:
                            url = str(settings.openai_base_url).rstrip("/") + "/responses"
                            headers = dict(upstream_headers0)
                            if not forward_idempotency_key:
                                headers.pop("idempotency-key", None)
                            req2 = request.app.state.http.build_request("POST", url, headers=headers, json=body2)
                            return await request.app.state.http.send(req2, stream=True, timeout=None)

                        final_response: dict[str, Any] | None = None
                        error_json: dict[str, Any] | None = None

                        async def _run_inner() -> None:
                            nonlocal forward_idempotency_key, cur_body, final_response, error_json, manifest_tools, toolset_version

                            iters = 0
                            while iters < max_iters:
                                iters += 1
                                upstream = await _openai_stream_response(body2=cur_body)
                                forward_idempotency_key = False

                                if upstream.status_code >= 400:
                                    try:
                                        raw = await upstream.aread()
                                    finally:
                                        await upstream.aclose()
                                    await _append_event("error", raw.decode("utf-8", errors="replace"))
                                    error_json = {"type": "upstream_error", "message": "upstream error"}
                                    break

                                completed: dict[str, Any] | None = None
                                cur_event: str | None = None
                                cur_data: list[str] = []

                                def _decode_completed_response(data: str) -> dict[str, Any] | None:
                                    try:
                                        payload = json.loads(data)
                                    except Exception:  # noqa: BLE001
                                        return None
                                    if not isinstance(payload, dict):
                                        return None
                                    resp = payload.get("response")
                                    if isinstance(resp, dict):
                                        return resp
                                    if isinstance(payload.get("id"), str):
                                        return payload
                                    return None

                                async def flush_block() -> None:
                                    nonlocal completed, cur_event, cur_data, final_response

                                    if cur_event is None and not cur_data:
                                        return

                                    data = "\n".join(cur_data)
                                    ev = cur_event
                                    cur_event = None
                                    cur_data = []

                                    if data.strip() == "[DONE]":
                                        return
                                    if ev is None and not data:
                                        return

                                    if ev == "response.completed":
                                        completed = _decode_completed_response(data)
                                        if completed is None:
                                            return
                                        # If function calls exist, tool loop will continue; do not emit this completion.
                                        if _extract_function_calls(completed):
                                            return

                                    try:
                                        payload = json.loads(data)
                                    except Exception:  # noqa: BLE001
                                        await _append_event(ev, data)
                                        return

                                    _normalize_response_id(payload, canonical_response_id)
                                    data2 = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                                    await _append_event(ev, data2)

                                    if ev == "response.completed" and isinstance(completed, dict):
                                        _normalize_response_id(completed, canonical_response_id)
                                        final_response = completed

                                try:
                                    async for line in upstream.aiter_lines():
                                        if not line.strip():
                                            await flush_block()
                                            continue
                                        if line.startswith("event:"):
                                            cur_event = line[len("event:") :].strip() or None
                                        elif line.startswith("data:"):
                                            cur_data.append(line[len("data:") :].lstrip())
                                        else:
                                            continue
                                    await flush_block()
                                finally:
                                    await upstream.aclose()

                                if completed is None:
                                    break

                                upstream_response_id = completed.get("id")
                                if not isinstance(upstream_response_id, str) or not upstream_response_id:
                                    break

                                calls = _extract_function_calls(completed)
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
                                        if tool_name in system_tool_names:
                                            tr = await _execute_system_tool(
                                                tool_name=tool_name,
                                                arguments_json=arguments,
                                                tool_call_id=call_id,
                                            )
                                        else:
                                            tr, toolset_version, manifest_tools = await _execute_with_version_retry(
                                                response_id=canonical_response_id,
                                                tool_call_id=call_id,
                                                tool_name=tool_name,
                                                arguments_json=arguments,
                                                deadline_ms=30_000,
                                            )
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
                                    "previous_response_id": upstream_response_id,
                                    "input": tool_outputs,
                                    "tools": manifest_tools,
                                    "metadata": body.get("metadata"),
                                    "stream": True,
                                }
                                if body.get("tool_choice") is not None:
                                    next_body["tool_choice"] = body.get("tool_choice")
                                cur_body = next_body

                        async def _run_all() -> None:
                            try:
                                await _with_lease(_run_inner)
                                await _append_event(None, "[DONE]")
                                await storage.run_store.set_final(
                                    response_id=canonical_response_id,
                                    status="completed" if error_json is None else "errored",
                                    final_response_json=final_response,
                                    error_json=error_json,
                                )
                            except Exception as e:  # noqa: BLE001
                                await _append_event("error", str(e))
                                await _append_event(None, "[DONE]")
                                await storage.run_store.set_final(
                                    response_id=canonical_response_id,
                                    status="errored",
                                    final_response_json=final_response,
                                    error_json={"type": "storage_error", "message": str(e)},
                                )

                        if settings.enable_keyed_serialization:
                            await request.app.state.sequencer.run(session_partition_key, _run_all)
                        else:
                            await _run_all()

                    task = asyncio.create_task(_run_stream_to_store())
                    request.app.state.storage_tasks.add(task)
                    task.add_done_callback(lambda t: request.app.state.storage_tasks.discard(t))  # type: ignore[arg-type]

                    return StreamingResponse(_iter_sse_from_store(response_id=idem_response_id), media_type="text/event-stream")

                max_iters = 8

                canonical_response_id = f"resp_anyagent_{uuid4().hex}"

                def _decode_completed_response(data: str) -> dict[str, Any] | None:
                    try:
                        payload = json.loads(data)
                    except Exception:  # noqa: BLE001
                        return None
                    if not isinstance(payload, dict):
                        return None
                    resp = payload.get("response")
                    if isinstance(resp, dict):
                        return resp
                    if isinstance(payload.get("id"), str):
                        return payload
                    return None

                async def _openai_stream_response(*, body2: dict[str, Any], forward_idempotency_key: bool) -> httpx.Response:
                    url = str(settings.openai_base_url).rstrip("/") + "/responses"
                    headers = _pick_upstream_headers(request, settings)
                    if not forward_idempotency_key:
                        headers.pop("idempotency-key", None)
                    req2 = request.app.state.http.build_request("POST", url, headers=headers, json=body2)
                    return await request.app.state.http.send(req2, stream=True, timeout=None)

                # preflight: open the first upstream stream so we can propagate status_code correctly
                upstream0 = await _openai_stream_response(body2=body, forward_idempotency_key=True)
                if upstream0.status_code >= 400:
                    try:
                        raw = await upstream0.aread()
                    finally:
                        await upstream0.aclose()
                    media_type = upstream0.headers.get("content-type") or "application/json"
                    return Response(content=raw, status_code=upstream0.status_code, media_type=media_type)

                async def iter_sse() -> Any:
                    nonlocal manifest_tools, toolset_version

                    iters = 0
                    cur_body: dict[str, Any] = dict(body)
                    cur_upstream: httpx.Response | None = upstream0
                    forward_idempotency_key = True

                    while iters < max_iters:
                        iters += 1

                        upstream = cur_upstream
                        if upstream is None:
                            upstream = await _openai_stream_response(body2=cur_body, forward_idempotency_key=forward_idempotency_key)
                        cur_upstream = None
                        forward_idempotency_key = False

                        if upstream.status_code >= 400:
                            try:
                                raw = await upstream.aread()
                            finally:
                                await upstream.aclose()
                            # best-effort surface upstream error in-stream; then terminate.
                            yield encode_sse_event("error", raw.decode("utf-8", errors="replace"))
                            break

                        completed: dict[str, Any] | None = None

                        cur_event: str | None = None
                        cur_data: list[str] = []

                        async def flush_block() -> Any:
                            nonlocal completed, cur_event, cur_data

                            if cur_event is None and not cur_data:
                                return

                            data = "\n".join(cur_data)
                            ev = cur_event
                            cur_event = None
                            cur_data = []

                            if data.strip() == "[DONE]":
                                return
                            if ev is None and not data:
                                return

                            if ev == "response.completed":
                                completed = _decode_completed_response(data)
                                if completed is None:
                                    return
                                response_id = completed.get("id")
                                if not isinstance(response_id, str) or not response_id:
                                    return

                                calls = _extract_function_calls(completed)
                                if calls:
                                    # intermediate completion: do not forward; tool loop will continue
                                    return

                            # backpressure strategy (v0):
                            # - pull-based streaming: do not pre-buffer upstream SSE; yielding is tied to client drain
                            # - if client disconnects, stop reading upstream asap
                            if await request.is_disconnected():
                                raise asyncio.CancelledError

                            # best-effort rewrite response_id / response.id to a single stable id
                            try:
                                payload = json.loads(data)
                            except Exception:  # noqa: BLE001
                                yield encode_sse_event(ev, data)
                                return

                            _normalize_response_id(payload, canonical_response_id)
                            yield encode_sse_event(ev, json.dumps(payload, ensure_ascii=False, separators=(",", ":")))

                        try:
                            async for line in upstream.aiter_lines():
                                if await request.is_disconnected():
                                    break
                                if not line.strip():
                                    async for chunk in flush_block():
                                        yield chunk
                                    continue
                                if line.startswith("event:"):
                                    cur_event = line[len("event:") :].strip() or None
                                elif line.startswith("data:"):
                                    cur_data.append(line[len("data:") :].lstrip())
                                else:
                                    continue

                            # flush last block if any
                            async for chunk in flush_block():
                                yield chunk
                        except asyncio.CancelledError:
                            # client disconnected: stop immediately
                            return
                        finally:
                            await upstream.aclose()

                        if completed is None:
                            break

                        response_id = completed.get("id")
                        if not isinstance(response_id, str) or not response_id:
                            break

                        calls = _extract_function_calls(completed)
                        if not calls:
                            break

                        if await request.is_disconnected():
                            break

                        tool_outputs: list[dict[str, Any]] = []
                        for call in calls:
                            call_id = call.get("call_id")
                            tool_name = call.get("name")
                            arguments = call.get("arguments")
                            if not isinstance(call_id, str) or not isinstance(tool_name, str):
                                continue
                            try:
                                if tool_name in system_tool_names:
                                    tr = await _execute_system_tool(
                                        tool_name=tool_name,
                                        arguments_json=arguments,
                                        tool_call_id=call_id,
                                    )
                                else:
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

                        cur_body = next_body

                    yield encode_sse_event(None, "[DONE]")

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
                if idempotency_key is not None and idem_created and isinstance(idem_response_id, str) and idem_response_id:
                    err_json = resp_json if isinstance(resp_json, dict) else {"error": {"message": "upstream_error"}}
                    await storage.run_store.set_final(
                        response_id=idem_response_id,
                        status="errored",
                        final_response_json=None,
                        error_json=err_json.get("error") if isinstance(err_json, dict) else None,
                    )
                    try:
                        await storage.event_store.append(
                            response_id=idem_response_id,
                            session_partition_key=session_partition_key,
                            event="error",
                            data=json.dumps(err_json, ensure_ascii=False, separators=(",", ":")),
                        )
                        await storage.event_store.append(
                            response_id=idem_response_id,
                            session_partition_key=session_partition_key,
                            event=None,
                            data="[DONE]",
                        )
                    except Exception:  # noqa: BLE001
                        pass
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
                        if tool_name in system_tool_names:
                            tr = await _execute_system_tool(
                                tool_name=tool_name,
                                arguments_json=arguments,
                                tool_call_id=call_id,
                            )
                        else:
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

            if idempotency_key is not None and idem_created and isinstance(idem_response_id, str) and idem_response_id and isinstance(resp_json, dict):
                try:
                    _normalize_response_id(resp_json, idem_response_id)
                except Exception:  # noqa: BLE001
                    pass

                await storage.run_store.set_final(
                    response_id=idem_response_id,
                    status="completed" if status_code < 400 else "errored",
                    final_response_json=resp_json,
                    error_json=resp_json.get("error") if status_code >= 400 else None,
                )
                try:
                    await storage.event_store.append(
                        response_id=idem_response_id,
                        session_partition_key=session_partition_key,
                        event="response.completed",
                        data=json.dumps(resp_json, ensure_ascii=False, separators=(",", ":")),
                    )
                    await storage.event_store.append(
                        response_id=idem_response_id,
                        session_partition_key=session_partition_key,
                        event=None,
                        data="[DONE]",
                    )
                except Exception:  # noqa: BLE001
                    pass

            return JSONResponse(status_code=status_code, content=resp_json)

        async def _run_with_local_serialization() -> Response:
            if settings.enable_keyed_serialization:
                return await request.app.state.sequencer.run(session_partition_key, do_work)
            return await do_work()

        # In external storage mode, enforce multi-instance session serialization via Redis lease lock.
        # Skip here for idempotent stream leaders because the actual work happens in a background task.
        if getattr(storage, "mode", "none") == "external" and not (
            stream and idempotency_key is not None and idem_created and isinstance(idem_response_id, str) and idem_response_id
        ):
            owner = idem_response_id if isinstance(idem_response_id, str) and idem_response_id else f"lease_{uuid4().hex}"
            handle = await storage.lease_lock.acquire(
                key=session_partition_key,
                owner=owner,
                ttl_ms=30_000,
                wait_timeout_ms=30_000,
            )
            if handle is None:
                return openai_error(
                    409,
                    message="session busy (lease lock)",
                    type_="rate_limit_error",
                    code="lease_lock_unavailable",
                    retryable=True,
                )

            renew_task: asyncio.Task[object] | None = None

            async def _renew_loop() -> None:
                while True:
                    await asyncio.sleep(10.0)
                    ok = await storage.lease_lock.renew(key=session_partition_key, owner=owner, ttl_ms=30_000)
                    if not ok:
                        raise RuntimeError("lease_lock_lost")

            try:
                renew_task = asyncio.create_task(_renew_loop())
                return await _run_with_local_serialization()
            finally:
                if renew_task is not None:
                    renew_task.cancel()
                await storage.lease_lock.release(key=session_partition_key, owner=owner)

        return await _run_with_local_serialization()

    app.include_router(create_internal_events_router(settings))
    app.include_router(create_internal_skills_router(settings))

    return app
