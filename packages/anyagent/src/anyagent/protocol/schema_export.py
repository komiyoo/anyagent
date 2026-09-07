from __future__ import annotations

"""
Protocol schema export helpers.

This module is intentionally separate from `anyagent.protocol.__init__` so the
default protocol import path stays lightweight. SDK generators, Studio tooling
and contract tests can import this module explicitly when they need the full
cross-language schema bundle.
"""

import importlib
import inspect
import pkgutil
import re
from collections.abc import Iterator
from typing import Any

from pydantic import BaseModel, TypeAdapter

import anyagent.protocol as protocol_pkg


SCHEMA_BUNDLE_VERSION = "2026-09-07"
PROTOCOL_VERSION = "0.1.10"
OPENAPI_VERSION = "3.1.0"


PROTOCOL_CHANGELOG: list[dict[str, Any]] = [
    {
        "protocol_version": PROTOCOL_VERSION,
        "schema_version": SCHEMA_BUNDLE_VERSION,
        "date": "2026-09-07",
        "summary": "Accept MCP source-name extension on function tool params; add scripted reply stage event.",
        "changes": [
            "Add optional `x-anyagent-source-name` to AnyAgentFunctionToolParam so MCP tools keep the raw server tool name through prompt-bundle validation.",
            "Add `anyagent.response.scripted` stage event (AnyAgentScriptedReplyEvent) marking turns answered by a scripted reply provider without a model request.",
            "Add `anyagent.protocol.scripted_reply.ScriptedReply` as the typed return value of scripted reply providers.",
        ],
    },
    {
        "protocol_version": "0.1.10",
        "schema_version": "2026-06-23",
        "date": "2026-06-23",
        "summary": "Add per-session tool call averages and truncation flags to observability metrics/summary.",
        "changes": [
            "Add `session_count`, `avg_tool_calls_per_session`, `avg_mcp_calls_per_session` to observability metrics.",
            "Add `truncated` flag to observability summary/metrics so the per-run 10k event cap is visible.",
        ],
    },
    {
        "protocol_version": "0.1.10",
        "schema_version": "2026-06-22",
        "date": "2026-06-22",
        "summary": "Add structured tool source labels to stage events and observability telemetry.",
        "changes": [
            "Add optional `tool_source` field to tool planned/result/execution-detail stage events.",
            "Add optional `tool_source` field to NormalizedTelemetryEvent and the Postgres telemetry_events row.",
            "Add `tool_call_counts_by_source` to observability summary/metrics and `tool_source` to tool stats.",
            "Tool invocations now carry a non-null source (command/mcp/builtin) for call-chain grouping.",
        ],
    },
    {
        "protocol_version": "0.1.10",
        "schema_version": "2026-05-29",
        "date": "2026-05-29",
        "summary": "Initial versioned protocol schema bundle with endpoint manifest, semantic rules and OpenAPI export.",
        "changes": [
            "Expose protocol_version as the stable protocol compatibility identifier.",
            "Keep schema_version as the deterministic schema bundle revision.",
            "Publish this changelog block in the schema bundle for SDK and runtime generators.",
            "Add rendered prompt-context replay event and internal prompt-context history endpoint.",
            "Add tool execution detail event and model request event for M2/M3 replay.",
            "Add internal tool-executions and model-request history endpoints.",
        ],
    }
]


TYPE_ADAPTER_EXPORTS: dict[str, TypeAdapter[Any]] = {
    "anyagent.protocol.stage_events.StageEvent": TypeAdapter(
        importlib.import_module("anyagent.protocol.stage_events").StageEvent
    ),
    "anyagent.protocol.tool_runtime.ExecuteResponse": TypeAdapter(
        importlib.import_module("anyagent.protocol.tool_runtime").ExecuteResponse
    ),
}


