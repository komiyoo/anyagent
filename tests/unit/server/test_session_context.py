from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from anyagent.server.session_context import build_developer_prompt_body, prepare_response_session_context


@dataclass(slots=True)
class _SessionRecord:
    session_partition_key: str
    agent_id: str
    session_key: str
    snapshot_json: dict[str, Any]
    snapshot_version: int


class _SessionStore:
    def __init__(self, record: _SessionRecord | None = None) -> None:
        self.record = record
        self.created: _SessionRecord | None = None

    async def get(self, *, session_partition_key: str) -> _SessionRecord | None:
        if self.record is not None and self.record.session_partition_key == session_partition_key:
            return self.record
        return self.created

    async def create_if_absent(self, *, session_partition_key: str, agent_id: str, session_key: str, snapshot_json: dict) -> _SessionRecord:
        self.created = _SessionRecord(
            session_partition_key=session_partition_key,
            agent_id=agent_id,
            session_key=session_key,
            snapshot_json=snapshot_json,
            snapshot_version=0,
        )
        return self.created


def test_prepare_response_session_context_wraps_prepare_session_request() -> None:
    async def _run() -> None:
        store = _SessionStore(
            _SessionRecord(
                session_partition_key="main::sess",
                agent_id="main",
                session_key="sess",
                snapshot_json={
                    "provider": "openai_responses",
                    "runtime_config": {"model": "gpt-4.1-mini", "temperature": 0.2},
                    "resume_cursor": {"last_response_id": "resp_prev", "fallback_transcript_items": []},
                },
                snapshot_version=3,
            )
        )
        ctx = await prepare_response_session_context(
            session_store=store,
            session_partition_key="main::sess",
            agent_id="main",
            session_key="sess",
            body={"input": "hello", "temperature": 0.7},
        )
        assert ctx.previous_snapshot_version == 3
        assert ctx.effective_runtime_config == {"model": "gpt-4.1-mini", "temperature": 0.7}
        assert ctx.effective_body["previous_response_id"] == "resp_prev"
        assert ctx.request_transcript_items == [{"role": "user", "content": "hello"}]

    asyncio.run(_run())


def test_build_developer_prompt_body_injects_before_user_content() -> None:
    body = {"input": [{"role": "user", "content": "hello"}]}
    out = build_developer_prompt_body(body=body, developer_text="follow the pack")
    assert out["input"][0] == {"role": "developer", "content": "follow the pack"}
    assert out["input"][1] == {"role": "user", "content": "hello"}
