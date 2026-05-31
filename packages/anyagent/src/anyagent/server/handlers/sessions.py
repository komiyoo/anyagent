from __future__ import annotations

from typing import Any

from anyagent.gateway.session import session_partition_key
from anyagent.protocol.agent_api_internal import InternalObservabilityRunItem, InternalSessionSummary


def _summarize_session_runs(records: list[Any]) -> list[InternalSessionSummary]:
    grouped: dict[tuple[str, str], list[Any]] = {}
    for record in records:
        agent_id = str(getattr(record, "agent_id", "") or "")
        session_key_value = str(getattr(record, "session_key", "") or "")
        if not agent_id or not session_key_value:
            continue
        grouped.setdefault((agent_id, session_key_value), []).append(record)

    summaries: list[InternalSessionSummary] = []
    for (agent_id, session_key_value), session_records in grouped.items():
        ordered = sorted(
            session_records,
            key=lambda item: int(getattr(item, "updated_at_ms", 0) or 0),
            reverse=True,
        )
        latest = ordered[0]
        statuses = [str(getattr(item, "effective_status", getattr(item, "status", "")) or "") for item in ordered]
        summaries.append(
            InternalSessionSummary(
                agent_id=agent_id,
                session_key=session_key_value,
                session_partition_key=session_partition_key(agent_id=agent_id, session_key=session_key_value),
                run_count=len(ordered),
                active_run_count=sum(1 for status in statuses if status in {"in_progress", "queued", "started"}),
                error_run_count=sum(1 for status in statuses if status in {"failed", "errored", "error"}),
                latest_response_id=str(getattr(latest, "response_id", "") or "") or None,
                latest_status=str(getattr(latest, "status", "") or "") or None,
                latest_effective_status=str(getattr(latest, "effective_status", getattr(latest, "status", "")) or "") or None,
                created_at_ms=min(int(getattr(item, "created_at_ms", 0) or 0) for item in ordered),
                updated_at_ms=max(int(getattr(item, "updated_at_ms", 0) or 0) for item in ordered),
            )
        )
    summaries.sort(key=lambda item: item.updated_at_ms, reverse=True)
    return summaries


def _internal_run_item(record: Any) -> InternalObservabilityRunItem:
    return InternalObservabilityRunItem(
        response_id=str(getattr(record, "response_id", "")),
        agent_id=str(getattr(record, "agent_id", "")),
        session_key=str(getattr(record, "session_key", "")),
        stream=bool(getattr(record, "stream", False)),
        status=str(getattr(record, "status", "")),
        effective_status=str(getattr(record, "effective_status", getattr(record, "status", ""))),
        created_at_ms=int(getattr(record, "created_at_ms", 0) or 0),
        updated_at_ms=int(getattr(record, "updated_at_ms", 0) or 0),
        ended_at_ms=int(getattr(record, "ended_at_ms")) if getattr(record, "ended_at_ms", None) is not None else None,
    )