PROTOCOL_ENDPOINTS: list[dict[str, Any]] = [
    {
        "operation": "health",
        "method": "GET",
        "path": "/healthz",
        "response_model": "anyagent.protocol.health.HealthResponse",
    },
    {
        "operation": "responses.create",
        "method": "POST",
        "path": "/v1/responses",
        "request_format": "openai_responses_create",
        "response_format": "openai_response_object",
    },
    {
        "operation": "responses.stream",
        "method": "POST",
        "path": "/v1/responses",
        "request_format": "openai_responses_create",
        "response_format": "responses_sse_stream",
    },
    {
        "operation": "responses.retrieve",
        "method": "GET",
        "path": "/v1/responses/{response_id}",
        "response_model": "anyagent.protocol.responses_optional.AnyAgentResponseStatusPayload",
    },
    {
        "operation": "responses.cancel",
        "method": "POST",
        "path": "/v1/responses/{response_id}/cancel",
        "request_format": "empty",
        "response_model": "anyagent.protocol.responses_optional.AnyAgentResponseStatusPayload",
    },
    {
        "operation": "events.list",
        "method": "GET",
        "path": "/internal/events/list",
        "response_model": "anyagent.protocol.agent_api_internal.InternalEventsListResponse",
    },
    {
        "operation": "responses.prompt_context",
        "method": "GET",
        "path": "/internal/responses/{response_id}/prompt-context",
        "response_model": "anyagent.protocol.agent_api_internal.InternalResponsePromptContextResponse",
    },
    {
        "operation": "responses.tool_executions",
        "method": "GET",
        "path": "/internal/responses/{response_id}/tool-executions",
        "response_model": "anyagent.protocol.agent_api_internal.InternalResponseToolExecutionsResponse",
    },
    {
        "operation": "responses.model_request",
        "method": "GET",
        "path": "/internal/responses/{response_id}/model-request",
        "response_model": "anyagent.protocol.agent_api_internal.InternalResponseModelRequestResponse",
    },
    {
        "operation": "agents.list",
        "method": "GET",
        "path": "/internal/agents",
        "response_model": "anyagent.protocol.agent_api_internal.InternalAgentsListResponse",
    },
    {
        "operation": "agents.get",
        "method": "GET",
        "path": "/internal/agents/{agent_id}",
        "response_model": "anyagent.protocol.agent_api_internal.InternalAgentDetailResponse",
    },
    {
        "operation": "tools.catalog",
        "method": "GET",
        "path": "/internal/tools/catalog",
        "response_model": "anyagent.protocol.agent_api_internal.InternalToolCatalogResponse",
    },
    {
        "operation": "skills.list",
        "method": "GET",
        "path": "/internal/skills/list",
        "response_model": "anyagent.protocol.agent_api_internal.InternalSkillsListResponse",
    },
    {
        "operation": "prompts.preview",
        "method": "POST",
        "path": "/internal/prompt/bundle",
        "request_format": "openai_responses_create",
        "response_model": "anyagent.protocol.agent_api_internal.InternalPromptBundlePreviewResponse",
    },
    {
        "operation": "prompts.versions.list",
        "method": "GET",
        "path": "/internal/prompt/versions",
        "response_model": "anyagent.protocol.prompt_versions.PromptVersionsResponse",
    },
    {
        "operation": "prompts.versions.create",
        "method": "POST",
        "path": "/internal/prompt/versions",
        "request_model": "anyagent.protocol.prompt_versions.PromptVersionCreateRequest",
        "response_model": "anyagent.protocol.prompt_versions.PromptVersionResponse",
    },
    {
        "operation": "prompts.versions.get",
        "method": "GET",
        "path": "/internal/prompt/versions/{version_id}",
        "response_model": "anyagent.protocol.prompt_versions.PromptVersionResponse",
    },
    {
        "operation": "prompts.versions.diff",
        "method": "GET",
        "path": "/internal/prompt/versions/diff",
        "response_model": "anyagent.protocol.prompt_versions.PromptVersionDiffResponse",
    },
    {
        "operation": "prompts.versions.restore",
        "method": "POST",
        "path": "/internal/prompt/versions/{version_id}/restore",
        "request_format": "empty",
        "response_model": "anyagent.protocol.prompt_versions.PromptVersionRestoreResponse",
    },
    {
        "operation": "sessions.list",
        "method": "GET",
        "path": "/internal/sessions",
        "response_model": "anyagent.protocol.agent_api_internal.InternalSessionsListResponse",
    },
    {
        "operation": "sessions.get",
        "method": "GET",
        "path": "/internal/sessions/{session_key}",
        "response_model": "anyagent.protocol.agent_api_internal.InternalSessionDetailResponse",
    },
    {
        "operation": "evaluations.datasets.list",
        "method": "GET",
        "path": "/internal/evaluations/datasets",
        "response_model": "anyagent.protocol.evaluations.EvalDatasetsResponse",
    },
    {
        "operation": "evaluations.datasets.upsert",
        "method": "POST",
        "path": "/internal/evaluations/datasets",
        "request_model": "anyagent.protocol.evaluations.EvalDatasetUpsertRequest",
        "response_model": "anyagent.protocol.evaluations.EvalDatasetResponse",
    },
    {
        "operation": "evaluations.datasets.get",
        "method": "GET",
        "path": "/internal/evaluations/datasets/{dataset_id}",
        "response_model": "anyagent.protocol.evaluations.EvalDatasetResponse",
    },
    {
        "operation": "evaluations.datasets.delete",
        "method": "DELETE",
        "path": "/internal/evaluations/datasets/{dataset_id}",
        "response_format": "json_object",
    },
    {
        "operation": "evaluations.run",
        "method": "POST",
        "path": "/internal/evaluations/run",
        "request_model": "anyagent.protocol.evaluations.EvalRunRequest",
        "response_model": "anyagent.protocol.evaluations.EvalRunResponse",
    },
    {
        "operation": "evaluations.runs.list",
        "method": "GET",
        "path": "/internal/evaluations/runs",
        "response_model": "anyagent.protocol.evaluations.EvalRunsResponse",
    },
    {
        "operation": "evaluations.runs.get",
        "method": "GET",
        "path": "/internal/evaluations/runs/{eval_run_id}",
        "response_model": "anyagent.protocol.evaluations.EvalRunResponse",
    },
    {
        "operation": "observability.summary",
        "method": "GET",
        "path": "/internal/observability/summary",
        "response_model": "anyagent.protocol.agent_api_internal.InternalObservabilitySummaryResponse",
    },
    {
        "operation": "observability.runs",
        "method": "GET",
        "path": "/internal/observability/runs",
        "response_model": "anyagent.protocol.agent_api_internal.InternalObservabilityRunsResponse",
    },
    {
        "operation": "observability.timeline",
        "method": "GET",
        "path": "/internal/observability/timeline",
        "response_model": "anyagent.protocol.agent_api_internal.InternalObservabilityTimelineResponse",
    },
    {
        "operation": "observability.metrics",
        "method": "GET",
        "path": "/internal/observability/metrics",
        "response_model": "anyagent.protocol.agent_api_internal.InternalObservabilityMetricsResponse",
    },
    {
        "operation": "observability.tools",
        "method": "GET",
        "path": "/internal/observability/tools",
        "response_model": "anyagent.protocol.agent_api_internal.InternalObservabilityToolsResponse",
    },
    {
        "operation": "observability.errors",
        "method": "GET",
        "path": "/internal/observability/errors",
        "response_model": "anyagent.protocol.agent_api_internal.InternalObservabilityErrorsResponse",
    },
    {
        "operation": "observability.trace",
        "method": "GET",
        "path": "/internal/observability/traces/{trace_id}",
        "response_model": "anyagent.protocol.agent_api_internal.InternalObservabilityTraceResponse",
    },
    {
        "operation": "observability.alerts",
        "method": "GET",
        "path": "/internal/observability/alerts",
        "response_model": "anyagent.protocol.alerts.AlertEventsResponse",
    },
    {
        "operation": "audit.events",
        "method": "GET",
        "path": "/internal/audit/events",
        "response_model": "anyagent.protocol.agent_api_internal.InternalAuditEventsResponse",
    },
    {
        "operation": "admin.storage.health",
        "method": "GET",
        "path": "/admin/storage/health",
        "response_model": "anyagent.protocol.admin_storage.StorageHealthResponse",
    },
    {
        "operation": "admin.tools.catalog",
        "method": "GET",
        "path": "/admin/tools/catalog",
        "response_model": "anyagent.protocol.agent_api_internal.AdminToolCatalogResponse",
    },
    {
        "operation": "admin.sandboxes.list",
        "method": "GET",
        "path": "/admin/sandboxes",
        "response_model": "anyagent.protocol.admin_storage.AdminSandboxWorkspaceListResponse",
    },
    {
        "operation": "admin.sandboxes.workspace.snapshots",
        "method": "GET",
        "path": "/admin/sandboxes/workspaces/{workspace_id}/snapshots",
        "response_model": "anyagent.protocol.admin_storage.AdminSandboxWorkspaceSnapshotsResponse",
    },
    {
        "operation": "admin.sandboxes.workspace.reclaim",
        "method": "POST",
        "path": "/admin/sandboxes/workspaces/{workspace_id}/reclaim",
        "request_format": "empty",
        "response_model": "anyagent.protocol.admin_storage.AdminSandboxWorkspaceReclaimResponse",
    },
    {
        "operation": "admin.plugins.catalog",
        "method": "GET",
        "path": "/admin/plugins/catalog",
        "response_model": "anyagent.protocol.plugins.PluginCatalogResponse",
    },
    {
        "operation": "admin.plugins.capabilities",
        "method": "GET",
        "path": "/admin/plugins/capabilities",
        "response_model": "anyagent.protocol.plugin_capabilities.PluginCapabilityMatrix",
    },
    {
        "operation": "admin.credentials.list",
        "method": "GET",
        "path": "/admin/credentials",
        "response_model": "anyagent.protocol.credential_vault.AdminCredentialListResponse",
    },
    {
        "operation": "admin.credentials.set",
        "method": "POST",
        "path": "/admin/credentials",
        "request_model": "anyagent.protocol.credential_vault.AdminCredentialSetRequest",
        "response_model": "anyagent.protocol.credential_vault.AdminCredentialRef",
    },
    {
        "operation": "admin.credentials.delete",
        "method": "DELETE",
        "path": "/admin/credentials/{credential_id}",
        "response_model": "anyagent.protocol.credential_vault.AdminCredentialDeleteResponse",
    },
    {
        "operation": "admin.workspace.agent.create",
        "method": "POST",
        "path": "/admin/workspace/agents",
        "request_model": "anyagent.protocol.agent_api_internal.AdminAgentCreateRequest",
        "response_model": "anyagent.protocol.agent_api_internal.AdminAgentCreateResponse",
    },
    {
        "operation": "admin.workspace.agent.get",
        "method": "GET",
        "path": "/admin/workspace/agents/{agent_id}",
        "response_model": "anyagent.protocol.agent_api_internal.InternalAgentDetailResponse",
    },
    {
        "operation": "admin.workspace.agent.files",
        "method": "GET",
        "path": "/admin/workspace/agents/{agent_id}/files",
        "response_model": "anyagent.protocol.agent_api_internal.AdminWorkspaceAgentFilesResponse",
    },
    {
        "operation": "admin.workspace.agent.file.update",
        "method": "PUT",
        "path": "/admin/workspace/agents/{agent_id}/files/{kind}",
        "request_model": "anyagent.protocol.agent_api_internal.AdminWorkspaceAgentFileUpdateRequest",
        "response_model": "anyagent.protocol.agent_api_internal.AdminWorkspaceAgentFileUpdateResponse",
    },
    {
        "operation": "admin.workspace.agent.mcp.servers",
        "method": "GET",
        "path": "/admin/workspace/agents/{agent_id}/mcp/servers",
        "response_model": "anyagent.protocol.agent_api_internal.AdminMcpServersResponse",
    },
    {
        "operation": "admin.workspace.agent.mcp.server.enabled",
        "method": "PUT",
        "path": "/admin/workspace/agents/{agent_id}/mcp/servers/{server_label}/enabled",
        "request_model": "anyagent.protocol.agent_api_internal.AdminMcpServerEnableRequest",
        "response_model": "anyagent.protocol.agent_api_internal.AdminMcpServerEnableResponse",
    },
    {
        "operation": "admin.workspace.agent.mcp.server.test",
        "method": "POST",
        "path": "/admin/workspace/agents/{agent_id}/mcp/servers/{server_label}/test",
        "request_format": "empty",
        "response_model": "anyagent.protocol.agent_api_internal.AdminMcpServerTestResponse",
    },
    {
        "operation": "admin.skill.import",
        "method": "POST",
        "path": "/admin/workspace/agents/{agent_id}/skills/import",
        "request_model": "anyagent.protocol.agent_api_internal.AdminSkillImportRequest",
        "response_model": "anyagent.protocol.agent_api_internal.AdminSkillImportResponse",
    },
    {
        "operation": "admin.skill.install",
        "method": "POST",
        "path": "/admin/workspace/agents/{agent_id}/skills/install",
        "request_model": "anyagent.protocol.agent_api_internal.AdminSkillRegistryInstallRequest",
        "response_model": "anyagent.protocol.agent_api_internal.AdminSkillImportResponse",
    },
    {
        "operation": "admin.skill.update.check",
        "method": "GET",
        "path": "/admin/workspace/agents/{agent_id}/skills/{directory_name}/update/check",
        "response_model": "anyagent.protocol.agent_api_internal.AdminSkillUpdateCheckResponse",
    },
    {
        "operation": "admin.skill.update.apply",
        "method": "POST",
        "path": "/admin/workspace/agents/{agent_id}/skills/{directory_name}/update/apply",
        "request_format": "empty_json",
        "response_model": "anyagent.protocol.agent_api_internal.AdminSkillImportResponse",
    },
    {
        "operation": "admin.agent.skills.update",
        "method": "PUT",
        "path": "/admin/workspace/agents/{agent_id}/skills",
        "request_model": "anyagent.protocol.agent_api_internal.AdminAgentSkillsUpdateRequest",
        "response_model": "anyagent.protocol.agent_api_internal.AdminAgentCreateResponse",
    },
    {
        "operation": "admin.agent.config.update",
        "method": "PUT",
        "path": "/admin/workspace/agents/{agent_id}/config",
        "request_model": "anyagent.protocol.agent_api_internal.AdminAgentConfigUpdateRequest",
        "response_model": "anyagent.protocol.agent_api_internal.AdminAgentCreateResponse",
    },
]


