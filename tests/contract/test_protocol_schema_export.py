from __future__ import annotations

import importlib
import json
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from anyagent.protocol.schema_export import (
    TYPE_ADAPTER_EXPORTS,
    export_openapi_document,
    export_protocol_changelog,
    export_protocol_schema_bundle,
    iter_protocol_model_classes,
)
from anyagent.protocol.sse import SSEBlockDecoder


ROOT = Path(__file__).resolve().parents[2]
SDK_CONFORMANCE_FIXTURE = ROOT / "tests" / "fixtures" / "sdk_conformance" / "core_surface.json"
SDK_MINIMUM_MATRIX = ROOT / "tests" / "fixtures" / "sdk_conformance" / "minimum_matrix.json"
TYPESCRIPT_CLIENT = ROOT / "sdks" / "typescript" / "src" / "client.ts"


def _load_model(qualified_name: str) -> type[Any]:
    module_name, class_name = qualified_name.rsplit(".", 1)
    module = importlib.import_module(module_name)
    model = getattr(module, class_name)
    return model


def _fixture_names(fixture: dict[str, Any], key: str) -> set[str]:
    return {case["name"] for case in fixture[key]}


def test_protocol_schema_export_includes_core_models_and_unions() -> None:
    bundle = export_protocol_schema_bundle()

    assert bundle["schema_version"] == "2026-09-07"
    assert bundle["protocol_version"] == "0.1.10"
    assert bundle["protocol_package"] == "anyagent.protocol"
    assert bundle["changelog"] == export_protocol_changelog()
    assert bundle["changelog"][0]["protocol_version"] == bundle["protocol_version"]
    assert bundle["changelog"][0]["schema_version"] == bundle["schema_version"]
    assert bundle["changelog"][0]["changes"]

    models = bundle["models"]
    assert "anyagent.protocol.agent_api_internal.InternalEventsListResponse" in models
    assert "anyagent.protocol.agent_api_internal.InternalToolCatalogResponse" in models
    assert "anyagent.protocol.credential_vault.AdminCredentialDeleteResponse" in models
    assert "anyagent.protocol.credential_vault.AdminCredentialSetRequest" in models
    assert "anyagent.protocol.health.HealthResponse" in models
    assert "anyagent.protocol.mcp.MCPConfig" in models
    assert "anyagent.protocol.mcp.MCPServerConfig" in models
    assert "anyagent.protocol.tool_runtime.ManifestRequest" in models

    adapters = bundle["type_adapters"]
    assert "anyagent.protocol.stage_events.StageEvent" in adapters
    assert "anyagent.protocol.tool_runtime.ExecuteResponse" in adapters

    semantic_rules = bundle["semantic_rules"]
    assert "anyagent.protocol.credential_vault.CredentialScope" in semantic_rules
    assert "anyagent.protocol.mcp.MCPServerConfig" in semantic_rules
    assert "anyagent.protocol.multi_agent.SpawnAgentArgs" in semantic_rules
    assert "anyagent.protocol.multi_agent.SendInputArgs" in semantic_rules
    assert "anyagent.protocol.tool_runtime.ToolContext" in semantic_rules

    stage_event_schema = adapters["anyagent.protocol.stage_events.StageEvent"]
    assert "discriminator" in stage_event_schema
    assert stage_event_schema["discriminator"]["propertyName"] == "type"


def test_protocol_schema_export_is_json_serializable_and_deterministic() -> None:
    first = export_protocol_schema_bundle()
    second = export_protocol_schema_bundle()

    assert first == second
    assert json.loads(json.dumps(first, sort_keys=True)) == first


def test_protocol_semantic_rules_are_stable_and_actionable() -> None:
    bundle = export_protocol_schema_bundle()
    rules = bundle["semantic_rules"]

    assert rules["anyagent.protocol.credential_vault.CredentialScope"][0]["id"] == (
        "credential_scope_agent_id_matches_level"
    )
    assert rules["anyagent.protocol.mcp.MCPServerConfig"][0]["id"] == (
        "mcp_server_source_is_exactly_one_of_url_or_command"
    )
    assert rules["anyagent.protocol.tool_runtime.ToolContext"][0]["mode"] == "before_validation"

    for model_name, model_rules in rules.items():
        assert model_name in bundle["models"], model_name
        assert model_rules, model_name
        for rule in model_rules:
            assert rule["id"]
            assert rule["kind"]
            assert rule["mode"] in {"before_validation", "after_validation"}
            assert rule["fields"]
            assert rule["description"]
            assert rule["examples"]["valid"]
            assert rule["examples"]["invalid"]


