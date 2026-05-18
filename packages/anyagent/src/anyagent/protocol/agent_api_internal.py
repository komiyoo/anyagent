from __future__ import annotations

"""
anyagent Agent API internal endpoints protocol (SSOT).

This module defines the request/response models for Agent API internal endpoints:
- /internal/events/list
- /internal/skills/list

Notes:
- These endpoints are not part of the external OpenAI Responses compatibility surface.
- We still keep them in `anyagent.protocol` so both server and client can share types.
"""

from collections.abc import Iterator
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from anyagent.protocol.openai_responses import AnyAgentFunctionToolParam
from anyagent.protocol.prompt_context import PromptContextAudit, RenderedPromptFragment
from anyagent.protocol.sandbox import SandboxMode
from anyagent.protocol.stage_events import AnyAgentPromptContextEvent, StageEvent, decode_stage_event


WorkspaceAgentFileKind = Literal["agents_md", "agent_yaml", "mcp_json"]


class InternalEventItem(BaseModel):
    """One stored SSE block (seq + event + data)."""

    model_config = ConfigDict(extra="forbid")

    seq: int = Field(ge=1)
    event: str | None = None
    data: str


class InternalEventsListResponse(BaseModel):
    """Response model for `GET /internal/events/list`."""

    model_config = ConfigDict(extra="forbid")

    response_id: str
    requested_last_seq: int = Field(ge=0)
    next_last_seq: int = Field(ge=0)
    events: list[InternalEventItem] = Field(default_factory=list)
    done: bool
    run_status: str | None = None
    effective_run_status: str | None = None

    def iter_typed(self, *, include_model_events: bool = True) -> Iterator[StageEvent]:
        """Yield typed stage events decoded from stored SSE blocks."""

        for item in self.events:
            decoded = decode_stage_event(
                response_id=self.response_id,
                event=item.event,
                data=item.data,
                seq=item.seq,
                include_model_events=include_model_events,
            )
            if decoded is not None:
                yield decoded

    def typed_events(self, *, include_model_events: bool = True) -> list[StageEvent]:
        """Decode stored SSE blocks into typed stage events."""

        return list(self.iter_typed(include_model_events=include_model_events))

    def latest_prompt_context(self) -> AnyAgentPromptContextEvent | None:
        """Return the latest prompt-context event present in this page, if any."""

        latest: AnyAgentPromptContextEvent | None = None
        for event in self.iter_typed(include_model_events=False):
            if isinstance(event, AnyAgentPromptContextEvent):
                latest = event
        return latest

    def replay_summary(self, *, include_model_events: bool = True) -> "InternalEventsReplaySummary":
        """Build one compact replay summary for this page."""

        typed = self.typed_events(include_model_events=include_model_events)
        prompt_context = self.latest_prompt_context()
        return InternalEventsReplaySummary(
            response_id=self.response_id,
            requested_last_seq=self.requested_last_seq,
            next_last_seq=self.next_last_seq,
            page_event_count=len(self.events),
            typed_event_count=len(typed),
            done=self.done,
            run_status=self.run_status,
            effective_run_status=self.effective_run_status,
            prompt_context=prompt_context,
        )


class InternalEventsReplaySummary(BaseModel):
    """Compact replay/debug summary derived from one or more internal event pages."""

    model_config = ConfigDict(extra="forbid")

    response_id: str
    requested_last_seq: int = Field(ge=0)
    next_last_seq: int = Field(ge=0)
    page_event_count: int = Field(default=0, ge=0)
    typed_event_count: int = Field(default=0, ge=0)
    scanned_pages: int = Field(default=1, ge=1)
    done: bool
    run_status: str | None = None
    effective_run_status: str | None = None
    prompt_context: AnyAgentPromptContextEvent | None = None


class InternalObservabilityTurnMetric(BaseModel):
    """Per-turn character metrics derived from request and final response text."""

    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=1)
    input_chars: int = Field(default=0, ge=0)
    output_chars: int = Field(default=0, ge=0)


class InternalObservabilitySummaryResponse(BaseModel):
    """Server-side observability summary for one response/run."""

    model_config = ConfigDict(extra="forbid")

    response_id: str
    agent_id: str | None = None
    session_key: str | None = None
    event_count: int = Field(default=0, ge=0)
    typed_event_count: int = Field(default=0, ge=0)
    tool_call_count: int = Field(default=0, ge=0)
    mcp_call_count: int = Field(default=0, ge=0)
    skill_view_count: int = Field(default=0, ge=0)
    turn_count: int = Field(default=0, ge=0)
    input_chars: int = Field(default=0, ge=0)
    output_chars: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    turns: list[InternalObservabilityTurnMetric] = Field(default_factory=list)
    first_token_latency_ms: float | None = None
    total_response_latency_ms: float | None = None
    run_status: str | None = None
    effective_run_status: str | None = None