SEMANTIC_RULES: dict[str, list[dict[str, Any]]] = {
    "anyagent.protocol.credential_vault.CredentialScope": [
        {
            "id": "credential_scope_agent_id_matches_level",
            "kind": "cross_field",
            "mode": "after_validation",
            "fields": ["level", "agent_id"],
            "description": "When level is agent, agent_id is required; when level is not agent, agent_id must be null.",
            "examples": {
                "valid": [{"level": "global"}, {"level": "agent", "agent_id": "main"}],
                "invalid": [{"level": "agent"}, {"level": "global", "agent_id": "main"}],
            },
        }
    ],
    "anyagent.protocol.mcp.MCPServerConfig": [
        {
            "id": "mcp_server_source_is_exactly_one_of_url_or_command",
            "kind": "cross_field",
            "mode": "after_validation",
            "fields": ["url", "command", "transport"],
            "description": "A server config must define exactly one source: url for streamable_http/sse or command for stdio. URL sources cannot use stdio; command sources cannot use streamable_http or sse.",
            "examples": {
                "valid": [{"url": "https://example.test/mcp"}, {"command": "mcp-server", "transport": "stdio"}],
                "invalid": [
                    {"url": "https://example.test/mcp", "command": "mcp-server"},
                    {"url": "https://example.test/mcp", "transport": "stdio"},
                    {"command": "mcp-server", "transport": "sse"},
                ],
            },
        }
    ],
    "anyagent.protocol.multi_agent.SpawnAgentArgs": [
        {
            "id": "spawn_agent_requires_consistent_agent_selector",
            "kind": "cross_field",
            "mode": "after_validation",
            "fields": ["agent_id", "agent_type"],
            "description": "spawn_agent requires agent_id. agent_type is a deprecated alias and must match agent_id when both are present.",
            "examples": {
                "valid": [{"agent_id": "worker"}, {"agent_id": "worker", "agent_type": "worker"}],
                "invalid": [{}, {"agent_id": "worker", "agent_type": "other"}],
            },
        }
    ],
    "anyagent.protocol.multi_agent.SendInputArgs": [
        {
            "id": "send_input_requires_message_or_items",
            "kind": "cross_field",
            "mode": "after_validation",
            "fields": ["message", "items"],
            "description": "send_input requires a non-empty message or at least one item.",
            "examples": {
                "valid": [{"id": "thread_1", "message": "continue"}, {"id": "thread_1", "items": [{"type": "message"}]}],
                "invalid": [{"id": "thread_1"}, {"id": "thread_1", "message": "   ", "items": []}],
            },
        }
    ],
    "anyagent.protocol.tool_runtime.ToolContext": [
        {
            "id": "tool_context_rejects_plaintext_secret_fields",
            "kind": "recursive_key_policy",
            "mode": "before_validation",
            "fields": ["*"],
            "description": "ToolContext must reference credentials via auth_ref or credential_id. Plaintext secret-like keys such as token, api_key, password, authorization, bearer_token, and common suffix variants are rejected recursively.",
            "examples": {
                "valid": [{"auth_ref": {"kind": "credential_id", "ref": "cred_demo"}}, {"credential_id": "cred_demo"}],
                "invalid": [{"token": "secret"}, {"nested": {"api_key": "secret"}}, {"items": [{"password": "secret"}]}],
            },
        }
    ],
}


