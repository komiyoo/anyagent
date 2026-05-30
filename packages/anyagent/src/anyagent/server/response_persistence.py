from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from anyagent.observability import emit_replay_observability_envelope_from_stage_event
from anyagent.persistence.config import PersistenceConfig
from anyagent.protocol.prompt_context import RenderedPromptFragment
from anyagent.protocol.stage_events import AnyAgentPromptContextEvent, AnyAgentPromptContextRenderedEvent

from .finalization import (
    build_nonstream_response_finalizer,
    build_run_final_and_session_persister,
    build_session_snapshot_advancer,
)
from .streaming import build_response_event_appender

ResponsePersistenceWarningHook = Callable[[str], None]


@dataclass(slots=True)
class DistributedResponsePersistenceContext:
    storage: Any
    session_partition_key: str
    agent_id: str
    session_key: str
    previous_snapshot: dict[str, Any] | None
    previous_snapshot_version: int | None
    runtime_config: dict[str, Any]
    request_transcript_items: list[dict[str, Any]] | None
    prompt_audit: Any | None = None
    prompt_rendered_fragments: list[RenderedPromptFragment] | None = None
    warn: ResponsePersistenceWarningHook | None = None

    async def append_internal_event_best_effort(
        self,
        *,
        response_id: str,
        event: str | None,
        data: str,
        tool_call_id: str | None = None,
        tool_name: str | None = None,
    ) -> int | None:
        try:
            seq = await self.storage.event_store.append(
                response_id=response_id,
                session_partition_key=self.session_partition_key,
                event=event,
                data=data,
            )
            if hasattr(self.storage.run_store, "set_last_event_seq"):
                try:
                    await self.storage.run_store.set_last_event_seq(response_id=response_id, last_event_seq=int(seq))
                except Exception as exc:  # noqa: BLE001
                    self._warn(f"set last event seq failed: {exc}")
            return int(seq)
        except Exception as exc:  # noqa: BLE001
            suffix = ""
            if tool_call_id is not None or tool_name is not None:
                suffix = f" tool_call_id={tool_call_id!r} tool_name={tool_name!r}"
            self._warn(f"event append failed: response_id={response_id!r} event={event!r}{suffix}: {exc}")
            return None

    async def stage_sink_best_effort(self, event: Any) -> None:
        response_id = getattr(event, "response_id", None)
        event_type = getattr(event, "type", None)
        if not isinstance(response_id, str) or not response_id.strip():
            return
        if not isinstance(event_type, str) or not event_type.strip():
            return
        try:
            if hasattr(event, "model_dump_json"):
                data = event.model_dump_json(exclude_none=True, by_alias=True)
            else:
                payload = event.model_dump(exclude_none=True) if hasattr(event, "model_dump") else event
                data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        except Exception as exc:  # noqa: BLE001
            self._warn(f"event encode failed: response_id={response_id!r} event={event_type!r}: {exc}")
            return
        seq = await self.append_internal_event_best_effort(
            response_id=response_id,
            event=event_type,
            data=data,
        )
        emit_replay_observability_envelope_from_stage_event(event, seq=seq)

    async def append_prompt_context_event_best_effort(self, response_id: str) -> None:
        if self.prompt_audit is None:
            return
        payload = self.prompt_audit.model_dump(exclude_none=True) if hasattr(self.prompt_audit, "model_dump") else dict(self.prompt_audit)
        await self.stage_sink_best_effort(
            AnyAgentPromptContextEvent.model_validate(
                {
                    "response_id": response_id,
                    "type": "anyagent.prompt.context",
                    **payload,
                }
            )
        )

    async def append_prompt_context_rendered_event_best_effort(self, response_id: str) -> None:
        if not self.prompt_rendered_fragments:
            return
        config = _persistence_config_from_runtime_config(self.runtime_config)
        if not config.persist_rendered_context:
            return
        rendered_fragments = _bounded_rendered_fragments(
            self.prompt_rendered_fragments,
            max_bytes=config.rendered_context_max_bytes,
        )
        if not rendered_fragments:
            return
        prompt_cache_key = getattr(self.prompt_audit, "prompt_cache_key", None)
        total_chars = sum(len(fragment.rendered_text) for fragment in rendered_fragments)
        await self.stage_sink_best_effort(
            AnyAgentPromptContextRenderedEvent(
                response_id=response_id,
                prompt_cache_key=prompt_cache_key if isinstance(prompt_cache_key, str) else None,
                fragments=rendered_fragments,
                total_chars=total_chars,
            )
        )

    async def finalize_nonstream_persisted(
        self,
        *,
        run_response_id: str,
        response_json: dict[str, Any] | None,
        effective_status: str | None,
        error_json: dict[str, Any] | None,
        resume_last_response_id: str | None,
        error_event_data: str | None = None,
    ) -> None:
        append_event = build_response_event_appender(
            response_id=run_response_id,
            writer=lambda rid, event, data: self.append_internal_event_best_effort(
                response_id=rid,
                event=event,
                data=data,
            ),
        )
        finalize_persisted_response = build_nonstream_response_finalizer(
            response_id=run_response_id,
            append_event=append_event,
            persist_run_final=self.build_run_final_persister(run_response_id),
            resume_last_response_id=resume_last_response_id,
        )
        await finalize_persisted_response(
            response_json=response_json,
            effective_status=effective_status,
            error_json=error_json,
            error_event_data=error_event_data,
        )

    async def advance_nonstream_session_only(
        self,
        *,
        run_response_id: str | None,
        response_json: dict[str, Any] | None,
        effective_status: str | None,
        resume_last_response_id: str | None,
    ) -> None:
        finalize_session_only = build_nonstream_response_finalizer(
            response_id=run_response_id,
            advance_session=self.build_session_snapshot_advancer(),
            append_completed_event=False,
            append_done_sentinel=False,
            resume_last_response_id=resume_last_response_id,
        )
        await finalize_session_only(
            response_json=response_json,
            effective_status=effective_status,
        )

    def build_run_final_persister(self, response_id: str):
        return build_run_final_and_session_persister(
            run_store=self.storage.run_store,
            session_store=self.storage.session_store,
            session_partition_key=self.session_partition_key,
            agent_id=self.agent_id,
            session_key=self.session_key,
            previous_snapshot=self.previous_snapshot,
            previous_snapshot_version=self.previous_snapshot_version,
            runtime_config=self.runtime_config,
            request_transcript_items=self.request_transcript_items,
            prompt_audit=self.prompt_audit,
            response_id_resolver=lambda _state, rid=response_id: rid,
            warn=self.warn,
        )

    def build_session_snapshot_advancer(self):
        return build_session_snapshot_advancer(
            session_store=self.storage.session_store,
            session_partition_key=self.session_partition_key,
            agent_id=self.agent_id,
            session_key=self.session_key,
            previous_snapshot=self.previous_snapshot,
            previous_snapshot_version=self.previous_snapshot_version,
            runtime_config=self.runtime_config,
            request_transcript_items=self.request_transcript_items,
            prompt_audit=self.prompt_audit,
            warn=self.warn,
        )

    def _warn(self, message: str) -> None:
        if self.warn is not None:
            self.warn(message)


