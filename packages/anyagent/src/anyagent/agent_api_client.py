from __future__ import annotations

"""
anyagent Client SDK — 资源型命名空间入口。

提供 ``AnyAgent`` 入口类，通过子命名空间与缓存属性组织能力：

- ``client.openai`` / ``client.async_openai`` — OpenAI 官方 SDK client（缓存属性）
- ``client.responses`` — AnyAgent 补充的 `/v1/responses/{id}` async helpers
- ``client.agents``    — Agent catalog / detail（/internal/agents）
- ``client.events``    — 内部观测 / replay（/internal/events/*）
- ``client.skills``    — 技能发现（/internal/skills/list）
- ``client.prompts``   — prompt explain / preview（preview + local example bundle）
- ``client.admin``     — 管理面 helpers（如 `/admin/storage/health`）

设计决策：docs/architecture/decisions/openai-first-api-surface.md
"""

from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator

import httpx
from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from anyagent.agent_packs import AgentPack, AgentSkillsSpec, AgentSpec, AgentToolsSpec, MultiAgentSpec
from anyagent.agent_runtime import build_default_environment_context_values, build_prompt_envelope
from anyagent.mcp.models import MCPConfig, MCPServerConfig
from anyagent.protocol.agent_api_internal import (
    InternalAgentDetailResponse,
    InternalAgentsListResponse,
    InternalEventsListResponse,
    InternalEventsReplaySummary,
    InternalPromptBundlePreviewResponse,
    PromptRunBundleExplanation,
    PromptRunBundleExplanationStep,
    PromptRunBundleExampleResponse,
    PromptRunBundleExampleOptions,
    PromptRunBundleScenario,
    PromptRunBundleScenarioDescriptor,
    PromptRunBundleToolLoopItem,
    InternalSkillsListResponse,
)
from anyagent.protocol.credential_vault import AdminCredentialListResponse, AdminCredentialRef, AdminCredentialSetRequest
from anyagent.protocol.health import HealthResponse
from anyagent.protocol.openai_responses import AnyAgentFunctionToolParam, build_minimal_openai_response_json
from anyagent.protocol.sandbox import FileSystemSandboxPolicy, SandboxPolicy
from anyagent.protocol.admin_storage import StorageHealthResponse
from anyagent.protocol.sse import SSEBlock, SSEBlockDecoder
from anyagent.protocol.stage_events import (
    AnyAgentDoneEvent,
    AnyAgentModelStreamEvent,
    AnyAgentPromptContextEvent,
    AnyAgentCommandPlannedEvent,
    AnyAgentCommandResultEvent,
    StageEvent,
    AnyAgentToolPlannedEvent,
    AnyAgentToolResultEvent,
    summarize_command,
    summarize_payload,
    decode_stage_event,
    parse_stage_event_seq,
)
from anyagent.protocol.tool_runtime import PolicyHint, RequesterContext, ToolContext, TraceContext
from anyagent.skills.models import SkillFrontMatter, SkillPackage

if TYPE_CHECKING:
    from openai import AsyncOpenAI, OpenAI
    from openai.types.responses.response import Response as OpenAIResponseModel
else:
    OpenAIResponseModel = object


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

class AnyAgentSettings(BaseSettings):
    """anyagent Client SDK settings (env-driven)."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    base_url: AnyHttpUrl = Field(
        default="http://127.0.0.1:8787",
        alias="ANYAGENT_AGENT_API_BASE_URL",
    )
    api_key: str = Field(alias="AGENT_API_KEY")


# ---------------------------------------------------------------------------
# Shared HTTP helper mixin
# ---------------------------------------------------------------------------

class _Namespace:
    """Base for resource namespaces sharing connection state."""

    __slots__ = ("_base_url", "_api_key", "_http")

    def __init__(self, *, base_url: str, api_key: str, http: httpx.AsyncClient | None) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self._http = http

    def _headers(self) -> dict[str, str]:
        return {"authorization": f"Bearer {self._api_key}"}

    async def _get(self, path: str, *, params: dict[str, Any] | None = None, timeout: float = 10.0) -> Any:
        """Issue GET and return parsed JSON."""
        url = f"{self._base_url}{path}"
        if self._http is None:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.get(url, headers=self._headers(), params=params)
        else:
            r = await self._http.get(url, headers=self._headers(), params=params, timeout=timeout)
        r.raise_for_status()
        return r.json()

    async def _post(self, path: str, *, timeout: float = 10.0) -> Any:
        """Issue POST (no body) and return parsed JSON."""
        url = f"{self._base_url}{path}"
        if self._http is None:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(url, headers=self._headers())
        else:
            r = await self._http.post(url, headers=self._headers(), timeout=timeout)
        r.raise_for_status()
        return r.json()

    async def _post_json(
        self,
        path: str,
        *,
        json_body: dict[str, Any],
        timeout: float = 10.0,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Issue POST with JSON body and return parsed JSON."""

        url = f"{self._base_url}{path}"
        request_headers = {**self._headers(), **(headers or {})}
        if self._http is None:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(url, headers=request_headers, json=json_body)
        else:
            r = await self._http.post(url, headers=request_headers, json=json_body, timeout=timeout)
        r.raise_for_status()
        return r.json()

    async def _delete(self, path: str, *, timeout: float = 10.0) -> Any:
        """Issue DELETE and return parsed JSON."""
        url = f"{self._base_url}{path}"
        if self._http is None:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.delete(url, headers=self._headers())
        else:
            r = await self._http.delete(url, headers=self._headers(), timeout=timeout)
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# client.responses — AnyAgent optional response helpers
# ---------------------------------------------------------------------------