def iter_protocol_model_classes() -> Iterator[type[BaseModel]]:
    """Yield Pydantic model classes owned by `anyagent.protocol.*` modules."""

    modules = sorted(
        (module_info.name for module_info in pkgutil.iter_modules(protocol_pkg.__path__, protocol_pkg.__name__ + ".")),
    )
    for module_name in modules:
        if module_name.endswith(".schema_export"):
            continue
        module = importlib.import_module(module_name)
        for _, obj in sorted(inspect.getmembers(module, inspect.isclass), key=lambda item: item[0]):
            if not issubclass(obj, BaseModel):
                continue
            if obj is BaseModel:
                continue
            if obj.__module__ != module.__name__:
                continue
            yield obj


def export_protocol_schema_bundle() -> dict[str, Any]:
    """
    Export the protocol model schemas used by server, SDKs and Studio.

    The output is deterministic so it can be checked into generated artifacts or
    compared in CI when the project chooses to publish a pinned schema bundle.
    """

    models: dict[str, Any] = {}
    for model_cls in iter_protocol_model_classes():
        key = f"{model_cls.__module__}.{model_cls.__name__}"
        models[key] = model_cls.model_json_schema(mode="validation")

    adapters: dict[str, Any] = {}
    for key, adapter in sorted(TYPE_ADAPTER_EXPORTS.items()):
        adapters[key] = adapter.json_schema(mode="validation")

    return {
        "schema_version": SCHEMA_BUNDLE_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "protocol_package": "anyagent.protocol",
        "changelog": export_protocol_changelog(),
        "endpoints": export_protocol_endpoints(),
        "models": dict(sorted(models.items())),
        "semantic_rules": export_semantic_rules(),
        "type_adapters": adapters,
    }


