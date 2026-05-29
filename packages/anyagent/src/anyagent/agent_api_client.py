from __future__ import annotations

"""
anyagent Client SDK — 资源型命名空间入口。

提供 ``AnyAgent`` 入口类，通过子命名空间与缓存属性组织能力：

- ``client.openai`` / ``client.async_openai`` — OpenAI 官方 SDK client（缓存属性）
- ``client.responses`` — AnyAgent 补充的 `/v1/responses/{id}` async helpers
- ``client.agents``    — Agent catalog / detail（/internal/agents）
- ``client.tools``     — Tool catalog / effective manifest discovery
- ``client.events``    — 内部观测 / replay（/internal/events/*）
- ``client.observability`` — typed telemetry query helpers（/internal/observability/*）
- ``client.skills``    — 技能发现（/internal/skills/list）
- ``client.prompts``   — prompt explain / preview（preview + local example bundle）
- ``client.admin``     — 管理面 helpers（如 `/admin/storage/health`）

设计决策：docs/architecture/decisions/openai-first-api-surface.md
"""

import fnmatch
from typing import TYPE_CHECKING, Any, AsyncIterator, TypeVar

import httpx
from pydantic import AnyHttpUrl, BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from anyagent.types import (
    AdminAgentConfigUpdateRequest,
    AdminAgentCreateRequest,
    AdminAgentCreateResponse,
    AdminAgentSkillsUpdateRequest,
    AdminCredentialDeleteResponse,
    AdminCredentialListResponse,
    AdminCredentialRef,
    AdminCredentialSetRequest,
    AdminSkillImportRequest,
    AdminSkillImportResponse,
    AdminSkillRegistryInstallRequest,
    AdminSkillUpdateCheckResponse,
    AdminToolCatalogResponse,
    AdminWorkspaceAgentFilesResponse,
    AdminWorkspaceAgentFileUpdateRequest,
    AdminWorkspaceAgentFileUpdateResponse,
    AnyAgentDoneEvent,
    AnyAgentFunctionToolParam,
    AnyAgentPromptContextEvent,
    AnyAgentResponseStatusPayload,
    HealthResponse,
    InternalAgentDetailResponse,
    InternalAgentsListResponse,
    InternalEventsListResponse,
    InternalEventsReplaySummary,
    InternalObservabilityErrorsResponse,
    InternalObservabilityMetricsResponse,
    InternalObservabilityRunsResponse,
    InternalObservabilitySummaryResponse,
    InternalObservabilityTimelineResponse,
    InternalObservabilityToolsResponse,
    InternalObservabilityTraceResponse,
    InternalPromptBundlePreviewResponse,
    InternalToolCatalogResponse,
    PromptRunBundleExampleResponse,
    PromptRunBundleExampleOptions,
    PromptRunBundleScenario,
    PromptRunBundleScenarioDescriptor,
    SSEBlock,
    StageEvent,
    InternalSkillsListResponse,
    PluginCatalogResponse,
    StorageHealthResponse,
    ToolRequestSource,
    ToolVisibilityExplanation,
)
from anyagent.protocol.sse import SSEBlockDecoder
from anyagent.protocol.stage_events import (
    decode_stage_event,
    parse_stage_event_seq,
)
from anyagent.sdk_prompt_examples import (
    EXAMPLE_SCENARIO_CATALOG,
    build_example_run_bundle,
    coerce_example_options,
)

if TYPE_CHECKING:
    from openai import AsyncOpenAI, OpenAI
    from openai.types.responses.response import Response as OpenAIResponseModel
else:
    OpenAIResponseModel = object

ModelT = TypeVar("ModelT", bound=BaseModel)


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

    async def _put_json(
        self,
        path: str,
        *,
        json_body: dict[str, Any],
        timeout: float = 10.0,
    ) -> Any:
        """Issue PUT with JSON body and return parsed JSON."""

        url = f"{self._base_url}{path}"
        if self._http is None:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.put(url, headers=self._headers(), json=json_body)
        else:
            r = await self._http.put(url, headers=self._headers(), json=json_body, timeout=timeout)
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
        if not r.content:
            return None
        return r.json()