class InternalObservabilityRunItem(BaseModel):
    """One run row for agent/session observability history."""

    model_config = ConfigDict(extra="forbid")

    response_id: str
    agent_id: str
    session_key: str
    stream: bool
    status: str
    effective_status: str
    created_at_ms: int = Field(ge=0)
    updated_at_ms: int = Field(ge=0)
    ended_at_ms: int | None = Field(default=None, ge=0)


class InternalObservabilityRunsResponse(BaseModel):
    """Response model for `GET /internal/observability/runs`."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str | None = None
    session_key: str | None = None
    response_id: str | None = None
    runs: list[InternalObservabilityRunItem] = Field(default_factory=list)


class InternalSkillListItem(BaseModel):
    """One skill entry returned by `GET /internal/skills/list`."""

    model_config = ConfigDict(extra="forbid")

    stable_id: str
    name: str
    description: str | None = None
    short_description: str | None = None
    path: str
    scope: str
    enabled: bool
    selected: bool = False
    source_hash: str | None = None
    interface: dict[str, Any] | None = None
    requested_tool_names: list[str] = Field(default_factory=list)


class InternalSkillLoadError(BaseModel):
    """One skill load error returned by `GET /internal/skills/list`."""

    model_config = ConfigDict(extra="forbid")

    scope: Literal["global", "agent"]
    path: str
    reason: str


class InternalSkillsListResponse(BaseModel):
    """Response model for `GET /internal/skills/list`."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    disabled_paths: list[str] = Field(default_factory=list)
    load_errors: list[InternalSkillLoadError] = Field(default_factory=list)
    skills: list[InternalSkillListItem] = Field(default_factory=list)


class InternalToolCatalogItem(BaseModel):
    """One effective tool visible to an agent after policy/MCP/skill resolution."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str | None = None
    kind: str | None = None
    parameters: dict[str, Any] | None = None
    decision: str = "allow"
    reason: str | None = None


class InternalToolCatalogResponse(BaseModel):
    """Response model for `GET /internal/tools/catalog`."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    session_key: str
    requested_tool_names: list[str] = Field(default_factory=list)
    toolset_version: int
    tools: list[InternalToolCatalogItem] = Field(default_factory=list)


class AdminToolCatalogResponse(BaseModel):
    """Response model for `GET /admin/tools/catalog`."""

    model_config = ConfigDict(extra="forbid")

    toolset_version: int
    tools: list[InternalToolCatalogItem] = Field(default_factory=list)


class InternalAgentPromptRef(BaseModel):
    """Prompt source metadata for an agent or workspace AGENTS.md."""

    model_config = ConfigDict(extra="forbid")

    path: str
    sha256: str
    preview: str | None = None
    text: str | None = None


class InternalAgentListItem(BaseModel):
    """One agent catalog entry returned by `GET /internal/agents`."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    name: str
    exposed: bool
    root_dir: str
    prompt_sha256: str
    workspace_prompt_sha256: str | None = None
    sandbox_mode: SandboxMode
    requested_tool_names: list[str] = Field(default_factory=list)
    default_selected_skill_ids: list[str] = Field(default_factory=list)
    spawn_allow_agent_ids: list[str] = Field(default_factory=list)
    has_mcp: bool = False
    mcp_server_labels: list[str] = Field(default_factory=list)


class InternalAgentsListResponse(BaseModel):
    """Response model for `GET /internal/agents`."""

    model_config = ConfigDict(extra="forbid")

    agents: list[InternalAgentListItem] = Field(default_factory=list)


class InternalAgentToolsConfig(BaseModel):
    """Agent tools configuration summary."""

    model_config = ConfigDict(extra="forbid")

    requested_tool_names: list[str] = Field(default_factory=list)
    allow_tools: list[str] | None = None
    deny_tools: list[str] | None = None


class InternalAgentSkillsConfig(BaseModel):
    """Agent skills configuration summary."""

    model_config = ConfigDict(extra="forbid")

    default_selected: list[str] | None = None
    disabled_paths: list[str] | None = None


class InternalAgentMCPConfig(BaseModel):
    """Agent MCP configuration summary."""

    model_config = ConfigDict(extra="forbid")

    configured: bool = False
    server_labels: list[str] = Field(default_factory=list)


class InternalAgentModelConfig(BaseModel):
    """Agent model resource configuration summary."""

    model_config = ConfigDict(extra="forbid")

    default: str | None = None
    provider: str = "openai"
    base_url_env: str | None = None
    api_key_env: str | None = None


class InternalAgentDetailResponse(BaseModel):
    """Detailed response model for `GET /internal/agents/{agent_id}`."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    name: str
    exposed: bool
    root_dir: str
    agents_md: InternalAgentPromptRef
    workspace_agents_md: InternalAgentPromptRef | None = None
    model: InternalAgentModelConfig = Field(default_factory=InternalAgentModelConfig)
    tools: InternalAgentToolsConfig
    skills: InternalAgentSkillsConfig
    sandbox: dict[str, Any] = Field(default_factory=dict)
    multiagent: dict[str, Any] = Field(default_factory=dict)
    mcp: InternalAgentMCPConfig = Field(default_factory=InternalAgentMCPConfig)


