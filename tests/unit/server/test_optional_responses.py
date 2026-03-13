from __future__ import annotations

from types import SimpleNamespace

from anyagent.protocol.openai_responses import build_minimal_openai_response_json
from anyagent.server.responses_optional import (
    cancelled_response_error_json,
    optional_response_payload_from_run,
    optional_response_status_from_run,
)


def test_optional_response_status_from_run_prefers_effective_status() -> None:
    run = SimpleNamespace(status="aborted", effective_status="cancelled", error_json=None)
    assert optional_response_status_from_run(run) == "cancelled"


def test_optional_response_status_from_run_maps_cancelled_error_json() -> None:
    run = SimpleNamespace(status="errored", effective_status=None, error_json={"code": "response_cancelled"})
    assert optional_response_status_from_run(run) == "cancelled"


def test_optional_response_payload_from_run_returns_final_response_when_openai_compatible() -> None:
    final = build_minimal_openai_response_json(response_id="resp_1", status="completed")
    run = SimpleNamespace(response_id="resp_1", status="completed", effective_status="completed", final_response_json=final)
    assert optional_response_payload_from_run(run) == final


def test_optional_response_payload_from_run_builds_minimal_response_with_created_at_ms() -> None:
    run = SimpleNamespace(
        response_id="resp_2",
        status="started",
        effective_status="in_progress",
        final_response_json=None,
        created_at_ms=123000,
        error_json=None,
    )
    payload = optional_response_payload_from_run(run)
    assert payload["id"] == "resp_2"
    assert payload["status"] == "in_progress"
    assert int(payload["created_at"]) == 123


def test_cancelled_response_error_json_is_stable() -> None:
    assert cancelled_response_error_json() == {
        "type": "cancelled",
        "message": "response cancelled by client request",
        "code": "response_cancelled",
    }