def _validate_response(model_type: type[ModelT], data: Any) -> ModelT:
    """Validate one SDK response boundary against the public data model."""

    return model_type.model_validate(data)


def _validate_request(model_type: type[ModelT], data: ModelT | dict[str, Any]) -> ModelT:
    """Validate one SDK request boundary before serializing JSON."""

    return model_type.model_validate(data.model_dump(exclude_none=True) if isinstance(data, model_type) else data)


# ---------------------------------------------------------------------------
# client.responses — AnyAgent optional response helpers
# ---------------------------------------------------------------------------

class Responses(_Namespace):
    """Async helpers for AnyAgent response query/cancel endpoints."""

    async def retrieve(self, response_id: str) -> AnyAgentResponseStatusPayload:
        """Query response status or final payload via ``GET /v1/responses/{response_id}``."""
        data = await self._get(f"/v1/responses/{response_id}")
        return _validate_response(AnyAgentResponseStatusPayload, data)

    async def retrieve_typed(self, response_id: str) -> OpenAIResponseModel | None:
        """Retrieve and decode as OpenAI SDK ``Response`` when shape-compatible."""
        from anyagent.protocol.openai_responses import decode_openai_response

        raw = await self.retrieve(response_id)
        payload = raw.model_dump(exclude_none=True) if isinstance(raw, BaseModel) else raw
        return decode_openai_response(payload)

    async def cancel(self, response_id: str) -> AnyAgentResponseStatusPayload:
        """Best-effort cancel via ``POST /v1/responses/{response_id}/cancel``."""
        data = await self._post(f"/v1/responses/{response_id}/cancel")
        return _validate_response(AnyAgentResponseStatusPayload, data)


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
        return _validate_response(InternalEventsListResponse, data)

    async def list_typed(
        self,
        response_id: str,
        *,
        last_seq: int = 0,
        limit: int = 200,
        include_model_events: bool = True,
        include_subagent_events: bool = True,
    ) -> list[StageEvent]:
        """List persisted internal events and decode them into the typed stage union."""

        listing = await self.list(response_id=response_id, last_seq=last_seq, limit=limit)
        return listing.typed_events(
            include_model_events=include_model_events,
            include_subagent_events=include_subagent_events,
        )

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
        include_subagent_events: bool = True,
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
            if not include_subagent_events and decoded.type.startswith("anyagent.subagent."):
                continue
            yield decoded
            if isinstance(decoded, AnyAgentDoneEvent):
                return