class Responses(_Namespace):
    """Async helpers for AnyAgent response query/cancel endpoints."""

    async def retrieve(self, response_id: str) -> dict[str, Any]:
        """Query response status or final payload via ``GET /v1/responses/{response_id}``."""
        data = await self._get(f"/v1/responses/{response_id}")
        if not isinstance(data, dict):
            raise RuntimeError(f"invalid /v1/responses/{response_id} payload")
        return data

    async def retrieve_typed(self, response_id: str) -> OpenAIResponseModel | None:
        """Retrieve and decode as OpenAI SDK ``Response`` when shape-compatible."""
        from anyagent.protocol.openai_responses import decode_openai_response

        payload = await self.retrieve(response_id)
        return decode_openai_response(payload)

    async def cancel(self, response_id: str) -> dict[str, Any]:
        """Best-effort cancel via ``POST /v1/responses/{response_id}/cancel``."""
        data = await self._post(f"/v1/responses/{response_id}/cancel")
        if not isinstance(data, dict):
            raise RuntimeError(f"invalid /v1/responses/{response_id}/cancel payload")
        return data


# ---------------------------------------------------------------------------
# client.events — 内部观测 / replay
# ---------------------------------------------------------------------------

class Events(_Namespace):
    """Internal event observation and replay (``/internal/events/*``)."""

    def __init__(self, *, base_url: str, api_key: str, http: httpx.AsyncClient | None) -> None:
        super().__init__(base_url=base_url, api_key=api_key, http=http)
        self._sse_decoder_factory = SSEBlockDecoder

    async def list(
        self,
        response_id: str,
        *,
        last_seq: int = 0,
        limit: int = 200,
    ) -> InternalEventsListResponse:
        """Paginated event list via ``GET /internal/events/list``."""
        data = await self._get(
            "/internal/events/list",
            params={"response_id": response_id, "last_seq": int(last_seq), "limit": int(limit)},
        )
        return InternalEventsListResponse.model_validate(data)

    async def list_typed(
        self,
        response_id: str,
        *,
        last_seq: int = 0,
        limit: int = 200,
        include_model_events: bool = True,
    ) -> list[StageEvent]:
        """List persisted internal events and decode them into the typed stage union."""

        listing = await self.list(response_id=response_id, last_seq=last_seq, limit=limit)
        return listing.typed_events(include_model_events=include_model_events)

    async def latest_prompt_context(
        self,
        response_id: str,
        *,
        last_seq: int = 0,
        limit: int = 200,
    ) -> AnyAgentPromptContextEvent | None:
        """Find the latest prompt-context event across paginated internal replay pages."""

        cursor = int(last_seq)
        latest: AnyAgentPromptContextEvent | None = None
        while True:
            listing = await self.list(response_id=response_id, last_seq=cursor, limit=limit)
            page_latest = listing.latest_prompt_context()
            if page_latest is not None:
                latest = page_latest
            if listing.done or not listing.events or listing.next_last_seq <= cursor:
                return latest
            cursor = listing.next_last_seq

    async def replay_summary(
        self,
        response_id: str,
        *,
        last_seq: int = 0,
        limit: int = 200,
        include_model_events: bool = False,
        max_pages: int = 20,
    ) -> InternalEventsReplaySummary:
        """Build one higher-level replay summary from paginated internal events."""

        cursor = int(last_seq)
        scanned_pages = 0
        page_event_count = 0
        typed_event_count = 0
        latest_prompt_context: AnyAgentPromptContextEvent | None = None
        run_status: str | None = None
        effective_run_status: str | None = None
        done = False
        next_last_seq = cursor

        while scanned_pages < max(1, int(max_pages)):
            listing = await self.list(response_id=response_id, last_seq=cursor, limit=limit)
            scanned_pages += 1
            page_event_count += len(listing.events)
            typed_page = listing.typed_events(include_model_events=include_model_events)
            typed_event_count += len(typed_page)
            page_prompt_context = listing.latest_prompt_context()
            if page_prompt_context is not None:
                latest_prompt_context = page_prompt_context
            run_status = listing.run_status
            effective_run_status = listing.effective_run_status
            done = listing.done
            next_last_seq = listing.next_last_seq
            if listing.done or not listing.events or listing.next_last_seq <= cursor:
                break
            cursor = listing.next_last_seq

        return InternalEventsReplaySummary(
            response_id=response_id,
            requested_last_seq=int(last_seq),
            next_last_seq=next_last_seq,
            page_event_count=page_event_count,
            typed_event_count=typed_event_count,
            scanned_pages=scanned_pages,
            done=done,
            run_status=run_status,
            effective_run_status=effective_run_status,
            prompt_context=latest_prompt_context,
        )

    async def stream(
        self,
        response_id: str,
        *,
        last_seq: int = 0,
    ) -> AsyncIterator[SSEBlock]:
        """SSE stream of persisted events via ``GET /internal/events/stream``."""
        url = f"{self._base_url}/internal/events/stream"
        params: dict[str, Any] = {"response_id": response_id, "last_seq": int(last_seq)}

        async def _iter(client: httpx.AsyncClient) -> AsyncIterator[SSEBlock]:
            decoder = self._sse_decoder_factory()
            async with client.stream("GET", url, headers=self._headers(), params=params, timeout=None) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    for ev in decoder.feed_line(line):
                        yield ev
                for ev in decoder.flush():
                    yield ev

        if self._http is None:
            async with httpx.AsyncClient(timeout=None) as c:
                async for ev in _iter(c):
                    yield ev
            return

        async for ev in _iter(self._http):
            yield ev

    async def stream_typed(
        self,
        response_id: str,
        *,
        last_seq: int = 0,
        include_model_events: bool = True,
    ) -> AsyncIterator[StageEvent]:
        """Stream typed ``StageEvent`` union from internal event stream.

        Decodes ``anyagent.*``-prefixed events into typed stage models and wraps
        OpenAI Responses SSE events as ``AnyAgentModelStreamEvent``.
        """
        async for blk in self.stream(response_id, last_seq=last_seq):
            decoded = decode_stage_event(
                response_id=response_id,
                event=blk.event,
                data=blk.data,
                seq=parse_stage_event_seq(blk.id),
                include_model_events=include_model_events,
            )
            if decoded is None:
                continue
            yield decoded
            if isinstance(decoded, AnyAgentDoneEvent):
                return


