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