class Observability(_Namespace):
    """Typed Core telemetry query helpers (``/internal/observability/*``)."""

    async def summary(self, response_id: str) -> InternalObservabilitySummaryResponse:
        data = await self._get("/internal/observability/summary", params={"response_id": response_id})
        return _validate_response(InternalObservabilitySummaryResponse, data)

    async def runs(
        self,
        *,
        agent_id: str | None = None,
        session_key: str | None = None,
        response_id: str | None = None,
        created_after_ms: int | None = None,
        created_before_ms: int | None = None,
        limit: int = 100,
    ) -> InternalObservabilityRunsResponse:
        data = await self._get(
            "/internal/observability/runs",
            params=_observability_params(
                agent_id=agent_id,
                session_key=session_key,
                response_id=response_id,
                created_after_ms=created_after_ms,
                created_before_ms=created_before_ms,
                limit=limit,
            ),
        )
        return _validate_response(InternalObservabilityRunsResponse, data)

    async def timeline(
        self,
        *,
        agent_id: str | None = None,
        session_key: str | None = None,
        response_id: str | None = None,
        trace_id: str | None = None,
        created_after_ms: int | None = None,
        created_before_ms: int | None = None,
        limit: int = 200,
    ) -> InternalObservabilityTimelineResponse:
        data = await self._get(
            "/internal/observability/timeline",
            params=_observability_params(
                agent_id=agent_id,
                session_key=session_key,
                response_id=response_id,
                trace_id=trace_id,
                created_after_ms=created_after_ms,
                created_before_ms=created_before_ms,
                limit=limit,
            ),
        )
        return _validate_response(InternalObservabilityTimelineResponse, data)

    async def metrics(
        self,
        *,
        agent_id: str | None = None,
        session_key: str | None = None,
        response_id: str | None = None,
        created_after_ms: int | None = None,
        created_before_ms: int | None = None,
        limit: int = 100,
    ) -> InternalObservabilityMetricsResponse:
        data = await self._get(
            "/internal/observability/metrics",
            params=_observability_params(
                agent_id=agent_id,
                session_key=session_key,
                response_id=response_id,
                created_after_ms=created_after_ms,
                created_before_ms=created_before_ms,
                limit=limit,
            ),
        )
        return _validate_response(InternalObservabilityMetricsResponse, data)

    async def tools(
        self,
        *,
        agent_id: str | None = None,
        session_key: str | None = None,
        response_id: str | None = None,
        created_after_ms: int | None = None,
        created_before_ms: int | None = None,
        limit: int = 100,
    ) -> InternalObservabilityToolsResponse:
        data = await self._get(
            "/internal/observability/tools",
            params=_observability_params(
                agent_id=agent_id,
                session_key=session_key,
                response_id=response_id,
                created_after_ms=created_after_ms,
                created_before_ms=created_before_ms,
                limit=limit,
            ),
        )
        return _validate_response(InternalObservabilityToolsResponse, data)

    async def errors(
        self,
        *,
        agent_id: str | None = None,
        session_key: str | None = None,
        response_id: str | None = None,
        trace_id: str | None = None,
        created_after_ms: int | None = None,
        created_before_ms: int | None = None,
        limit: int = 100,
    ) -> InternalObservabilityErrorsResponse:
        data = await self._get(
            "/internal/observability/errors",
            params=_observability_params(
                agent_id=agent_id,
                session_key=session_key,
                response_id=response_id,
                trace_id=trace_id,
                created_after_ms=created_after_ms,
                created_before_ms=created_before_ms,
                limit=limit,
            ),
        )
        return _validate_response(InternalObservabilityErrorsResponse, data)

    async def trace(self, trace_id: str, *, limit: int = 500) -> InternalObservabilityTraceResponse:
        data = await self._get(f"/internal/observability/traces/{trace_id}", params={"limit": int(limit)})
        return _validate_response(InternalObservabilityTraceResponse, data)


