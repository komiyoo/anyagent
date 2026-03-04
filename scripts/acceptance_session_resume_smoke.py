from __future__ import annotations

import json
import tempfile

from anyagent_agent_api.settings import Settings
from anyagent_agent_api.storage.runtime import create_storage_runtime


_MANAGED_RUNTIME_FIELDS = (
    "model",
    "temperature",
    "top_p",
    "frequency_penalty",
    "presence_penalty",
    "reasoning",
)


def _json_clone(value):
    return json.loads(json.dumps(value, ensure_ascii=False))


def _extract_runtime_updates_from_request(body: dict) -> dict:
    out: dict = {}
    for key in _MANAGED_RUNTIME_FIELDS:
        if key in body:
            out[key] = _json_clone(body.get(key))
    return out


def _merge_runtime_config(*, base_runtime_config: dict, explicit_updates: dict) -> dict:
    merged = _json_clone(base_runtime_config if isinstance(base_runtime_config, dict) else {})
    for key, value in explicit_updates.items():
        merged[key] = _json_clone(value)
    return merged


def _apply_runtime_config_to_body(*, body: dict, runtime_config: dict) -> dict:
    out = dict(body)
    for key in _MANAGED_RUNTIME_FIELDS:
        if key in runtime_config:
            out[key] = _json_clone(runtime_config[key])
        else:
            out.pop(key, None)
    return out


def _build_initial_session_snapshot(*, runtime_config: dict) -> dict:
    return {
        "provider": "openai_responses",
        "runtime_config": _json_clone(runtime_config),
        "resume_cursor": {"last_response_id": None, "fallback_transcript_items": []},
    }


def _apply_session_resume_to_body(*, body: dict, session_snapshot: dict) -> tuple[dict, str | None]:
    out = dict(body)
    prev = out.get("previous_response_id")
    if isinstance(prev, str) and prev.strip():
        return out, prev.strip()

    resume_cursor = session_snapshot.get("resume_cursor")
    if not isinstance(resume_cursor, dict):
        return out, None
    last_response_id = resume_cursor.get("last_response_id")
    if isinstance(last_response_id, str) and last_response_id.strip():
        out["previous_response_id"] = last_response_id.strip()
        return out, last_response_id.strip()
    return out, None


def _build_next_session_snapshot(
    *,
    previous_snapshot: dict,
    runtime_config: dict,
    resume_last_response_id: str | None,
    run_response_id: str | None,
    last_event_seq: int | None,
) -> dict:
    import time

    out = _json_clone(previous_snapshot if isinstance(previous_snapshot, dict) else {})
    out["provider"] = "openai_responses"
    out["runtime_config"] = _json_clone(runtime_config)
    resume = out.get("resume_cursor")
    if not isinstance(resume, dict):
        resume = {}
    if isinstance(resume_last_response_id, str) and resume_last_response_id.strip():
        resume["last_response_id"] = resume_last_response_id.strip()
    out["resume_cursor"] = resume
    out["last_run"] = {
        "response_id": run_response_id,
        "last_event_seq": int(last_event_seq) if isinstance(last_event_seq, int) else 0,
        "updated_at_ms": int(time.time() * 1000),
    }
    return out


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


