from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from anyagent.config.agents import AgentCatalog, AgentPack
from anyagent.agent_runtime.multiagent import stable_root_thread_id
from anyagent.gateway.session import SessionBindingError
from anyagent.gateway.session import session_partition_key as build_session_partition_key


def resolve_agent_id(
    *,
    metadata: Mapping[str, Any] | None,
    x_agent_id: str | None = None,
    model: Any = None,
    default: str = "main",
) -> str:
    if isinstance(metadata, Mapping):
        value = metadata.get("agent_id")
        if isinstance(value, str) and value.strip():
            return value.strip()
    if isinstance(x_agent_id, str) and x_agent_id.strip():
        return x_agent_id.strip()
    if isinstance(model, str) and model.startswith("agent:") and model[6:].strip():
        return model[6:].strip()
    return default


def resolve_session_key(
    *,
    metadata: Mapping[str, Any] | None,
    user: Any = None,
    ephemeral_prefix: str = "ephemeral:",
) -> str:
    if isinstance(metadata, Mapping):
        value = metadata.get("session_key")
        if isinstance(value, str) and value.strip():
            return value.strip()
    if isinstance(user, str) and user.strip():
        return user.strip()
    return f"{ephemeral_prefix}{uuid.uuid4().hex}"


def resolve_optional_session_key(*, metadata: Mapping[str, Any] | None) -> str | None:
    if isinstance(metadata, Mapping):
        value = metadata.get("session_key")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


@dataclass(frozen=True)
class ResponsesRequestContext:
    body: dict[str, Any]
    metadata: dict[str, Any] | None
    agent_id: str
    pack: AgentPack
    session_key: str
    session_partition_key: str
    stream: bool
    root_thread_id: str
    thread_id: str
    thread_depth: int
    idempotency_key: str | None


class ResponsesRequestContextError(Exception):
    def __init__(
        self,
        status_code: int,
        *,
        message: str,
        type_: str = "invalid_request_error",
        code: str | None = None,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.type = type_
        self.code = code
        self.retryable = retryable


def _get_header(headers: Mapping[str, Any], name: str) -> str | None:
    value = headers.get(name)
    if value is None:
        value = headers.get(name.lower())
    if value is None:
        value = headers.get(name.title())
    return value if isinstance(value, str) else None


def prepare_responses_request_context(
    *,
    body: dict[str, Any],
    metadata: dict[str, Any] | None,
    headers: Mapping[str, Any],
    catalog: AgentCatalog,
    ephemeral_session_key_factory: Any | None = None,
    idempotency_key_max_len: int = 256,
) -> ResponsesRequestContext:
    agent_id = resolve_agent_id(
        metadata=metadata,
        x_agent_id=_get_header(headers, "x-agent-id"),
    )

    pack = catalog.get(agent_id)
    if pack is None:
        raise ResponsesRequestContextError(
            404,
            message=f"unknown agent_id: {agent_id}",
            type_="invalid_request_error",
        )
    if not pack.spec.exposed:
        raise ResponsesRequestContextError(
            403,
            message=f"agent_id not exposed: {agent_id}",
            type_="invalid_request_error",
        )

    if not isinstance(body.get("model"), str) or not body.get("model", "").strip():
        default_model = getattr(pack.spec.model, "default", None)
        if isinstance(default_model, str) and default_model.strip():
            body["model"] = default_model.strip()

    session_key = resolve_optional_session_key(metadata=metadata)
    if session_key is None:
        if ephemeral_session_key_factory is None:
            session_key = f"ephemeral::{uuid.uuid4().hex}"
        else:
            session_key = str(ephemeral_session_key_factory())

    try:
        session_partition_key = build_session_partition_key(agent_id=agent_id, session_key=session_key)
    except SessionBindingError as e:
        raise ResponsesRequestContextError(
            400,
            message=str(e),
            type_="invalid_request_error",
        ) from e

    stream = bool(body.get("stream") is True)
    root_thread_id = stable_root_thread_id(session_partition_key)
    thread_id = root_thread_id
    thread_depth = 0
    if isinstance(metadata, Mapping):
        mtid = metadata.get("thread_id")
        if isinstance(mtid, str) and mtid.strip():
            thread_id = mtid.strip()
        mdepth = metadata.get("thread_depth")
        if isinstance(mdepth, int) and mdepth >= 0:
            thread_depth = mdepth

    idem_raw = _get_header(headers, "idempotency-key")
    idempotency_key = idem_raw.strip() if isinstance(idem_raw, str) else ""
    idempotency_key = idempotency_key if idempotency_key else None
    if idempotency_key is not None and len(idempotency_key) > idempotency_key_max_len:
        raise ResponsesRequestContextError(
            400,
            message=f"Idempotency-Key too long (max {idempotency_key_max_len})",
            type_="invalid_request_error",
        )

    return ResponsesRequestContext(
        body=body,
        metadata=metadata,
        agent_id=agent_id,
        pack=pack,
        session_key=session_key,
        session_partition_key=session_partition_key,
        stream=stream,
        root_thread_id=root_thread_id,
        thread_id=thread_id,
        thread_depth=thread_depth,
        idempotency_key=idempotency_key,
    )
