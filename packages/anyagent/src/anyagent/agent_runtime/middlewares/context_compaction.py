from __future__ import annotations

import time
from typing import Any

from anyagent.agent_runtime.middleware import BaseMiddleware, BeforeModelResult, MiddlewareContext
from anyagent.protocol.stage_events import AnyAgentContextCompactedEvent, summarize_payload

from ._token_estimate import estimate_tokens


class ContextCompactionMiddleware(BaseMiddleware):
    def __init__(
        self,
        *,
        max_context_tokens: int = 128_000,
        trigger_ratio: float = 0.8,
        keep_recent_tokens: int = 20_000,
    ) -> None:
        self.max_context_tokens = max(1, max_context_tokens)
        self.trigger_tokens = max(1, int(self.max_context_tokens * trigger_ratio))
        self.keep_recent_tokens = max(1, keep_recent_tokens)

    async def before_model_call(self, context: MiddlewareContext, body: dict[str, Any]) -> BeforeModelResult:
        if context.iter_index <= 0:
            return BeforeModelResult()
        input_items = body.get("input")
        if not isinstance(input_items, list):
            if body.get("previous_response_id") is not None:
                await self._emit_skipped(context=context, reason="stateful")
            return BeforeModelResult()
        if body.get("previous_response_id") is not None:
            await self._emit_skipped(context=context, reason="stateful")
            return BeforeModelResult()

        tokens_before = estimate_tokens(input_items)
        if tokens_before < self.trigger_tokens:
            return BeforeModelResult()

        split_at = _find_split_index(input_items, keep_recent_tokens=self.keep_recent_tokens)
        if split_at <= 0:
            return BeforeModelResult()
        old_items = input_items[:split_at]
        recent_items = input_items[split_at:]
        summary_text = await _build_summary(
            context=context,
            body=body,
            previous_summary=context.state.get("context_compaction.summary"),
            old_items=old_items,
        )
        context.state["context_compaction.summary"] = summary_text
        summary_item = {
            "role": "developer",
            "content": (
                "Compressed prior conversation and tool context. Use this as continuity state:\n\n"
                f"{summary_text}"
            ),
        }
        next_items = [summary_item, *recent_items]
        tokens_after = estimate_tokens(next_items)
        next_body = dict(body)
        next_body["input"] = next_items
        await self._emit_compacted(
            context=context,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            items_before=len(input_items),
            items_after=len(next_items),
            summary=summary_text,
        )
        return BeforeModelResult(body=next_body)

    async def _emit_skipped(self, *, context: MiddlewareContext, reason: str) -> None:
        if context.stage_event_sink is None:
            return
        key = f"context_compaction.skipped.{context.iter_index}.{reason}"
        if context.state.get(key):
            return
        context.state[key] = True
        await context.stage_event_sink(
            AnyAgentContextCompactedEvent(
                response_id=context.canonical_response_id or context.response_id or "resp_anyagent",
                tokens_before=0,
                tokens_after=0,
                items_before=0,
                items_after=0,
                skipped=True,
                reason=reason,
                ts_ms=int(time.time() * 1000),
            )
        )

    async def _emit_compacted(
        self,
        *,
        context: MiddlewareContext,
        tokens_before: int,
        tokens_after: int,
        items_before: int,
        items_after: int,
        summary: str,
    ) -> None:
        if context.stage_event_sink is None:
            return
        await context.stage_event_sink(
            AnyAgentContextCompactedEvent(
                response_id=context.canonical_response_id or context.response_id or "resp_anyagent",
                tokens_before=tokens_before,
                tokens_after=tokens_after,
                items_before=items_before,
                items_after=items_after,
                summary=summarize_payload(summary),
                ts_ms=int(time.time() * 1000),
            )
        )


def _find_split_index(input_items: list[Any], *, keep_recent_tokens: int) -> int:
    total = 0
    split_at = 0
    for idx in range(len(input_items) - 1, -1, -1):
        total += estimate_tokens(input_items[idx])
        if total >= keep_recent_tokens:
            split_at = idx
            break
    split_at = _move_split_away_from_tool_pair(input_items, split_at)
    return split_at


def _move_split_away_from_tool_pair(input_items: list[Any], split_at: int) -> int:
    if split_at <= 0 or split_at >= len(input_items):
        return split_at
    before = input_items[split_at - 1]
    after = input_items[split_at]
    if not isinstance(before, dict) or not isinstance(after, dict):
        return split_at
    if before.get("type") == "function_call" and after.get("type") == "function_call_output":
        before_call_id = before.get("call_id")
        after_call_id = after.get("call_id")
        if isinstance(before_call_id, str) and before_call_id == after_call_id:
            return max(0, split_at - 1)
    return split_at


async def _build_summary(
    *,
    context: MiddlewareContext,
    body: dict[str, Any],
    previous_summary: Any,
    old_items: list[Any],
) -> str:
    local_summary = _build_local_summary(previous_summary=previous_summary, old_items=old_items)
    model_provider = context.model_provider
    if model_provider is None or not hasattr(model_provider, "create_response"):
        return local_summary
    summary_body: dict[str, Any] = {
        "input": [
            {
                "role": "developer",
                "content": (
                    "Summarize compacted agent context for handoff. Preserve progress, decisions, "
                    "open blockers, tool results, and next steps. Do not include secrets."
                ),
            },
            {
                "role": "user",
                "content": local_summary[:12_000],
            },
        ],
        "stream": False,
    }
    if isinstance(body.get("model"), str) and body["model"].strip():
        summary_body["model"] = body["model"].strip()
    try:
        response = await model_provider.create_response(body=summary_body, idempotency_key=None)
    except Exception:  # noqa: BLE001
        return local_summary
    model_summary = _extract_response_text(response.model_dump(exclude_none=True, by_alias=True))
    return model_summary.strip() or local_summary


def _build_local_summary(*, previous_summary: Any, old_items: list[Any]) -> str:
    lines: list[str] = []
    if isinstance(previous_summary, str) and previous_summary.strip():
        lines.append("Previous summary:")
        lines.append(previous_summary.strip()[:4000])
    lines.append(f"Compacted {len(old_items)} older input item(s).")
    text_fragments: list[str] = []
    tool_names: list[str] = []
    for item in old_items[-24:]:
        if isinstance(item, dict):
            if item.get("type") == "function_call" and isinstance(item.get("name"), str):
                tool_names.append(item["name"])
            content = item.get("content")
            if isinstance(content, str):
                text_fragments.append(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        text_fragments.append(part["text"])
        elif isinstance(item, str):
            text_fragments.append(item)
    if tool_names:
        lines.append("Recent compacted tools: " + ", ".join(tool_names[-12:]))
    if text_fragments:
        snippet = "\n".join(fragment.strip() for fragment in text_fragments if fragment.strip())
        if snippet:
            lines.append("Recent compacted text:")
            lines.append(snippet[:6000])
    lines.append("Continue from the uncompressed recent items that follow this summary.")
    return "\n".join(lines)


def _extract_response_text(payload: dict[str, Any]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str):
        return output_text
    chunks: list[str] = []
    output = payload.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    chunks.append(part["text"])
    return "".join(chunks)
