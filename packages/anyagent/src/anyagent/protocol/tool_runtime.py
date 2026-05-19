from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .openai_responses import AnyAgentFunctionToolParam


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


class ToolContext(BaseModel):
    """
    v0 标准化 context（平台无关 + 平台扩展）：
    - v0 允许 extra（例如 future fields），但对已知字段提供结构化校验。
    - token/secret 禁止直接放入 context，必须走 auth_ref 引用（服务端再次收口）。
    """

    model_config = ConfigDict(extra="allow")

    trace: TraceContext | None = None
    requester: RequesterContext | None = None
    channel: ChannelContext | None = None
    auth_ref: AuthRef | None = None
    policy: PolicyHint | None = None

    @model_validator(mode="before")
    @classmethod
    def _reject_plaintext_secrets(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        forbidden = _find_plaintext_secret_path(data)
        if forbidden is not None:
            raise ValueError(f"tool context must reference credentials via auth_ref, not plaintext secret field: {forbidden}")
        return data


class ManifestRequest(BaseModel):
    tenant_id: str | None = None
    agent_id: str | None = None
    session_key: str | None = None
    context: ToolContext = Field(default_factory=ToolContext)

    enabled_skills: list[str] | None = None
    requested_tool_names: list[str] | None = None
    requested_tools: list[dict[str, Any]] | None = None


_PLAINTEXT_SECRET_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "bearer_token",
    "credential_value",
    "password",
    "refresh_token",
    "secret",
    "token",
}
_PLAINTEXT_SECRET_SUFFIXES = ("_api_key", "_apikey", "_password", "_refresh_token", "_secret", "_token")


def _find_plaintext_secret_path(value: Any, *, prefix: str = "") -> str | None:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                continue
            path = f"{prefix}.{key}" if prefix else key
            normalized = key.lower().replace("-", "_")
            if normalized in {"auth_ref", "credential_id"}:
                continue
            if normalized in _PLAINTEXT_SECRET_KEYS or normalized.endswith(_PLAINTEXT_SECRET_SUFFIXES):
                return path
            nested = _find_plaintext_secret_path(item, prefix=path)
            if nested is not None:
                return nested
    elif isinstance(value, list):
        for index, item in enumerate(value):
            nested = _find_plaintext_secret_path(item, prefix=f"{prefix}[{index}]")
            if nested is not None:
                return nested
    return None


class ManifestDecision(BaseModel):
    tool_name: str
    decision: Literal["allow", "deny"]
    reason: str


class ManifestResponse(BaseModel):
    tools: list[AnyAgentFunctionToolParam]
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
    context: ToolContext = Field(default_factory=ToolContext)


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


class CancelRequest(BaseModel):
    tenant_id: str | None = None
    agent_id: str | None = None
    session_key: str | None = None
    response_id: str
    tool_call_id: str
    tool_name: str | None = None


class CancelResponse(BaseModel):
    ok: bool