# ---------------------------------------------------------------------------
# client.skills — 技能发现
# ---------------------------------------------------------------------------

class Skills(_Namespace):
    """Skills discovery (``/internal/skills/list``)."""

    async def list(self, *, agent_id: str = "main") -> InternalSkillsListResponse:
        """List skills visible to an agent via ``GET /internal/skills/list``."""
        data = await self._get("/internal/skills/list", params={"agent_id": agent_id})
        return InternalSkillsListResponse.model_validate(data)


class Agents(_Namespace):
    """Agent catalog helpers (``/internal/agents``)."""

    async def list(self, *, include_unexposed: bool = False) -> InternalAgentsListResponse:
        """List agent ids currently callable through the Agent API."""
        data = await self._get("/internal/agents", params={"include_unexposed": include_unexposed})
        return InternalAgentsListResponse.model_validate(data)

    async def get(self, agent_id: str, *, include_prompt: bool = False) -> InternalAgentDetailResponse:
        """Return detailed configuration metadata for one agent."""
        data = await self._get(f"/internal/agents/{agent_id}", params={"include_prompt": include_prompt})
        return InternalAgentDetailResponse.model_validate(data)


class Prompts(_Namespace):
    """Prompt debug / explain helpers (`/internal/prompt/*`)."""

    async def preview(
        self,
        request_body: dict[str, Any],
        *,
        x_agent_id: str | None = None,
    ) -> InternalPromptBundlePreviewResponse:
        """Preview one fully assembled prompt bundle via ``POST /internal/prompt/bundle``."""

        data = await self._post_json(
            "/internal/prompt/bundle",
            json_body=request_body,
            headers={"x-agent-id": x_agent_id} if isinstance(x_agent_id, str) and x_agent_id.strip() else None,
        )
        return InternalPromptBundlePreviewResponse.model_validate(data)

    def example_run_bundle(
        self,
        *,
        agent_id: str = "main",
        session_key: str = "sess_example_bundle",
        model: str = "gpt-5",
        scenario: PromptRunBundleScenario = "sandbox_file_write",
        options: PromptRunBundleExampleOptions | dict[str, Any] | None = None,
    ) -> PromptRunBundleExampleResponse:
        """
        Return one pure local illustrative run bundle.

        说明：
        - 不发 HTTP 请求
        - 不依赖真实 workspace / run / event store
        - 仅用 SDK 内部构造的 typed 示例数据展示完整链路
        """

        return _build_example_run_bundle(
            agent_id=agent_id,
            session_key=session_key,
            model=model,
            scenario=scenario,
            options=_coerce_example_options(options),
        )

    def example_scenarios(self) -> list[PromptRunBundleScenarioDescriptor]:
        """List built-in local example run-bundle scenarios."""

        return list(_EXAMPLE_SCENARIO_CATALOG)


class Admin(_Namespace):
    """Admin helpers (`/admin/*`)."""

    async def storage_health(self) -> StorageHealthResponse:
        data = await self._get("/admin/storage/health")
        return StorageHealthResponse.model_validate(data)

    async def set_credential(self, request: AdminCredentialSetRequest | dict[str, Any]) -> AdminCredentialRef:
        model = request if isinstance(request, AdminCredentialSetRequest) else AdminCredentialSetRequest.model_validate(request)
        data = await self._post_json("/admin/credentials", json_body=model.model_dump(exclude_none=True))
        return AdminCredentialRef.model_validate(data)

    async def list_credentials(self) -> AdminCredentialListResponse:
        data = await self._get("/admin/credentials")
        return AdminCredentialListResponse.model_validate(data)

    async def delete_credential(self, credential_id: str) -> dict[str, Any]:
        data = await self._delete(f"/admin/credentials/{credential_id}")
        if not isinstance(data, dict):
            raise RuntimeError("invalid /admin/credentials/{credential_id} delete payload")
        return data