class AdminAgentCreateResponse(BaseModel):
    """Response model for `POST /admin/workspace/agents`."""

    model_config = ConfigDict(extra="forbid")

    agent: InternalAgentDetailResponse
    reloaded_agent_ids: list[str] = Field(default_factory=list)


class AdminWorkspaceAgentFile(BaseModel):
    """One editable agent-pack source file exposed to admin control surfaces."""

    model_config = ConfigDict(extra="forbid")

    kind: WorkspaceAgentFileKind
    path: str
    exists: bool
    sha256: str | None = None
    text: str | None = None


class AdminWorkspaceAgentFilesResponse(BaseModel):
    """Response model for `GET /admin/workspace/agents/{agent_id}/files`."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    files: list[AdminWorkspaceAgentFile] = Field(default_factory=list)


class AdminWorkspaceAgentFileUpdateRequest(BaseModel):
    """Request model for updating one editable agent-pack source file."""

    model_config = ConfigDict(extra="forbid")

    text: str
    expected_sha256: str | None = None


class AdminWorkspaceAgentFileUpdateResponse(BaseModel):
    """Response model for `PUT /admin/workspace/agents/{agent_id}/files/{kind}`."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    file: AdminWorkspaceAgentFile
    reloaded_agent_ids: list[str] = Field(default_factory=list)


class AdminAgentCreateRequest(BaseModel):
    """Request model for creating one agent pack from Studio/admin UI."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(min_length=1, max_length=64)
    instructions: str = Field(min_length=1, max_length=64 * 1024)
    exposed: bool = True
    sandbox_mode: SandboxMode = "disabled"
    model_default: str | None = None
    model_provider: str = "openai"
    model_base_url_env: str | None = None
    model_api_key_env: str | None = None
    requested_tool_names: list[str] = Field(default_factory=list)
    default_selected_skills: list[str] = Field(default_factory=list)
    spawn_allow_agent_ids: list[str] = Field(default_factory=list)


class AdminAgentSkillsUpdateRequest(BaseModel):
    """Request model for updating an agent's default selected skills."""

    model_config = ConfigDict(extra="forbid")

    default_selected: list[str] = Field(default_factory=list)


class AdminAgentConfigUpdateRequest(BaseModel):
    """Request model for updating common no-code agent.yaml controls."""

    model_config = ConfigDict(extra="forbid")

    exposed: bool | None = None
    model_default: str | None = None
    model_provider: str | None = None
    model_base_url_env: str | None = None
    model_api_key_env: str | None = None
    requested_tool_names: list[str] | None = None
    sandbox_mode: SandboxMode | None = None
    spawn_allow_agent_ids: list[str] | None = None
    disabled_skill_paths: list[str] | None = None


class AdminSkillImportRequest(BaseModel):
    """Request model for importing one agent-local skill package."""

    model_config = ConfigDict(extra="forbid")

    directory_name: str = Field(min_length=1, max_length=64)
    skill_md: str = Field(min_length=1)
    overwrite: bool = False


class AdminSkillRegistryInstallRequest(BaseModel):
    """Request model for installing one skill from a configured skill channel."""

    model_config = ConfigDict(extra="forbid")

    channel: Literal["skills.sh", "registry", "github"] = "skills.sh"
    package: str = Field(min_length=1, max_length=256)
    skill: str = Field(min_length=1, max_length=128)
    directory_name: str | None = Field(default=None, min_length=1, max_length=64)
    github_repo: str | None = Field(default=None, min_length=1, max_length=256)
    github_ref: str | None = Field(default=None, min_length=1, max_length=128)
    github_path: str | None = Field(default=None, min_length=1, max_length=256)
    overwrite: bool = False