def create_distributed_response_persistence_context(
    *,
    storage: Any,
    session_partition_key: str,
    agent_id: str,
    session_key: str,
    previous_snapshot: dict[str, Any] | None,
    previous_snapshot_version: int | None,
    runtime_config: dict[str, Any],
    request_transcript_items: list[dict[str, Any]] | None,
    prompt_audit: Any | None = None,
    prompt_rendered_fragments: list[RenderedPromptFragment] | None = None,
    warn: ResponsePersistenceWarningHook | None = None,
) -> DistributedResponsePersistenceContext:
    return DistributedResponsePersistenceContext(
        storage=storage,
        session_partition_key=session_partition_key,
        agent_id=agent_id,
        session_key=session_key,
        previous_snapshot=previous_snapshot,
        previous_snapshot_version=previous_snapshot_version,
        runtime_config=runtime_config,
        request_transcript_items=request_transcript_items,
        prompt_audit=prompt_audit,
        prompt_rendered_fragments=prompt_rendered_fragments,
        warn=warn,
    )


def _persistence_config_from_runtime_config(runtime_config: dict[str, Any]) -> PersistenceConfig:
    raw = runtime_config.get("observability") if isinstance(runtime_config, dict) else None
    if not isinstance(raw, dict):
        return PersistenceConfig()
    payload: dict[str, Any] = {}
    if "persist_rendered_context" in raw:
        payload["persist_rendered_context"] = raw.get("persist_rendered_context")
    if "rendered_context_max_bytes" in raw:
        payload["rendered_context_max_bytes"] = raw.get("rendered_context_max_bytes")
    return PersistenceConfig.model_validate(payload)


def _bounded_rendered_fragments(
    fragments: list[RenderedPromptFragment],
    *,
    max_bytes: int,
) -> list[RenderedPromptFragment]:
    if max_bytes <= 0:
        return []
    out = [fragment.model_copy(deep=True) for fragment in fragments]
    while out and _rendered_fragments_size(out) > max_bytes:
        out.pop()
    if out:
        return out
    first = fragments[0].model_copy(deep=True)
    metadata = dict(first.metadata or {})
    metadata["truncated"] = "true"
    first.metadata = metadata
    first.rendered_text = ""
    return [first] if _rendered_fragments_size([first]) <= max_bytes else []


def _rendered_fragments_size(fragments: list[RenderedPromptFragment]) -> int:
    payload = [fragment.model_dump(mode="json", exclude_none=True) for fragment in fragments]
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
