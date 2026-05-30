from __future__ import annotations

import json

from anyagent.observability import (
    FileJsonlReplaySink,
    ReplayObservabilityEnvelope,
    build_replay_observability_envelope,
)
from anyagent.protocol.stage_events import AnyAgentModelRequestEvent, AnyAgentPromptContextRenderedEvent


def test_build_replay_observability_envelope_redacts_model_request_secrets() -> None:
    event = AnyAgentModelRequestEvent(
        response_id="resp_redact",
        applied_body={
            "model": "gpt-test",
            "Authorization": "Bearer secret",
            "metadata": {"credential_id": "cred-openai", "safe": "ok"},
        },
        prompt_cache_key="cache-redact",
    )

    envelope = build_replay_observability_envelope(event, seq=7)

    assert envelope is not None
    assert envelope.category == "model_request"
    assert envelope.seq == 7
    assert envelope.payload["applied_body"]["Authorization"] == "[REDACTED]"
    assert envelope.payload["applied_body"]["metadata"]["credential_id"] == "[REDACTED]"
    assert envelope.payload["applied_body"]["metadata"]["safe"] == "ok"


def test_build_replay_observability_envelope_ignores_non_replay_events() -> None:
    assert build_replay_observability_envelope({"type": "anyagent.tool.planned", "response_id": "resp_1"}) is None


def test_file_jsonl_replay_sink_appends_envelopes(tmp_path) -> None:
    path = tmp_path / "replay.jsonl"
    sink = FileJsonlReplaySink(path)
    envelope = build_replay_observability_envelope(
        AnyAgentPromptContextRenderedEvent(response_id="resp_file", fragments=[], total_chars=0),
        seq=1,
    )

    assert envelope is not None
    sink.emit(envelope)

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert rows == [
        ReplayObservabilityEnvelope.model_validate(
            {
                "schema_version": "2026-05-30",
                "source": "event_store",
                "category": "prompt_context",
                "event_type": "anyagent.prompt.context.rendered",
                "response_id": "resp_file",
                "seq": 1,
                "payload": {
                    "type": "anyagent.prompt.context.rendered",
                    "response_id": "resp_file",
                    "fragments": [],
                    "total_chars": 0,
                },
            }
        ).model_dump(exclude_none=True)
    ]