def export_openapi_document() -> dict[str, Any]:
    """
    Export a minimal OpenAPI 3.1 document from the protocol models and endpoint
    manifest.

    This is intentionally generated from the same SSOT as the SDK schema bundle:
    protocol Pydantic models provide component schemas, while `PROTOCOL_ENDPOINTS`
    owns operation/path/request/response metadata.
    """

    components: dict[str, Any] = {}
    for model_cls in iter_protocol_model_classes():
        key = f"{model_cls.__module__}.{model_cls.__name__}"
        components[key] = model_cls.model_json_schema(mode="validation")

    paths: dict[str, Any] = {}
    for endpoint in export_protocol_endpoints():
        path_item = paths.setdefault(endpoint["path"], {})
        method = str(endpoint["method"]).lower()
        operation = _openapi_operation(endpoint)
        if method in path_item:
            _merge_openapi_operations(path_item[method], operation)
        else:
            path_item[method] = operation

    return {
        "openapi": OPENAPI_VERSION,
        "info": {
            "title": "AnyAgent Protocol API",
            "version": SCHEMA_BUNDLE_VERSION,
        },
        "x-anyagent-schema-version": SCHEMA_BUNDLE_VERSION,
        "x-anyagent-protocol-version": PROTOCOL_VERSION,
        "x-anyagent-protocol-changelog": export_protocol_changelog(),
        "paths": dict(sorted(paths.items())),
        "components": {
            "schemas": dict(sorted(components.items())),
        },
    }


