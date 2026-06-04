from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from typing import Any

from anyagent.agent_runtime import PreparedSessionRequest, input_to_transcript_items, prepare_session_request
from anyagent.protocol.context_fragments import ContextFragment, render_context_fragment
from anyagent.protocol.openai_responses import inject_text_into_responses_body


SESSION_ONCE_CONTEXT_KINDS = frozenset({"business_context", "channel_context", "page_context"})


@dataclass(slots=True, frozen=True)
class PreparedResponseSessionContext:
    previous_snapshot: dict[str, Any]
    previous_snapshot_version: int | None
    effective_runtime_config: dict[str, Any]
    request_transcript_items: list[dict[str, Any]]
    effective_body: dict[str, Any]

    @classmethod
    def from_prepared(cls, prepared: PreparedSessionRequest) -> PreparedResponseSessionContext:
        return cls(
            previous_snapshot=prepared.previous_snapshot,
            previous_snapshot_version=prepared.previous_snapshot_version,
            effective_runtime_config=prepared.effective_runtime_config,
            request_transcript_items=prepared.request_transcript_items,
            effective_body=prepared.effective_body,
        )


async def prepare_response_session_context(
    *,
    session_store: Any,
    session_partition_key: str,
    agent_id: str,
    session_key: str,
    body: dict[str, Any],
) -> PreparedResponseSessionContext:
    prepared = await prepare_session_request(
        session_store=session_store,
        session_partition_key=session_partition_key,
        agent_id=agent_id,
        session_key=session_key,
        body=body,
    )
    return PreparedResponseSessionContext.from_prepared(prepared)


def build_developer_prompt_body(*, body: dict[str, Any], developer_text: str) -> dict[str, Any]:
    return inject_text_into_responses_body(body=body, text=developer_text, role="developer")


def split_session_once_context_fragments(
    fragments: list[ContextFragment] | None,
) -> tuple[list[ContextFragment], list[ContextFragment]]:
    session_once: list[ContextFragment] = []
    prompt_envelope: list[ContextFragment] = []
    for fragment in fragments or []:
        (session_once if fragment.kind in SESSION_ONCE_CONTEXT_KINDS else prompt_envelope).append(fragment)
    return session_once, prompt_envelope


def apply_session_once_context_to_body(
    *,
    body: dict[str, Any],
    previous_snapshot: dict[str, Any] | None,
    fragments: list[ContextFragment] | None,
) -> dict[str, Any]:
    texts = _new_session_once_context_texts(
        previous_snapshot=previous_snapshot,
        fragments=fragments,
    )
    if not texts:
        return body
    out = dict(body)
    input_value = out.get("input")
    request_items = input_to_transcript_items(input_value)
    context_messages = [{"role": "assistant", "content": text} for text in texts]
    if isinstance(input_value, str):
        out["input"] = [*context_messages, {"role": "user", "content": input_value}]
        return out
    if input_value is None:
        out["input"] = context_messages
        return out
    if isinstance(input_value, list):
        out["input"] = [*context_messages, *request_items]
        return out
    return body


def apply_session_once_context_to_session(
    *,
    session_ctx: PreparedResponseSessionContext,
    fragments: list[ContextFragment] | None,
) -> PreparedResponseSessionContext:
    effective_body = apply_session_once_context_to_body(
        body=session_ctx.effective_body,
        previous_snapshot=session_ctx.previous_snapshot,
        fragments=fragments,
    )
    if effective_body is session_ctx.effective_body:
        return session_ctx
    return replace(
        session_ctx,
        effective_body=effective_body,
        request_transcript_items=input_to_transcript_items(effective_body.get("input")),
    )


def _new_session_once_context_texts(
    *,
    previous_snapshot: dict[str, Any] | None,
    fragments: list[ContextFragment] | None,
) -> list[str]:
    previous_text = "\n\n".join(
        item.get("content", "")
        for item in input_to_transcript_items(
            ((previous_snapshot or {}).get("resume_cursor") or {}).get("fallback_transcript_items")
            if isinstance((previous_snapshot or {}).get("resume_cursor"), dict)
            else []
        )
        if isinstance(item, dict) and isinstance(item.get("content"), str)
    )
    out: list[str] = []
    for fragment in fragments or []:
        text = render_context_fragment(fragment).strip()
        if not text:
            continue
        stable_id = fragment.stable_id if isinstance(fragment.stable_id, str) and fragment.stable_id.strip() else None
        if stable_id is not None and stable_id in previous_text:
            continue
        if text in previous_text:
            continue
        out.append(text)
    return out
