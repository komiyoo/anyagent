from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class TraceContext(BaseModel):
    trace_id: str | None = None
    span_id: str | None = None


class RequesterContext(BaseModel):
    id: str | None = None
    display_name: str | None = None
    is_owner: bool | None = None


class ChannelContext(BaseModel):
    provider: str | None = None
    account_id: str | None = None
    chat_id: str | None = None
    thread_id: str | None = None
    message_id: str | None = None
    ext: dict[str, Any] | None = None


class AuthRef(BaseModel):
    kind: str | None = None
    ref: str | None = None


class PolicyHint(BaseModel):
    allow_tools: list[str] | None = None
    deny_tools: list[str] | None = None


class Context(BaseModel):
    """
    v0 标准化 context（平台无关 + 平台扩展）。
    - 允许 extra（channel.ext / future fields），但对已知字段提供结构化校验。
    """

    model_config = ConfigDict(extra="allow")

    trace: TraceContext | None = None
    requester: RequesterContext | None = None
    channel: ChannelContext | None = None
    auth_ref: AuthRef | None = None
    policy: PolicyHint | None = None


class ManifestRequest(BaseModel):
    tenant_id: str | None = None
    agent_id: str | None = None
    session_key: str | None = None
    context: Context = Field(default_factory=Context)

    enabled_skills: list[str] | None = None
    requested_tool_names: list[str] | None = None
    requested_tools: list[dict[str, Any]] | None = None


class ManifestDecision(BaseModel):
    tool_name: str
    decision: Literal["allow", "deny"]
    reason: str


class ManifestResponse(BaseModel):
    tools: list[dict[str, Any]]
    toolset_version: int
    decisions: list[ManifestDecision] | None = None


class ToolError(BaseModel):
    type: str
    code: str
    message: str
    retryable: bool = False


class ExecuteRequest(BaseModel):
    tenant_id: str | None = None
    agent_id: str
    session_key: str
    response_id: str
    tool_call_id: str
    tool_name: str
    arguments_json: Any
    deadline_ms: int | None = Field(default=None, ge=1, le=600_000)
    toolset_version: int | None = Field(default=None, ge=1)
    context: Context = Field(default_factory=Context)


class ExecuteMeta(BaseModel):
    duration_ms: int = 0
    output_truncated: bool = False
    audit_ref: str | None = None


class ExecuteResponseCompleted(BaseModel):
    status: Literal["completed"]
    output: str
    meta: ExecuteMeta


class ExecuteResponseCancelled(BaseModel):
    status: Literal["cancelled"]
    error: ToolError
    meta: ExecuteMeta


class ExecuteResponseError(BaseModel):
    status: Literal["error"]
    error: ToolError
    meta: ExecuteMeta


ExecuteResponse = ExecuteResponseCompleted | ExecuteResponseCancelled | ExecuteResponseError