def test_protocol_schema_export_endpoint_manifest_references_protocol_models() -> None:
    bundle = export_protocol_schema_bundle()
    endpoints = bundle["endpoints"]

    assert endpoints
    operation_names = [endpoint["operation"] for endpoint in endpoints]
    assert operation_names == sorted(operation_names)
    assert len(operation_names) == len(set(operation_names))

    for endpoint in endpoints:
        assert endpoint["method"] in {"DELETE", "GET", "POST", "PUT"}, endpoint["operation"]
        assert endpoint["path"].startswith("/"), endpoint["operation"]
        assert endpoint.get("request_model") or endpoint.get("request_format") or endpoint["method"] in {"DELETE", "GET"}
        assert endpoint.get("response_model") or endpoint.get("response_format"), endpoint["operation"]
        request_model = endpoint.get("request_model")
        if request_model:
            assert request_model in bundle["models"], endpoint["operation"]
        response_model = endpoint.get("response_model")
        if response_model:
            assert response_model in bundle["models"], endpoint["operation"]

    required_operations = {
        "health",
        "responses.create",
        "responses.stream",
        "responses.retrieve",
        "responses.cancel",
        "responses.prompt_context",
        "events.list",
        "agents.list",
        "agents.get",
        "tools.catalog",
        "skills.list",
        "prompts.preview",
        "observability.summary",
        "observability.runs",
        "observability.timeline",
        "observability.metrics",
        "observability.tools",
        "observability.errors",
        "observability.trace",
        "admin.storage.health",
        "admin.plugins.catalog",
        "admin.plugins.capabilities",
        "admin.credentials.list",
        "admin.credentials.set",
        "admin.credentials.delete",
        "admin.workspace.agent.create",
        "admin.workspace.agent.files",
        "admin.workspace.agent.file.update",
        "admin.skill.import",
        "admin.skill.install",
        "admin.skill.update.check",
        "admin.skill.update.apply",
        "admin.agent.skills.update",
        "admin.agent.config.update",
    }
    assert required_operations <= set(operation_names)


def test_openapi_export_is_generated_from_endpoint_manifest_and_protocol_models() -> None:
    bundle = export_protocol_schema_bundle()
    document = export_openapi_document()

    assert document["openapi"] == "3.1.0"
    assert document["info"]["version"] == bundle["schema_version"]
    assert document["x-anyagent-schema-version"] == bundle["schema_version"]
    assert document["x-anyagent-protocol-version"] == bundle["protocol_version"]
    assert document["x-anyagent-protocol-changelog"] == bundle["changelog"]
    assert document["components"]["schemas"].keys() == bundle["models"].keys()

    health = document["paths"]["/healthz"]["get"]
    assert health["operationId"] == "health"
    assert health["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/anyagent.protocol.health.HealthResponse"
    }

    responses = document["paths"]["/v1/responses"]["post"]
    assert responses["x-anyagent-operations"] == ["responses.create", "responses.stream"]
    assert "application/json" in responses["responses"]["200"]["content"]
    assert "text/event-stream" in responses["responses"]["200"]["content"]

    agent_get = document["paths"]["/internal/agents/{agent_id}"]["get"]
    assert agent_get["parameters"] == [
        {"name": "agent_id", "in": "path", "required": True, "schema": {"type": "string"}}
    ]

    credential_set = document["paths"]["/admin/credentials"]["post"]
    assert credential_set["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/anyagent.protocol.credential_vault.AdminCredentialSetRequest"
    }
    assert credential_set["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/anyagent.protocol.credential_vault.AdminCredentialRef"
    }