class AdminSkillImportResponse(BaseModel):
    """Response model for `POST /admin/workspace/agents/{agent_id}/skills/import`."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    stable_id: str
    name: str
    path: str
    sha256: str
    reloaded_agent_ids: list[str] = Field(default_factory=list)


class AdminSkillUpdateCheckResponse(BaseModel):
    """Response model for checking one channel-installed agent-local skill."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    directory_name: str
    channel: str | None = None
    source_ref: str | None = None
    current_hash: str | None = None
    latest_hash: str | None = None
    update_available: bool = False
    updatable: bool = False
    reason: str | None = None


class InternalPromptBundlePreviewResponse(BaseModel):
    """Debug response model for one fully assembled prompt bundle preview."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    session_key: str
    model: str | None = None
    prompt_cache_key: str | None = None
    instruction_role: Literal["developer", "system"]
    selected_skill_ids: list[str] = Field(default_factory=list)
    manifest_tools: list[AnyAgentFunctionToolParam] = Field(default_factory=list)
    manifest_tool_names: list[str] = Field(default_factory=list)
    mcp_servers: list[str] = Field(default_factory=list)
    tool_context: dict[str, Any] = Field(default_factory=dict)
    prompt_context: PromptContextAudit
    rendered_fragments: list[RenderedPromptFragment] = Field(default_factory=list)
    effective_body: dict[str, Any] = Field(default_factory=dict)
    applied_body: dict[str, Any] = Field(default_factory=dict)


class PromptRunBundleToolLoopItem(BaseModel):
    """One illustrative tool-loop item included in local run bundle examples."""

    model_config = ConfigDict(extra="forbid")

    phase: Literal["model_function_call", "tool_output_to_model", "assistant_message"]
    item: dict[str, Any] = Field(default_factory=dict)


PromptRunBundleScenario = Literal["sandbox_file_write", "multi_skill_research", "toolset_retry"]


class PromptRunBundleExampleOptions(BaseModel):
    """Options for locally synthesizing one example run bundle."""

    model_config = ConfigDict(extra="forbid")

    skill_count: int | None = Field(default=None, ge=0, le=8)
    include_mcp: bool | None = None
    sandbox_mode: SandboxMode | None = None
    user_input: str | None = None


class PromptRunBundleScenarioDescriptor(BaseModel):
    """Catalog item describing one available local example scenario."""

    model_config = ConfigDict(extra="forbid")

    scenario: PromptRunBundleScenario
    label: str
    summary: str
    supports_mcp_toggle: bool = True
    supports_skill_count: bool = True
    supports_sandbox_override: bool = True
    default_options: PromptRunBundleExampleOptions = Field(default_factory=PromptRunBundleExampleOptions)


class PromptRunBundleExplanationStep(BaseModel):
    """One human-readable step for explaining an illustrative run bundle."""

    model_config = ConfigDict(extra="forbid")

    title: str
    detail: str
    cites: list[str] = Field(default_factory=list)


class PromptRunBundleExplanation(BaseModel):
    """Human-readable explanation attached to a local illustrative run bundle."""

    model_config = ConfigDict(extra="forbid")

    summary: str
    why_this_shape: str
    key_takeaways: list[str] = Field(default_factory=list)
    steps: list[PromptRunBundleExplanationStep] = Field(default_factory=list)


class PromptRunBundleExampleResponse(BaseModel):
    """
    Pure local SDK example for a fully assembled run bundle.

    说明：
    - 不依赖真实服务端、event store 或实际工具执行
    - 用内部构造的 typed 示例数据展示 prompt bundle、tool loop 中间态和最终模型回复
    """

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    session_key: str
    response_id: str
    model: str
    scenario: PromptRunBundleScenario
    scenario_label: str
    options: PromptRunBundleExampleOptions = Field(default_factory=PromptRunBundleExampleOptions)
    prompt_bundle: InternalPromptBundlePreviewResponse
    tool_loop_items: list[PromptRunBundleToolLoopItem] = Field(default_factory=list)
    stage_events: list[StageEvent] = Field(default_factory=list)
    model_response: dict[str, Any] = Field(default_factory=dict)
    explanation: PromptRunBundleExplanation