def _observability_params(
    *,
    agent_id: str | None = None,
    session_key: str | None = None,
    response_id: str | None = None,
    trace_id: str | None = None,
    created_after_ms: int | None = None,
    created_before_ms: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if agent_id:
        params["agent_id"] = agent_id
    if session_key:
        params["session_key"] = session_key
    if response_id:
        params["response_id"] = response_id
    if trace_id:
        params["trace_id"] = trace_id
    if created_after_ms is not None:
        params["created_after_ms"] = int(created_after_ms)
    if created_before_ms is not None:
        params["created_before_ms"] = int(created_before_ms)
    if limit is not None:
        params["limit"] = int(limit)
    return params


# ---------------------------------------------------------------------------
# client.skills — 技能发现
# ---------------------------------------------------------------------------

class Skills(_Namespace):
    """Skills discovery (``/internal/skills/list``)."""

    async def list(self, *, agent_id: str = "main") -> InternalSkillsListResponse:
        """List skills visible to an agent via ``GET /internal/skills/list``."""
        data = await self._get("/internal/skills/list", params={"agent_id": agent_id})
        return _validate_response(InternalSkillsListResponse, data)


class Agents(_Namespace):
    """Agent catalog helpers (``/internal/agents``)."""

    async def list(self, *, include_unexposed: bool = False) -> InternalAgentsListResponse:
        """List agent ids currently callable through the Agent API."""
        data = await self._get("/internal/agents", params={"include_unexposed": include_unexposed})
        return _validate_response(InternalAgentsListResponse, data)

    async def get(self, agent_id: str, *, include_prompt: bool = False) -> InternalAgentDetailResponse:
        """Return detailed configuration metadata for one agent."""
        data = await self._get(f"/internal/agents/{agent_id}", params={"include_prompt": include_prompt})
        return _validate_response(InternalAgentDetailResponse, data)


class Tools(_Namespace):
    """Effective tool discovery helpers (``/internal/tools/catalog``)."""

    async def catalog(
        self,
        *,
        agent_id: str = "main",
        session_key: str = "sdk-catalog",
        requested_tool_names: list[str] | None = None,
    ) -> InternalToolCatalogResponse:
        params: dict[str, Any] = {
            "agent_id": agent_id,
            "session_key": session_key,
        }
        if requested_tool_names:
            params["requested_tool_names"] = ",".join(item for item in requested_tool_names if item)
        data = await self._get("/internal/tools/catalog", params=params)
        return _validate_response(InternalToolCatalogResponse, data)

    async def explain(
        self,
        tool_name: str,
        *,
        agent_id: str = "main",
        session_key: str = "sdk-tool-explain",
        include_probe: bool = True,
    ) -> ToolVisibilityExplanation:
        """Explain why one tool is or is not visible to an agent.

        This is an SDK-side composition over typed discovery endpoints. It
        keeps the server API small while giving application code one object that
        ties together agent requested tools, selected skills, policy, and the
        effective manifest probe for a specific tool.
        """

        target = tool_name.strip()
        if not target:
            raise ValueError("tool_name must be non-empty")

        agent = await Agents(base_url=self._base_url, api_key=self._api_key, http=self._http).get(agent_id)
        skills = await Skills(base_url=self._base_url, api_key=self._api_key, http=self._http).list(agent_id=agent_id)
        default_selected = set(agent.skills.default_selected or [])
        selected_skills = [
            skill
            for skill in skills.skills
            if skill.selected or skill.stable_id in default_selected or skill.name in default_selected
        ]

        request_sources: list[ToolRequestSource] = []
        requested_patterns: list[str] = []
        for pattern in agent.tools.requested_tool_names:
            _append_tool_request_source(
                request_sources,
                requested_patterns,
                ToolRequestSource(source="agent", pattern=pattern),
            )
        for skill in selected_skills:
            for pattern in skill.requested_tool_names:
                _append_tool_request_source(
                    request_sources,
                    requested_patterns,
                    ToolRequestSource(
                        source="skill",
                        pattern=pattern,
                        skill_id=skill.stable_id,
                        skill_name=skill.name,
                        selected=True,
                    ),
                )

        base_catalog = await self.catalog(
            agent_id=agent_id,
            session_key=session_key,
            requested_tool_names=requested_patterns,
        )
        base_visible_names = [tool.name for tool in base_catalog.tools]
        base_effective = next((tool for tool in base_catalog.tools if tool.name == target), None)
        effective_tool = base_effective
        visible_tools = list(base_visible_names)
        visible_without_probe = base_effective is not None
        probe_catalog: InternalToolCatalogResponse | None = None

        if include_probe and base_effective is None:
            _append_tool_request_source(
                request_sources,
                requested_patterns,
                ToolRequestSource(source="probe", pattern=target),
            )
            probe_patterns = _dedupe_strs([*requested_patterns, target])
            probe_catalog = await self.catalog(
                agent_id=agent_id,
                session_key=session_key,
                requested_tool_names=probe_patterns,
            )
            visible_tools = [tool.name for tool in probe_catalog.tools]
            effective_tool = next((tool for tool in probe_catalog.tools if tool.name == target), None)

        notes: list[str] = []
        if effective_tool is None:
            notes.append("tool_not_visible")
            if not _matches_any(target, requested_patterns):
                notes.append("not_requested_by_agent_or_selected_skills")
        elif not visible_without_probe:
            notes.append("visible_when_requested")
        else:
            notes.append("visible_by_default")
        if agent.tools.allow_tools and not _matches_any(target, agent.tools.allow_tools):
            notes.append("outside_agent_allow_policy")
        if agent.tools.deny_tools and _matches_any(target, agent.tools.deny_tools):
            notes.append("blocked_by_agent_deny_policy")
        if skills.load_errors:
            notes.append("skill_load_errors_present")

        return ToolVisibilityExplanation(
            agent_id=agent_id,
            session_key=session_key,
            tool_name=target,
            visible=effective_tool is not None,
            visible_without_probe=visible_without_probe,
            requested_patterns=requested_patterns,
            request_sources=request_sources,
            effective_tool=effective_tool,
            visible_tools=visible_tools,
            policy_allow_tools=agent.tools.allow_tools,
            policy_deny_tools=agent.tools.deny_tools,
            selected_skill_ids=[skill.stable_id for skill in selected_skills],
            load_errors=skills.load_errors,
            notes=notes,
        )


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
        return _validate_response(InternalPromptBundlePreviewResponse, data)

    def example_run_bundle(
        self,
        *,
        agent_id: str = "main",
        session_key: str = "sess_example_bundle",
        model: str | None = None,
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

        return build_example_run_bundle(
            agent_id=agent_id,
            session_key=session_key,
            model=model or "anyagent-example-model",
            scenario=scenario,
            options=coerce_example_options(options),
        )

    def example_scenarios(self) -> list[PromptRunBundleScenarioDescriptor]:
        """List built-in local example run-bundle scenarios."""

        return list(EXAMPLE_SCENARIO_CATALOG)


def _append_tool_request_source(
    sources: list[ToolRequestSource],
    patterns: list[str],
    source: ToolRequestSource,
) -> None:
    pattern = source.pattern.strip() if isinstance(source.pattern, str) else ""
    if not pattern:
        return
    sources.append(source.model_copy(update={"pattern": pattern}))
    if pattern not in patterns:
        patterns.append(pattern)


def _matches_any(tool_name: str, patterns: list[str] | None) -> bool:
    for pattern in patterns or []:
        if not isinstance(pattern, str) or not pattern.strip():
            continue
        pat = pattern.strip()
        if "*" in pat or "?" in pat or "[" in pat:
            if fnmatch.fnmatchcase(tool_name, pat):
                return True
            continue
        if pat.endswith("."):
            if tool_name.startswith(pat):
                return True
            continue
        if pat.endswith(".*"):
            if tool_name.startswith(pat[:-1]):
                return True
            continue
        if tool_name == pat:
            return True
    return False


def _dedupe_strs(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        item = value.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


class Admin(_Namespace):
    """Admin helpers (`/admin/*`)."""

    async def storage_health(self) -> StorageHealthResponse:
        data = await self._get("/admin/storage/health")
        return _validate_response(StorageHealthResponse, data)

    async def tool_catalog(self) -> AdminToolCatalogResponse:
        data = await self._get("/admin/tools/catalog")
        return _validate_response(AdminToolCatalogResponse, data)

    async def plugin_catalog(self) -> PluginCatalogResponse:
        data = await self._get("/admin/plugins/catalog")
        return _validate_response(PluginCatalogResponse, data)

    async def set_credential(self, request: AdminCredentialSetRequest | dict[str, Any]) -> AdminCredentialRef:
        model = _validate_request(AdminCredentialSetRequest, request)
        data = await self._post_json("/admin/credentials", json_body=model.model_dump(exclude_none=True))
        return _validate_response(AdminCredentialRef, data)

    async def list_credentials(self) -> AdminCredentialListResponse:
        data = await self._get("/admin/credentials")
        return _validate_response(AdminCredentialListResponse, data)

    async def delete_credential(self, credential_id: str) -> AdminCredentialDeleteResponse:
        data = await self._delete(f"/admin/credentials/{credential_id}")
        return _validate_response(AdminCredentialDeleteResponse, data)

    async def create_agent(self, request: AdminAgentCreateRequest | dict[str, Any]) -> AdminAgentCreateResponse:
        model = _validate_request(AdminAgentCreateRequest, request)
        data = await self._post_json("/admin/workspace/agents", json_body=model.model_dump(exclude_none=True))
        return _validate_response(AdminAgentCreateResponse, data)

    async def get_agent(self, agent_id: str, *, include_prompt: bool = False) -> InternalAgentDetailResponse:
        data = await self._get(f"/admin/workspace/agents/{agent_id}", params={"include_prompt": include_prompt})
        return _validate_response(InternalAgentDetailResponse, data)

    async def list_agent_files(self, agent_id: str) -> AdminWorkspaceAgentFilesResponse:
        data = await self._get(f"/admin/workspace/agents/{agent_id}/files")
        return _validate_response(AdminWorkspaceAgentFilesResponse, data)

    async def update_agent_file(
        self,
        agent_id: str,
        kind: str,
        request: AdminWorkspaceAgentFileUpdateRequest | dict[str, Any],
    ) -> AdminWorkspaceAgentFileUpdateResponse:
        model = _validate_request(AdminWorkspaceAgentFileUpdateRequest, request)
        data = await self._put_json(
            f"/admin/workspace/agents/{agent_id}/files/{kind}",
            json_body=model.model_dump(exclude_none=True),
        )
        return _validate_response(AdminWorkspaceAgentFileUpdateResponse, data)

    async def import_agent_skill(
        self,
        agent_id: str,
        request: AdminSkillImportRequest | dict[str, Any],
    ) -> AdminSkillImportResponse:
        model = _validate_request(AdminSkillImportRequest, request)
        data = await self._post_json(
            f"/admin/workspace/agents/{agent_id}/skills/import",
            json_body=model.model_dump(exclude_none=True),
        )
        return _validate_response(AdminSkillImportResponse, data)

    async def install_agent_skill(
        self,
        agent_id: str,
        request: AdminSkillRegistryInstallRequest | dict[str, Any],
    ) -> AdminSkillImportResponse:
        model = _validate_request(AdminSkillRegistryInstallRequest, request)
        data = await self._post_json(
            f"/admin/workspace/agents/{agent_id}/skills/install",
            json_body=model.model_dump(exclude_none=True),
        )
        return _validate_response(AdminSkillImportResponse, data)

    async def check_agent_skill_update(
        self,
        agent_id: str,
        directory_name: str,
    ) -> AdminSkillUpdateCheckResponse:
        data = await self._get(
            f"/admin/workspace/agents/{agent_id}/skills/{directory_name}/update/check"
        )
        return _validate_response(AdminSkillUpdateCheckResponse, data)

    async def apply_agent_skill_update(
        self,
        agent_id: str,
        directory_name: str,
    ) -> AdminSkillImportResponse:
        data = await self._post_json(
            f"/admin/workspace/agents/{agent_id}/skills/{directory_name}/update/apply",
            json_body={},
        )
        return _validate_response(AdminSkillImportResponse, data)

    async def update_agent_skills(
        self,
        agent_id: str,
        request: AdminAgentSkillsUpdateRequest | dict[str, Any],
    ) -> AdminAgentCreateResponse:
        model = _validate_request(AdminAgentSkillsUpdateRequest, request)
        data = await self._put_json(
            f"/admin/workspace/agents/{agent_id}/skills",
            json_body=model.model_dump(exclude_none=True),
        )
        return _validate_response(AdminAgentCreateResponse, data)

    async def update_agent_config(
        self,
        agent_id: str,
        request: AdminAgentConfigUpdateRequest | dict[str, Any],
    ) -> AdminAgentCreateResponse:
        model = _validate_request(AdminAgentConfigUpdateRequest, request)
        data = await self._put_json(
            f"/admin/workspace/agents/{agent_id}/config",
            json_body=model.model_dump(exclude_none=True),
        )
        return _validate_response(AdminAgentCreateResponse, data)


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
        timeline = await client.observability.timeline(agent_id="main")
        health = await client.health()
        agents = await client.agents.list()
        agent = await client.agents.get("main")
        skills = await client.skills.list(agent_id="main")
        tools = await client.tools.catalog(agent_id="main")
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
        self.tools = Tools(**shared)
        self.events = Events(**shared)
        self.observability = Observability(**shared)
        self.skills = Skills(**shared)
        self.prompts = Prompts(**shared)
        self.admin = Admin(**shared)

    async def health(self) -> HealthResponse:
        data = await _Namespace(base_url=self._base_url, api_key=self._api_key, http=self._http)._get("/healthz")
        return _validate_response(HealthResponse, data)

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