def test_typescript_client_uses_endpoint_manifest_for_protocol_paths() -> None:
    bundle = export_protocol_schema_bundle()
    endpoint_operations = {endpoint["operation"] for endpoint in bundle["endpoints"]}
    source = TYPESCRIPT_CLIENT.read_text(encoding="utf-8")

    forbidden_fragments = [
        "anyagent.protocol.",
        '"/healthz"',
        '"/internal/',
        '"/admin/',
        '"/v1/responses',
        "`/internal/",
        "`/admin/",
        "`/v1/responses",
    ]
    for fragment in forbidden_fragments:
        assert fragment not in source

    operation_names = set(re.findall(r'operation: "([^"]+)"', source))
    assert operation_names
    assert operation_names <= endpoint_operations


def test_protocol_schema_export_scans_owned_pydantic_models_only() -> None:
    names = {f"{model.__module__}.{model.__name__}" for model in iter_protocol_model_classes()}

    assert "pydantic.main.BaseModel" not in names
    assert "anyagent.protocol.stage_events.StagePayloadSummary" in names
    assert "anyagent.protocol.agent_api_internal.StagePayloadSummary" not in names


def test_sdk_conformance_fixture_payloads_match_protocol_models() -> None:
    bundle = export_protocol_schema_bundle()
    fixture = json.loads(SDK_CONFORMANCE_FIXTURE.read_text(encoding="utf-8"))

    assert fixture["schema_version"] == bundle["schema_version"]
    assert fixture["cases"]

    for case in fixture["cases"]:
        schema_name = case["schema"]
        assert schema_name in bundle["models"], case["name"]
        model = _load_model(schema_name)
        model.model_validate(case["payload"])


def test_sdk_conformance_openai_response_payloads_are_minimal_response_objects() -> None:
    fixture = json.loads(SDK_CONFORMANCE_FIXTURE.read_text(encoding="utf-8"))

    assert fixture["openai_response_cases"]

    for case in fixture["openai_response_cases"]:
        payload = case["payload"]
        assert isinstance(payload, dict), case["name"]
        assert isinstance(payload.get("id"), str), case["name"]
        assert payload.get("object") == "response", case["name"]


def test_sdk_conformance_type_adapter_payloads_match_protocol_schemas() -> None:
    bundle = export_protocol_schema_bundle()
    fixture = json.loads(SDK_CONFORMANCE_FIXTURE.read_text(encoding="utf-8"))

    assert fixture["type_adapter_cases"]

    for case in fixture["type_adapter_cases"]:
        schema_name = case["schema"]
        assert schema_name in bundle["type_adapters"], case["name"]
        adapter = TYPE_ADAPTER_EXPORTS[schema_name]
        adapter.validate_python(case["payload"])


def test_sdk_conformance_negative_type_adapter_payloads_fail_protocol_schemas() -> None:
    bundle = export_protocol_schema_bundle()
    fixture = json.loads(SDK_CONFORMANCE_FIXTURE.read_text(encoding="utf-8"))

    assert fixture["type_adapter_negative_cases"]

    for case in fixture["type_adapter_negative_cases"]:
        schema_name = case["schema"]
        assert schema_name in bundle["type_adapters"], case["name"]
        adapter = TYPE_ADAPTER_EXPORTS[schema_name]
        with pytest.raises(ValidationError) as exc_info:
            adapter.validate_python(case["payload"])
        error_paths = {".".join(str(part) for part in error["loc"]) for error in exc_info.value.errors()}
        expected_path = case.get("pydantic_error_path", case["error_path"])
        assert expected_path in error_paths, case["name"]


def test_sdk_conformance_response_stream_sse_blocks_are_parseable() -> None:
    fixture = json.loads(SDK_CONFORMANCE_FIXTURE.read_text(encoding="utf-8"))

    text = "\n\n".join(fixture["response_stream_sse_blocks"]) + "\n\n"
    decoder = SSEBlockDecoder()
    blocks = []
    for line in text.splitlines():
        blocks.extend(decoder.feed_line(line))
    blocks.extend(decoder.flush())

    assert [block.event for block in blocks] == ["response.created", "response.completed", None]
    assert json.loads(blocks[0].data)["response"]["id"] == "resp_stream"
    assert blocks[-1].data == "[DONE]"


