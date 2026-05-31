from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from anyagent.agent_runtime import PreparedSessionRequest, prepare_session_request
from anyagent.protocol.openai_responses import inject_text_into_responses_body


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