# ---------------------------------------------------------------------------
# AnyAgent — SDK 入口
# ---------------------------------------------------------------------------

class AnyAgent:
    """anyagent Client SDK entry point (resource-namespace pattern).

    Usage::

        client = AnyAgent(api_key="...", base_url="http://127.0.0.1:8787")

        # OpenAI-compatible primary path
        resp = client.openai.responses.create(...)
        async_resp = await client.async_openai.responses.create(...)

        # AnyAgent async helpers for optional endpoints
        resp = await client.responses.retrieve(response_id)
        await client.responses.cancel(response_id)

        # AnyAgent superset
        events = await client.events.list(response_id)
        async for ev in client.events.stream_typed(response_id):
            ...
        health = await client.health()
        agents = await client.agents.list()
        agent = await client.agents.get("main")
        skills = await client.skills.list(agent_id="main")
        preview = await client.prompts.preview({...})
        example = client.prompts.example_run_bundle()
        await client.admin.set_credential({...})

        # Convenience: get OpenAI official SDK clients
        openai_client = client.as_openai_client()
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "http://127.0.0.1:8787",
        http: httpx.AsyncClient | None = None,
    ) -> None:
        base = base_url.rstrip("/")
        shared = {"base_url": base, "api_key": api_key, "http": http}

        self._base_url = base
        self._api_key = api_key
        self._http = http
        self._openai_client: OpenAI | None = None
        self._async_openai_client: AsyncOpenAI | None = None

        self.responses = Responses(**shared)
        self.agents = Agents(**shared)
        self.events = Events(**shared)
        self.skills = Skills(**shared)
        self.prompts = Prompts(**shared)
        self.admin = Admin(**shared)

    async def health(self) -> HealthResponse:
        data = await _Namespace(base_url=self._base_url, api_key=self._api_key, http=self._http)._get("/healthz")
        return HealthResponse.model_validate(data)

    def _openai_base_url(self) -> str:
        """Return normalized OpenAI SDK base URL for this AnyAgent server."""
        if self._base_url.endswith("/v1"):
            return self._base_url
        return f"{self._base_url}/v1"

    @property
    def openai(self) -> "OpenAI":
        """Return a cached OpenAI SDK sync client bound to this AnyAgent server."""
        if self._openai_client is None:
            self._openai_client = self.as_openai_client()
        return self._openai_client

    @property
    def async_openai(self) -> "AsyncOpenAI":
        """Return a cached OpenAI SDK async client bound to this AnyAgent server."""
        if self._async_openai_client is None:
            self._async_openai_client = self.as_async_openai_client()
        return self._async_openai_client

    def as_openai_client(self) -> "OpenAI":
        """Create a new OpenAI SDK sync client pointing to this AnyAgent server."""
        from openai import OpenAI

        return OpenAI(api_key=self._api_key, base_url=self._openai_base_url())

    def as_async_openai_client(self) -> "AsyncOpenAI":
        """Create a new OpenAI SDK async client pointing to this AnyAgent server."""
        from openai import AsyncOpenAI

        return AsyncOpenAI(api_key=self._api_key, base_url=self._openai_base_url())


# ---------------------------------------------------------------------------
# Factory (settings-driven)
# ---------------------------------------------------------------------------

def create_anyagent_client(
    *,
    settings: AnyAgentSettings,
    http: httpx.AsyncClient | None = None,
) -> AnyAgent:
    """Create an ``AnyAgent`` client from settings."""
    return AnyAgent(
        api_key=settings.api_key,
        base_url=str(settings.base_url).rstrip("/"),
        http=http,
    )


def _build_example_run_bundle(
    *,
    agent_id: str,
    session_key: str,
    model: str,
    scenario: PromptRunBundleScenario,
    options: PromptRunBundleExampleOptions,
) -> PromptRunBundleExampleResponse:
    """
    组装一个纯本地的 run bundle 示例。

    这条链路故意不依赖真实运行时：
    - 不访问 server
    - 不访问 event store
    - 不访问真实 MCP / tool runtime
    """

    response_id = f"resp_example_{agent_id}_{scenario}"
    scenario_spec = _build_example_scenario_spec(scenario=scenario, model=model, session_key=session_key)
    _apply_example_options(scenario_spec=scenario_spec, options=options)
    request_body = scenario_spec["request_body"]
    tool_call_id = scenario_spec["tool_call_id"]

    pack = AgentPack(
        agent_id=agent_id,
        root_dir=Path(f"/example-workspace/.agents/agents/{agent_id}"),
        spec=AgentSpec(
            exposed=True,
            tools=AgentToolsSpec(requested_tool_names=list(scenario_spec["requested_tool_names"])),
            skills=AgentSkillsSpec(default_selected=[]),
            sandbox=SandboxPolicy(
                mode=str(scenario_spec["sandbox_mode"]),
                filesystem=FileSystemSandboxPolicy(
                    persistence_mode=str(scenario_spec["persistence_mode"]),
                    workspace_root="/workspace",
                    hot_idle_ttl_s=900,
                    cold_retention_s=604800,
                    max_snapshot_bytes=5 * 1024 * 1024 * 1024,
                ),
            ),
            multiagent=MultiAgentSpec(),
        ),
        agents_md_path=Path(f"/example-workspace/.agents/agents/{agent_id}/AGENTS.md"),
        agents_md_text="你是一个 coding agent，优先解释上下文，再在沙箱里执行命令。\n",
        agents_md_sha256="example-agent-sha256",
        workspace_agents_md_path=Path("/example-workspace/AGENTS.md"),
        workspace_agents_md_text="这是 workspace 级协作规范。\n",
        workspace_agents_md_sha256="example-workspace-sha256",
        mcp_config=MCPConfig(
            mcpServers={
                label: MCPServerConfig.model_validate(config)
                for label, config in dict(scenario_spec["mcp_servers"]).items()
            }
        )
        if scenario_spec["mcp_servers"]
        else None,
    )

    skills = [
        SkillPackage(
            skill_dir=Path(f"/example-workspace/.agents/skills/{item['slug']}"),
            skill_md_path=Path(f"/example-workspace/.agents/skills/{item['slug']}/SKILL.md"),
            scope=item["scope"],
            frontmatter=SkillFrontMatter(name=item["name"], description=item["description"]),
            body_markdown=item["body_markdown"],
            agent_metadata=item["agent_metadata"],
        )
        for item in scenario_spec["skills"]
    ]

    tool_context = ToolContext(
        trace=TraceContext(trace_id="trace-example-run-bundle"),
        requester=RequesterContext(id="user_demo", display_name="Demo User", is_owner=True),
        policy=PolicyHint(allow_tools=list(scenario_spec["requested_tool_names"]), deny_tools=["admin.*"]),
    )
    environment_values = build_default_environment_context_values(cwd="/example-workspace", sandbox_mode=pack.spec.sandbox.mode)
    prompt_envelope = build_prompt_envelope(
        pack=pack,
        selected_skills=skills,
        tool_context=tool_context,
        model=model,
        environment_values=environment_values,
    )

    manifest_tools = [AnyAgentFunctionToolParam.model_validate(item) for item in scenario_spec["manifest_tools"]]

    effective_body = dict(request_body)
    applied_body = prompt_envelope.apply_to_body(body=effective_body)
    prompt_bundle = InternalPromptBundlePreviewResponse(
        agent_id=agent_id,
        session_key=session_key,
        model=model,
        prompt_cache_key=prompt_envelope.prompt_cache_key,
        instruction_role="developer",
        selected_skill_ids=[skill.stable_id for skill in skills],
        manifest_tools=manifest_tools,
        manifest_tool_names=[tool.name for tool in manifest_tools],
        mcp_servers=list(scenario_spec["mcp_servers"].keys()),
        tool_context=tool_context.model_dump(exclude_none=True),
        prompt_context=prompt_envelope.audit_metadata(),
        rendered_fragments=prompt_envelope.rendered_fragments(),
        effective_body=effective_body,
        applied_body=applied_body,
    )

    model_function_call = dict(scenario_spec["model_function_call"])
    tool_output_item = dict(scenario_spec["tool_output_item"])
    assistant_message = dict(scenario_spec["assistant_message"])
    tool_loop_items = [
        PromptRunBundleToolLoopItem(phase="model_function_call", item=model_function_call),
        PromptRunBundleToolLoopItem(phase="tool_output_to_model", item=tool_output_item),
        PromptRunBundleToolLoopItem(phase="assistant_message", item=assistant_message),
    ]

    model_response = build_minimal_openai_response_json(
        response_id=response_id,
        status="completed",
        model=model,
        tools=[tool.model_dump(exclude_none=True, by_alias=True) for tool in manifest_tools],
        tool_choice="auto",
        output=[assistant_message],
    )

    stage_events: list[StageEvent] = [
        AnyAgentPromptContextEvent.model_validate(
            {
                "type": "anyagent.prompt.context",
                "response_id": response_id,
                "trace_id": "trace-example-run-bundle",
                "seq": 1,
                "ts_ms": 1_730_000_000_001,
                **prompt_envelope.audit_metadata().model_dump(exclude_none=True),
            }
        ),
        AnyAgentToolPlannedEvent(
            response_id=response_id,
            trace_id="trace-example-run-bundle",
            seq=2,
            ts_ms=1_730_000_000_002,
            tool_call_id=tool_call_id,
            tool_name=str(model_function_call["name"]),
            arguments=summarize_payload(model_function_call.get("arguments")),
        ),
        AnyAgentCommandPlannedEvent(
            response_id=response_id,
            trace_id="trace-example-run-bundle",
            seq=3,
            ts_ms=1_730_000_000_003,
            command=summarize_command(str(scenario_spec["command_preview"])),
            workdir=scenario_spec.get("command_workdir"),
            timeout_ms=60000,
            source_tool_call_id=tool_call_id,
            source_tool_name=str(model_function_call["name"]),
        ),
        AnyAgentCommandResultEvent(
            response_id=response_id,
            trace_id="trace-example-run-bundle",
            seq=4,
            ts_ms=1_730_000_000_004,
            exit_code=int(scenario_spec["command_exit_code"]),
            stdout=summarize_payload(str(scenario_spec["command_stdout"])),
            stderr=summarize_payload(str(scenario_spec["command_stderr"])),
            duration_ms=int(scenario_spec["command_duration_ms"]),
            source_tool_call_id=tool_call_id,
            source_tool_name=str(model_function_call["name"]),
        ),
        AnyAgentToolResultEvent(
            response_id=response_id,
            trace_id="trace-example-run-bundle",
            seq=5,
            ts_ms=1_730_000_000_005,
            tool_call_id=tool_call_id,
            tool_name=str(model_function_call["name"]),
            status="completed",
            meta={"duration_ms": 240, "output_truncated": False, "audit_ref": "aud_example_exec"},
            output=summarize_payload(tool_output_item["output"]),
        ),
        AnyAgentModelStreamEvent(
            response_id=response_id,
            trace_id="trace-example-run-bundle",
            seq=6,
            ts_ms=1_730_000_000_006,
            sse_event="response.completed",
            payload={"type": "response.completed", "response": model_response},
        ),
        AnyAgentDoneEvent(
            response_id=response_id,
            trace_id="trace-example-run-bundle",
            seq=7,
            ts_ms=1_730_000_000_007,
        ),
    ]

    return PromptRunBundleExampleResponse(
        agent_id=agent_id,
        session_key=session_key,
        response_id=response_id,
        model=model,
        scenario=scenario,
        scenario_label=str(scenario_spec["scenario_label"]),
        options=options,
        prompt_bundle=prompt_bundle,
        tool_loop_items=tool_loop_items,
        stage_events=stage_events,
        model_response=model_response,
        explanation=_build_example_run_bundle_explanation(
            scenario=scenario,
            scenario_label=str(scenario_spec["scenario_label"]),
            manifest_tool_names=[tool.name for tool in manifest_tools],
            selected_skill_ids=[skill.stable_id for skill in skills],
        ),
    )


def _build_example_scenario_spec(
    *,
    scenario: PromptRunBundleScenario,
    model: str,
    session_key: str,
) -> dict[str, Any]:
    common_manifest_exec = {
        "type": "function",
        "name": "exec",
        "description": "Execute a shell command in the sandbox environment.",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["cmd"],
            "properties": {
                "cmd": {"type": "string"},
                "workdir": {"type": "string"},
                "timeout": {"type": "integer"},
            },
        },
        "x-anyagent-kind": "command",
    }
    if scenario == "multi_skill_research":
        return {
            "scenario_label": "Multi Skill Research",
            "request_body": {
                "model": model,
                "input": "请先抓取两篇资料，再总结成一份研究提纲。",
                "stream": False,
                "metadata": {"session_key": session_key},
            },
            "tool_call_id": "call_exec_research",
            "requested_tool_names": ["exec", "core.web_fetch"],
            "sandbox_mode": "local-unsafe",
            "persistence_mode": "session_hot_cold",
            "mcp_servers": {
                "github": {"url": "https://mcp.example.test"},
                "docs": {"url": "https://docs.example.test"},
            },
            "skills": [
                {
                    "slug": "repo-helper",
                    "scope": "repo",
                    "name": "repo-helper",
                    "description": "帮助分析仓库与生成修复计划",
                    "body_markdown": "Read the repository, summarize the task, then run targeted commands.\n",
                    "agent_metadata": {"interface": {"default_prompt": "Inspect the repo first."}},
                },
                {
                    "slug": "research-notes",
                    "scope": "repo",
                    "name": "research-notes",
                    "description": "帮助整理研究材料与提纲",
                    "body_markdown": "Gather multiple sources, compare them, and produce a concise outline.\n",
                    "agent_metadata": {"interface": {"default_prompt": "Compare sources before concluding."}},
                },
            ],
            "manifest_tools": [
                common_manifest_exec,
                {
                    "type": "function",
                    "name": "core.web_fetch",
                    "description": "Fetch a URL and return text content.",
                    "parameters": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["url"],
                        "properties": {"url": {"type": "string"}},
                    },
                },
            ],
            "model_function_call": {
                "type": "function_call",
                "call_id": "call_exec_research",
                "name": "exec",
                "arguments": '{"cmd":"python build_outline.py","workdir":"/workspace/research"}',
            },
            "tool_output_item": {
                "type": "function_call_output",
                "call_id": "call_exec_research",
                "output": '{"exit_code":0,"stdout":"outline saved to /workspace/research/outline.md","stderr":""}',
            },
            "assistant_message": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "我已经整理出研究提纲，并保存到 /workspace/research/outline.md。"}],
            },
            "command_preview": "python build_outline.py",
            "command_workdir": "/workspace/research",
            "command_exit_code": 0,
            "command_stdout": "outline saved to /workspace/research/outline.md",
            "command_stderr": "",
            "command_duration_ms": 480,
        }
    if scenario == "toolset_retry":
        return {
            "scenario_label": "Toolset Refresh Retry",
            "request_body": {
                "model": model,
                "input": "请在工具版本变更后重试并完成写文件。",
                "stream": False,
                "metadata": {"session_key": session_key},
            },
            "tool_call_id": "call_exec_retry",
            "requested_tool_names": ["exec"],
            "sandbox_mode": "local-unsafe",
            "persistence_mode": "session_hot_cold",
            "mcp_servers": {},
            "skills": [
                {
                    "slug": "retry-aware",
                    "scope": "repo",
                    "name": "retry-aware",
                    "description": "帮助在 manifest 变化后做单次安全重试",
                    "body_markdown": "If tool metadata changes, refresh manifest once before retrying.\n",
                    "agent_metadata": {"interface": {"default_prompt": "Retry once after manifest refresh."}},
                }
            ],
            "manifest_tools": [common_manifest_exec],
            "model_function_call": {
                "type": "function_call",
                "call_id": "call_exec_retry",
                "name": "exec",
                "arguments": '{"cmd":"python write_retry_file.py","workdir":"/workspace/retry"}',
            },
            "tool_output_item": {
                "type": "function_call_output",
                "call_id": "call_exec_retry",
                "output": '{"exit_code":0,"stdout":"retried after manifest refresh and wrote /workspace/retry/output.txt","stderr":""}',
            },
            "assistant_message": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "我已经在刷新工具清单后重试成功，并写入 /workspace/retry/output.txt。"}],
            },
            "command_preview": "python write_retry_file.py",
            "command_workdir": "/workspace/retry",
            "command_exit_code": 0,
            "command_stdout": "retried after manifest refresh and wrote /workspace/retry/output.txt",
            "command_stderr": "",
            "command_duration_ms": 310,
        }
    return {
        "scenario_label": "Sandbox File Write",
        "request_body": {
            "model": model,
            "input": "请抓取网页摘要，并在沙箱里生成一份总结文件。",
            "stream": False,
            "metadata": {"session_key": session_key},
        },
        "tool_call_id": "call_exec_example",
        "requested_tool_names": ["exec", "core.web_fetch"],
        "sandbox_mode": "local-unsafe",
        "persistence_mode": "session_hot_cold",
        "mcp_servers": {"github": {"url": "https://mcp.example.test"}},
        "skills": [
            {
                "slug": "repo-helper",
                "scope": "repo",
                "name": "repo-helper",
                "description": "帮助分析仓库与生成修复计划",
                "body_markdown": "Read the repository, summarize the task, then run targeted commands.\n",
                "agent_metadata": {
                    "interface": {"default_prompt": "Inspect the repo first."},
                    "dependencies.tools": [{"transport": "builtin", "value": "exec"}],
                },
            }
        ],
        "manifest_tools": [
            common_manifest_exec,
            {
                "type": "function",
                "name": "core.web_fetch",
                "description": "Fetch a URL and return text content.",
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["url"],
                    "properties": {"url": {"type": "string"}},
                },
            },
        ],
        "model_function_call": {
            "type": "function_call",
            "call_id": "call_exec_example",
            "name": "exec",
            "arguments": '{"cmd":"python summarize.py","workdir":"/workspace/repo"}',
        },
        "tool_output_item": {
            "type": "function_call_output",
            "call_id": "call_exec_example",
            "output": '{"exit_code":0,"stdout":"summary saved to /workspace/repo/summary.txt","stderr":""}',
        },
        "assistant_message": {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "我已经把总结写入 /workspace/repo/summary.txt。"}],
        },
        "command_preview": "python summarize.py",
        "command_workdir": "/workspace/repo",
        "command_exit_code": 0,
        "command_stdout": "summary saved to /workspace/repo/summary.txt",
        "command_stderr": "",
        "command_duration_ms": 240,
    }


def _build_example_run_bundle_explanation(
    *,
    scenario: PromptRunBundleScenario,
    scenario_label: str,
    manifest_tool_names: list[str],
    selected_skill_ids: list[str],
) -> PromptRunBundleExplanation:
    scenario_summary = {
        "sandbox_file_write": "展示一个典型的 coding agent 如何在沙箱里写文件，并把上下文、工具和最终回复串成完整链路。",
        "multi_skill_research": "展示多个 skill 和多个 MCP 引用如何共同影响 prompt bundle 与 tool loop。",
        "toolset_retry": "展示工具清单刷新后重试的 explain 视角，帮助说明 manifest/tool loop 的关系。",
    }[scenario]
    why = {
        "sandbox_file_write": "这个场景适合解释 sandbox guidance、workspace 持久化和 exec 命令派生事件。",
        "multi_skill_research": "这个场景适合解释为什么 PromptEnvelope 里会同时出现多个 skill 与 MCP catalog 片段。",
        "toolset_retry": "这个场景适合解释 manifest 和 tool loop 并不是静态不变的，重试也需要被解释出来。",
    }[scenario]
    steps = [
        PromptRunBundleExplanationStep(
            title="1. 先组装 prompt bundle",
            detail=f"示例先构造 {scenario_label} 场景下的 PromptEnvelope，把 AGENTS、skills、MCP、sandbox guidance 和 environment context 渲染成模型可见片段。",
            cites=["prompt_bundle.rendered_fragments", "prompt_bundle.prompt_context"],
        ),
        PromptRunBundleExplanationStep(
            title="2. 再展示 manifest 可见工具",
            detail=f"示例不会真的去请求 Tool Runtime，而是内部构造 manifest tools：{', '.join(manifest_tool_names)}。",
            cites=["prompt_bundle.manifest_tools", "prompt_bundle.manifest_tool_names"],
        ),
        PromptRunBundleExplanationStep(
            title="3. 最后拼出 tool loop 与模型回复",
            detail="示例继续构造 function_call、function_call_output、assistant message 和 stage events，形成一条完整但纯本地的运行轨迹。",
            cites=["tool_loop_items", "stage_events", "model_response"],
        ),
    ]
    return PromptRunBundleExplanation(
        summary=scenario_summary,
        why_this_shape=why,
        key_takeaways=[
            "这是一份纯本地示例，不依赖真实运行时。",
            f"当前示例选中的 skill 数量为 {len(selected_skill_ids)}。",
            "UI 或 onboarding 页面可以直接消费 explanation 和 stage_events 做演示。",
        ],
        steps=steps,
    )


def _coerce_example_options(options: PromptRunBundleExampleOptions | dict[str, Any] | None) -> PromptRunBundleExampleOptions:
    if isinstance(options, PromptRunBundleExampleOptions):
        return options
    if isinstance(options, dict):
        return PromptRunBundleExampleOptions.model_validate(options)
    return PromptRunBundleExampleOptions()


def _apply_example_options(
    *,
    scenario_spec: dict[str, Any],
    options: PromptRunBundleExampleOptions,
) -> None:
    # 这些覆写只作用于本地 explain 示例，不影响任何真实运行时状态。
    if options.user_input:
        scenario_spec["request_body"] = dict(scenario_spec["request_body"])
        scenario_spec["request_body"]["input"] = options.user_input

    if options.skill_count is not None:
        scenario_spec["skills"] = list(scenario_spec["skills"])[: int(options.skill_count)]

    if options.include_mcp is False:
        scenario_spec["mcp_servers"] = {}

    if options.sandbox_mode is not None:
        scenario_spec["sandbox_mode"] = options.sandbox_mode
        if options.sandbox_mode == "disabled":
            # 关闭 sandbox 时，示例也同步切换到非 exec 的工具形态，
            # 这样返回的数据和真实 PromptEnvelope 语义保持一致。
            requested = [name for name in list(scenario_spec["requested_tool_names"]) if name != "exec"]
            if "core.web_fetch" not in requested:
                requested.append("core.web_fetch")
            scenario_spec["requested_tool_names"] = requested
            scenario_spec["manifest_tools"] = [
                item for item in list(scenario_spec["manifest_tools"]) if item.get("name") != "exec"
            ]
            if not scenario_spec["manifest_tools"]:
                scenario_spec["manifest_tools"] = [
                    {
                        "type": "function",
                        "name": "core.web_fetch",
                        "description": "Fetch a URL and return text content.",
                        "parameters": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["url"],
                            "properties": {"url": {"type": "string"}},
                        },
                    }
                ]
            scenario_spec["model_function_call"] = {
                "type": "function_call",
                "call_id": "call_web_fetch_example",
                "name": "core.web_fetch",
                "arguments": '{"url":"https://example.com"}',
            }
            scenario_spec["tool_output_item"] = {
                "type": "function_call_output",
                "call_id": "call_web_fetch_example",
                "output": '{"status":200,"text":"example page summary","url":"https://example.com"}',
            }
            scenario_spec["assistant_message"] = {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "我已经基于抓取到的网页内容给出摘要。"}],
            }
            scenario_spec["tool_call_id"] = "call_web_fetch_example"
            scenario_spec["command_preview"] = "core.web_fetch https://example.com"
            scenario_spec["command_workdir"] = None
            scenario_spec["command_stdout"] = "example page summary"
            scenario_spec["command_stderr"] = ""
            scenario_spec["command_exit_code"] = 0
            scenario_spec["command_duration_ms"] = 120


_EXAMPLE_SCENARIO_CATALOG: tuple[PromptRunBundleScenarioDescriptor, ...] = (
    PromptRunBundleScenarioDescriptor(
        scenario="sandbox_file_write",
        label="Sandbox File Write",
        summary="演示典型 coding agent 如何在沙箱中写文件，并串起 prompt bundle、tool loop 与最终回复。",
        default_options=PromptRunBundleExampleOptions(
            skill_count=1,
            include_mcp=True,
            sandbox_mode="local-unsafe",
        ),
    ),
    PromptRunBundleScenarioDescriptor(
        scenario="multi_skill_research",
        label="Multi Skill Research",
        summary="演示多个 skills 与多个 MCP catalog 如何一起影响 PromptEnvelope 和后续 tool loop。",
        default_options=PromptRunBundleExampleOptions(
            skill_count=2,
            include_mcp=True,
            sandbox_mode="local-unsafe",
        ),
    ),
    PromptRunBundleScenarioDescriptor(
        scenario="toolset_retry",
        label="Toolset Refresh Retry",
        summary="演示 manifest/toolset 发生变化后，如何从 explain 视角理解一次重试链路。",
        default_options=PromptRunBundleExampleOptions(
            skill_count=1,
            include_mcp=False,
            sandbox_mode="local-unsafe",
        ),
    ),
)