def test_sdk_conformance_negative_request_payloads_fail_protocol_models() -> None:
    bundle = export_protocol_schema_bundle()
    fixture = json.loads(SDK_CONFORMANCE_FIXTURE.read_text(encoding="utf-8"))

    assert fixture["request_negative_cases"]

    for case in fixture["request_negative_cases"]:
        schema_name = case["schema"]
        assert schema_name in bundle["models"], case["name"]
        model = _load_model(schema_name)
        with pytest.raises(ValidationError) as exc_info:
            model.model_validate(case["payload"])
        error_paths = {".".join(str(part) for part in error["loc"]) for error in exc_info.value.errors()}
        expected_path = case.get("pydantic_error_path", case["error_path"])
        assert expected_path in error_paths, case["name"]


def test_sdk_minimum_matrix_references_existing_conformance_fixtures() -> None:
    bundle = export_protocol_schema_bundle()
    fixture = json.loads(SDK_CONFORMANCE_FIXTURE.read_text(encoding="utf-8"))
    matrix = json.loads(SDK_MINIMUM_MATRIX.read_text(encoding="utf-8"))

    assert matrix["schema_version"] == fixture["schema_version"]
    operation_names = [operation["name"] for operation in matrix["operations"]]
    assert len(operation_names) == len(set(operation_names))

    protocol_cases = _fixture_names(fixture, "cases")
    openai_cases = _fixture_names(fixture, "openai_response_cases")
    type_adapter_cases = _fixture_names(fixture, "type_adapter_cases")
    request_negative_cases = _fixture_names(fixture, "request_negative_cases")
    type_adapter_negative_cases = _fixture_names(fixture, "type_adapter_negative_cases")

    for operation in matrix["operations"]:
        kind = operation["kind"]
        reference = operation["fixture"]
        assert operation["protocol_version"] == bundle["protocol_version"], operation["name"]
        if kind == "protocol_model":
            assert reference in protocol_cases, operation["name"]
        elif kind == "openai_response":
            assert reference in openai_cases, operation["name"]
        elif kind == "type_adapter":
            assert reference in type_adapter_cases, operation["name"]
        elif kind == "request_negative":
            assert reference in request_negative_cases, operation["name"]
        elif kind == "type_adapter_negative":
            assert reference in type_adapter_negative_cases, operation["name"]
        elif kind == "sse_stream":
            assert reference == "response_stream_sse_blocks"
            assert fixture["response_stream_sse_blocks"]
        else:
            raise AssertionError(f"unknown conformance operation kind: {kind}")

    required_operations = {
        "responses.create",
        "responses.stream",
        "responses.retrieve",
        "responses.cancel",
        "events.list",
        "responses.tool_executions",
        "responses.model_request",
        "agents.list",
        "agents.get",
        "tools.catalog",
        "skills.list",
        "prompts.preview",
        "admin.storage.health",
        "admin.plugins.catalog",
        "admin.plugins.capabilities",
        "admin.credentials.set",
        "admin.credentials.delete",
        "admin.workspace.agent.create",
        "admin.workspace.agent.file.update",
        "admin.skill.import",
        "admin.skill.install",
        "admin.skill.update.apply",
        "admin.agent.skills.update",
        "admin.agent.config.update",
        "stage_event.tool.planned",
        "stage_event.subagent.spawned",
        "stage_event.context.compacted",
        "stage_event.agent.loop_terminated",
    }
    assert required_operations <= set(operation_names)


def test_sdk_minimum_matrix_covers_stage_event_and_tool_runtime_main_paths() -> None:
    matrix = json.loads(SDK_MINIMUM_MATRIX.read_text(encoding="utf-8"))

    operation_names = {operation["name"] for operation in matrix["operations"]}
    assert {
        "stage_event.model.stream_event",
        "stage_event.tool.planned",
        "stage_event.tool.result",
        "stage_event.command.planned",
        "stage_event.command.result",
        "stage_event.prompt.context",
        "stage_event.sandbox.workspace.restored",
        "stage_event.subagent.spawned",
        "stage_event.subagent.completed",
        "stage_event.subagent.timeout",
        "stage_event.context.compacted",
        "stage_event.agent.loop_warning",
        "stage_event.agent.loop_terminated",
        "stage_event.done",
        "tool_runtime.manifest.request",
        "tool_runtime.manifest.response",
        "tool_runtime.execute.request",
        "tool_runtime.execute.response",
        "tool_runtime.execute.response.cancelled",
        "tool_runtime.execute.response.error",
    } <= operation_names