def _openapi_operation(endpoint: dict[str, Any]) -> dict[str, Any]:
    operation: dict[str, Any] = {
        "operationId": endpoint["operation"].replace(".", "_"),
        "x-anyagent-operation": endpoint["operation"],
        "x-anyagent-operations": [endpoint["operation"]],
        "tags": [str(endpoint["operation"]).split(".", 1)[0]],
        "responses": {
            "200": {
                "description": "Successful response",
                "content": _openapi_response_content(endpoint),
            }
        },
    }

    parameters = _openapi_path_parameters(endpoint["path"])
    if parameters:
        operation["parameters"] = parameters

    request_content = _openapi_request_content(endpoint)
    if request_content is not None:
        operation["requestBody"] = {
            "required": endpoint.get("request_format") not in {"empty", "empty_json"},
            "content": request_content,
        }

    return operation


def _merge_openapi_operations(target: dict[str, Any], extra: dict[str, Any]) -> None:
    """Merge logical AnyAgent operations that share one HTTP method/path."""

    for operation_name in extra.get("x-anyagent-operations", []):
        if operation_name not in target["x-anyagent-operations"]:
            target["x-anyagent-operations"].append(operation_name)
    if target.get("x-anyagent-operation") != extra.get("x-anyagent-operation"):
        target["x-anyagent-operation"] = target["x-anyagent-operations"][0]

    for tag in extra.get("tags", []):
        if tag not in target["tags"]:
            target["tags"].append(tag)

    target_content = target["responses"]["200"].setdefault("content", {})
    target_content.update(extra["responses"]["200"].get("content", {}))

    if "requestBody" not in target and "requestBody" in extra:
        target["requestBody"] = extra["requestBody"]