async def _smoke_runtime_merge_and_resume() -> None:
    snapshot = {
        "provider": "openai_responses",
        "runtime_config": {
            "model": "gpt-4.1-mini",
            "temperature": 0.2,
            "top_p": 1.0,
        },
        "resume_cursor": {"last_response_id": "resp_prev_123", "fallback_transcript_items": []},
    }
    req_body = {
        "input": [{"role": "user", "content": [{"type": "input_text", "text": "hi"}]}],
        "temperature": 0.7,
        "reasoning": {"effort": "medium"},
    }

    explicit = _extract_runtime_updates_from_request(req_body)
    merged = _merge_runtime_config(base_runtime_config=snapshot["runtime_config"], explicit_updates=explicit)
    _assert(merged.get("model") == "gpt-4.1-mini", "model should be inherited from session runtime_config")
    _assert(float(merged.get("temperature")) == 0.7, "temperature should be updated by explicit request field")
    _assert(merged.get("reasoning", {}).get("effort") == "medium", "reasoning should be merged into runtime_config")

    body2 = _apply_runtime_config_to_body(body=req_body, runtime_config=merged)
    body3, prev = _apply_session_resume_to_body(body=body2, session_snapshot=snapshot)
    _assert(prev == "resp_prev_123", "previous_response_id should come from session resume cursor")
    _assert(body3.get("previous_response_id") == "resp_prev_123", "resume cursor should be applied to request body")

    tool_round_body = _apply_runtime_config_to_body(
        body={
            "previous_response_id": "resp_prev_123",
            "input": [{"type": "function_call_output", "call_id": "call_1", "output": "ok"}],
            "tools": [{"type": "function", "name": "core.web_fetch"}],
        },
        runtime_config=merged,
    )
    _assert(
        tool_round_body.get("model") == "gpt-4.1-mini" and float(tool_round_body.get("temperature")) == 0.7,
        "tool round body should inherit the same effective runtime_config",
    )

    next_snapshot = _build_next_session_snapshot(
        previous_snapshot=snapshot,
        runtime_config=merged,
        resume_last_response_id="resp_new_456",
        run_response_id="resp_new_456",
        last_event_seq=3,
    )
    _assert(
        next_snapshot.get("resume_cursor", {}).get("last_response_id") == "resp_new_456",
        "next snapshot should advance resume cursor",
    )


async def _smoke_none_mode_local_recovery() -> None:
    with tempfile.TemporaryDirectory(prefix="anyagent-session-resume-") as td:
        settings = Settings.model_validate(
            {
                "WORKSPACE_DIR": td,
                "AGENT_API_KEY": "test-agent-api-key",
                "OPENAI_API_KEY": "test-openai-api-key",
                "TOOL_RUNTIME_INTERNAL_KEY": "test-tool-runtime-key",
                "STORAGE_MODE": "none",
                "ROLLOUT_ROOT_DIR": f"{td}/rollouts",
            }
        )
        session_partition_key = "main::session-resume-smoke"

        runtime1 = await create_storage_runtime(settings)
        try:
            initial_snapshot = _build_initial_session_snapshot(runtime_config={"model": "gpt-4.1-mini", "temperature": 0.2})
            created = await runtime1.session_store.create_if_absent(
                session_partition_key=session_partition_key,
                agent_id="main",
                session_key="session-resume-smoke",
                snapshot_json=initial_snapshot,
            )
            _assert(created.snapshot_version == 0, "new session should start from snapshot_version=0")

            next_snapshot = _build_next_session_snapshot(
                previous_snapshot=created.snapshot_json,
                runtime_config={"model": "gpt-4.1-mini", "temperature": 0.6},
                resume_last_response_id="resp_after_first_turn",
                run_response_id="resp_after_first_turn",
                last_event_seq=2,
            )
            ok, updated = await runtime1.session_store.update_snapshot_cas(
                session_partition_key=session_partition_key,
                expected_snapshot_version=0,
                snapshot_json=next_snapshot,
                agent_id="main",
                session_key="session-resume-smoke",
            )
            _assert(ok and updated is not None, "CAS update should succeed for expected version")
            _assert(updated.snapshot_version == 1, "snapshot version should increment after CAS update")
        finally:
            await runtime1.aclose()

        # Recreate runtime and verify snapshot is recovered from local rollout files.
        runtime2 = await create_storage_runtime(settings)
        try:
            recovered = await runtime2.session_store.get(session_partition_key=session_partition_key)
            _assert(recovered is not None, "session snapshot should be recoverable after runtime restart")
            _assert(recovered.snapshot_version == 1, "recovered snapshot version should match latest committed version")
            _assert(
                recovered.snapshot_json.get("resume_cursor", {}).get("last_response_id") == "resp_after_first_turn",
                "recovered snapshot should keep last_response_id",
            )
            ok2, _ = await runtime2.session_store.update_snapshot_cas(
                session_partition_key=session_partition_key,
                expected_snapshot_version=0,
                snapshot_json=recovered.snapshot_json,
                agent_id="main",
                session_key="session-resume-smoke",
            )
            _assert(not ok2, "CAS with stale snapshot_version must fail")
        finally:
            await runtime2.aclose()


async def main() -> None:
    await _smoke_runtime_merge_and_resume()
    await _smoke_none_mode_local_recovery()
    print("ok: acceptance_session_resume_smoke")


if __name__ == "__main__":
    try:
        import asyncio

        asyncio.run(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