def _openapi_path_parameters(path: str) -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "in": "path",
            "required": True,
            "schema": {"type": "string"},
        }
        for name in re.findall(r"\{([^}]+)\}", path)
    ]


def _openapi_schema_ref(model_name: str) -> dict[str, str]:
    return {"$ref": f"#/components/schemas/{model_name}"}


def _openapi_request_content(endpoint: dict[str, Any]) -> dict[str, Any] | None:
    request_model = endpoint.get("request_model")
    if request_model:
        return {"application/json": {"schema": _openapi_schema_ref(request_model)}}

    request_format = endpoint.get("request_format")
    if request_format == "openai_responses_create":
        return {"application/json": {"schema": {"type": "object", "additionalProperties": True}}}
    if request_format == "empty_json":
        return {"application/json": {"schema": {"type": "object", "maxProperties": 0}}}
    return None


def _openapi_response_content(endpoint: dict[str, Any]) -> dict[str, Any]:
    response_model = endpoint.get("response_model")
    if response_model:
        return {"application/json": {"schema": _openapi_schema_ref(response_model)}}

    response_format = endpoint.get("response_format")
    if response_format == "openai_response_object":
        return {
            "application/json": {
                "schema": {
                    "type": "object",
                    "required": ["id"],
                    "properties": {
                        "id": {"type": "string"},
                        "object": {"type": "string"},
                        "status": {"type": "string"},
                    },
                    "additionalProperties": True,
                }
            }
        }
    if response_format == "responses_sse_stream":
        return {"text/event-stream": {"schema": {"type": "string"}}}
    return {"application/json": {"schema": {}}}


def export_protocol_endpoints() -> list[dict[str, Any]]:
    """Export stable API operation metadata for SDK generators and contract tests."""

    return sorted((dict(endpoint) for endpoint in PROTOCOL_ENDPOINTS), key=lambda item: item["operation"])


def export_semantic_rules() -> dict[str, list[dict[str, Any]]]:
    """Export non-JSON-Schema semantic rules required by SDK/runtime generators."""

    return {key: list(value) for key, value in sorted(SEMANTIC_RULES.items())}


def export_protocol_changelog() -> list[dict[str, Any]]:
    """Export protocol version history for SDK/runtime compatibility checks."""

    return [dict(entry) for entry in PROTOCOL_CHANGELOG]
