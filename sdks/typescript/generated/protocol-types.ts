/* eslint-disable */
// Generated from anyagent.protocol schema bundle. Do not edit by hand.
// schema_version: 2026-09-07

export type MCPServerTransport = "streamable_http" | "sse" | "stdio";

export type AdminSandboxRuntimeDiagnostics = {
  "created_at"?: string | null;
  "expires_at"?: string | null;
  "image_uri"?: string | null;
  "last_transition_at"?: string | null;
  "message"?: string | null;
  "provider": string;
  "reason"?: string | null;
  "sandbox_id"?: string | null;
  "state"?: string | null;
};

export type AdminSandboxWorkspaceEventsRequest = {
  "agent_id": string;
  "limit"?: number;
  "session_key": string;
};

export type AdminSandboxWorkspaceHealthResponse = {
  "backend": string;
  "enabled": boolean;
  "lease_backend": string;
  "metadata_backend": string;
  "persistence_mode": string;
  "runtime_providers"?: Array<string>;
  "runtime_states"?: Record<string, number>;
  "sandbox_mode": string;
  "sandbox_root_dir"?: string | null;
  "snapshot_backend": string;
  "workspace_count": number;
  "workspace_root": string;
};

export type AdminSandboxWorkspaceListResponse = {
  "workspaces"?: Array<AdminSandboxWorkspaceRef>;
};

export type AdminSandboxWorkspaceReclaimResponse = {
  "ok": boolean;
  "reclaimed": boolean;
  "session_partition_key": string;
  "workspace_id": string;
};

export type AdminSandboxWorkspaceRef = {
  "cold_expires_at_ms"?: number | null;
  "failure_code"?: string | null;
  "failure_message"?: string | null;
  "generation": number;
  "hot_expires_at_ms"?: number | null;
  "last_accessed_at_ms"?: number | null;
  "runtime_diagnostics"?: AdminSandboxRuntimeDiagnostics | null;
  "sandbox_id"?: string | null;
  "session_partition_key": string;
  "snapshot_bytes"?: number | null;
  "snapshot_digest"?: string | null;
  "snapshot_uri"?: string | null;
  "state": string;
  "tenant_id"?: string | null;
  "workspace_id": string;
  "workspace_root"?: string | null;
};

export type AdminSandboxWorkspaceRequest = {
  "agent_id": string;
  "session_key": string;
};

export type AdminSandboxWorkspaceSnapshotItem = {
  "created_at_ms"?: number | null;
  "generation": number;
  "session_partition_key": string;
  "snapshot_bytes"?: number | null;
  "snapshot_digest"?: string | null;
  "snapshot_uri": string;
  "workspace_id": string;
};

export type AdminSandboxWorkspaceSnapshotsResponse = {
  "session_partition_key": string;
  "snapshots"?: Array<AdminSandboxWorkspaceSnapshotItem>;
  "workspace_id": string;
};

export type StorageBackendConfig = {
  "event_store": string;
  "run_store": string;
  "session_lock": string;
  "session_store": string;
};

export type StorageComponentCapabilities = {
  "cross_instance": boolean;
  "long_term_owner": "anyagent" | "anyagent-apps";
  "requires_services"?: Array<string>;
  "restart_recovery": boolean;
  "source_of_truth": string;
  "supports_hibernation"?: boolean | null;
  "supports_idempotency"?: boolean | null;
  "supports_keyed_serialization"?: boolean | null;
  "supports_live_tail"?: boolean | null;
  "supports_replay"?: boolean | null;
  "supports_snapshot_cas"?: boolean | null;
  "supports_workspace_sessions"?: boolean | null;
  "tier": "reference" | "external";
};

export type StorageComponentHealth = {
  "layers"?: Array<string>;
  "type": string;
};

export type StorageHealthConnectivity = {
  "configured": boolean;
  "namespace"?: string | null;
  "reachable"?: boolean | null;
  "schema"?: string | null;
};

export type StorageHealthResponse = {
  "backends": StorageBackendConfig;
  "capabilities"?: Record<string, StorageComponentCapabilities>;
  "extra"?: Record<string, unknown>;
  "ok": boolean;
  "postgres": StorageHealthConnectivity;
  "redis": StorageHealthConnectivity;
  "retention_s": StorageRetentionConfig;
  "single_instance_only"?: boolean;
  "storage_mode": string;
  "storage_profile"?: string | null;
  "stores": Record<string, StorageComponentHealth>;
  "warnings"?: Array<string>;
};

export type StorageRetentionConfig = {
  "events": number;
  "runs": number;
  "sessions": number;
};

export type AdminAgentConfigUpdateRequest = {
  "disabled_skill_paths"?: Array<string> | null;
  "exposed"?: boolean | null;
  "model_api_key_env"?: string | null;
  "model_base_url_env"?: string | null;
  "model_default"?: string | null;
  "model_provider"?: string | null;
  "requested_tool_names"?: Array<string> | null;
  "sandbox_mode"?: "opensandbox" | "external" | "local-unsafe" | "disabled" | null;
  "spawn_allow_agent_ids"?: Array<string> | null;
};

export type AdminAgentCreateRequest = {
  "agent_id": string;
  "default_selected_skills"?: Array<string>;
  "exposed"?: boolean;
  "instructions": string;
  "model_api_key_env"?: string | null;
  "model_base_url_env"?: string | null;
  "model_default"?: string | null;
  "model_provider"?: string;
  "requested_tool_names"?: Array<string>;
  "sandbox_mode"?: "opensandbox" | "external" | "local-unsafe" | "disabled";
  "spawn_allow_agent_ids"?: Array<string>;
};

export type AdminAgentCreateResponse = {
  "agent": InternalAgentDetailResponse;
  "reloaded_agent_ids"?: Array<string>;
};

export type AdminAgentSkillsUpdateRequest = {
  "default_selected"?: Array<string>;
};

export type AdminMcpServerEnableRequest = {
  "enabled": boolean;
};

export type AdminMcpServerEnableResponse = {
  "agent_id": string;
  "enabled": boolean;
  "file": AdminWorkspaceAgentFile;
  "reloaded_agent_ids"?: Array<string>;
  "server_label": string;
  "servers": AdminMcpServersResponse;
};

export type AdminMcpServerItem = {
  "command"?: string | null;
  "credential_id"?: string | null;
  "enabled": boolean;
  "enablement": "enabled" | "disabled" | "inherited" | "invalid";
  "error"?: string | null;
  "idle_timeout_seconds"?: number | null;
  "label": string;
  "source"?: "agent" | "inherited" | "unknown";
  "timeout_seconds"?: number | null;
  "tool_filter"?: Record<string, unknown> | null;
  "transport"?: string | null;
  "url"?: string | null;
};

export type AdminMcpServersResponse = {
  "agent_id": string;
  "configured": boolean;
  "disabled_count"?: number;
  "enabled_count"?: number;
  "inherited_count"?: number;
  "invalid_count"?: number;
  "servers"?: Array<AdminMcpServerItem>;
};

export type AdminMcpServerTestResponse = {
  "agent_id": string;
  "message"?: string | null;
  "ok": boolean;
  "server_label": string;
  "status": "ready" | "failed" | "skipped";
  "tool_count"?: number | null;
  "transport"?: string | null;
};

export type AdminSkillImportRequest = {
  "directory_name": string;
  "overwrite"?: boolean;
  "skill_md": string;
};

export type AdminSkillImportResponse = {
  "agent_id": string;
  "name": string;
  "path": string;
  "reloaded_agent_ids"?: Array<string>;
  "sha256": string;
  "stable_id": string;
};

export type AdminSkillRegistryInstallRequest = {
  "channel"?: "skills.sh" | "registry" | "github";
  "directory_name"?: string | null;
  "github_path"?: string | null;
  "github_ref"?: string | null;
  "github_repo"?: string | null;
  "overwrite"?: boolean;
  "package": string;
  "skill": string;
};

export type AdminSkillUpdateCheckResponse = {
  "agent_id": string;
  "channel"?: string | null;
  "current_hash"?: string | null;
  "directory_name": string;
  "latest_hash"?: string | null;
  "reason"?: string | null;
  "source_ref"?: string | null;
  "updatable"?: boolean;
  "update_available"?: boolean;
};

export type AdminToolCatalogResponse = {
  "tools"?: Array<InternalToolCatalogItem>;
  "toolset_version": number;
};

export type AdminWorkspaceAgentFile = {
  "exists": boolean;
  "kind": "agents_md" | "agent_yaml" | "mcp_json";
  "path": string;
  "sha256"?: string | null;
  "text"?: string | null;
};

export type AdminWorkspaceAgentFilesResponse = {
  "agent_id": string;
  "files"?: Array<AdminWorkspaceAgentFile>;
};

export type AdminWorkspaceAgentFileUpdateRequest = {
  "expected_sha256"?: string | null;
  "text": string;
};

export type AdminWorkspaceAgentFileUpdateResponse = {
  "agent_id": string;
  "file": AdminWorkspaceAgentFile;
  "reloaded_agent_ids"?: Array<string>;
};

export type InternalAgentDetailResponse = {
  "agent_id": string;
  "agents_md": InternalAgentPromptRef;
  "exposed": boolean;
  "mcp"?: InternalAgentMCPConfig;
  "model"?: InternalAgentModelConfig;
  "multiagent"?: Record<string, unknown>;
  "name": string;
  "root_dir": string;
  "sandbox"?: Record<string, unknown>;
  "skills": InternalAgentSkillsConfig;
  "tools": InternalAgentToolsConfig;
  "workspace_agents_md"?: InternalAgentPromptRef | null;
};

export type InternalAgentListItem = {
  "agent_id": string;
  "default_selected_skill_ids"?: Array<string>;
  "exposed": boolean;
  "has_mcp"?: boolean;
  "mcp_server_labels"?: Array<string>;
  "model_api_key_env"?: string | null;
  "model_base_url_env"?: string | null;
  "model_default"?: string | null;
  "model_provider"?: string;
  "name": string;
  "prompt_sha256": string;
  "requested_tool_names"?: Array<string>;
  "root_dir": string;
  "sandbox_mode": "opensandbox" | "external" | "local-unsafe" | "disabled";
  "spawn_allow_agent_ids"?: Array<string>;
  "workspace_prompt_sha256"?: string | null;
};

export type InternalAgentMCPConfig = {
  "configured"?: boolean;
  "server_labels"?: Array<string>;
};

export type InternalAgentModelConfig = {
  "api_key_env"?: string | null;
  "base_url_env"?: string | null;
  "default"?: string | null;
  "provider"?: string;
};

export type InternalAgentPromptRef = {
  "path": string;
  "preview"?: string | null;
  "sha256": string;
  "text"?: string | null;
};

export type InternalAgentSkillsConfig = {
  "default_selected"?: Array<string> | null;
  "disabled_paths"?: Array<string> | null;
};

export type InternalAgentsListResponse = {
  "agents"?: Array<InternalAgentListItem>;
};

export type InternalAgentToolsConfig = {
  "allow_tools"?: Array<string> | null;
  "deny_tools"?: Array<string> | null;
  "requested_tool_names"?: Array<string>;
};

export type InternalAuditEventItem = {
  "agent_id"?: string | null;
  "audit_ref"?: string | null;
  "category"?: string | null;
  "credential_id"?: string | null;
  "duration_ms"?: number | null;
  "level"?: "debug" | "info" | "warning" | "error" | null;
  "message"?: string | null;
  "payload"?: Record<string, unknown>;
  "response_id"?: string | null;
  "seq"?: number | null;
  "session_key"?: string | null;
  "source": "run" | "event" | "stage" | "observability" | "workspace" | "audit";
  "status"?: string | null;
  "tool_call_id"?: string | null;
  "tool_name"?: string | null;
  "tool_source"?: string | null;
  "trace_id"?: string | null;
  "ts_ms"?: number | null;
  "type": string;
};

export type InternalAuditEventsResponse = {
  "agent_id"?: string | null;
  "credential_id"?: string | null;
  "events"?: Array<InternalAuditEventItem>;
  "response_id"?: string | null;
  "session_key"?: string | null;
  "trace_id"?: string | null;
};

export type InternalEventItem = {
  "data": string;
  "event"?: string | null;
  "seq": number;
};

export type InternalEventsListResponse = {
  "done": boolean;
  "effective_run_status"?: string | null;
  "events"?: Array<InternalEventItem>;
  "next_last_seq": number;
  "requested_last_seq": number;
  "response_id": string;
  "run_status"?: string | null;
};

export type InternalEventsReplaySummary = {
  "done": boolean;
  "effective_run_status"?: string | null;
  "next_last_seq": number;
  "page_event_count"?: number;
  "prompt_context"?: AnyAgentPromptContextEvent | null;
  "requested_last_seq": number;
  "response_id": string;
  "run_status"?: string | null;
  "scanned_pages"?: number;
  "typed_event_count"?: number;
};

export type InternalObservabilityErrorItem = {
  "agent_id"?: string | null;
  "audit_ref"?: string | null;
  "message"?: string | null;
  "payload"?: Record<string, unknown>;
  "response_id"?: string | null;
  "retryable"?: boolean | null;
  "session_key"?: string | null;
  "source": "run" | "event" | "stage" | "observability" | "workspace" | "audit";
  "tool_call_id"?: string | null;
  "tool_name"?: string | null;
  "trace_id"?: string | null;
  "ts_ms"?: number | null;
  "type": string;
};

export type InternalObservabilityErrorsResponse = {
  "agent_id"?: string | null;
  "errors"?: Array<InternalObservabilityErrorItem>;
  "response_id"?: string | null;
  "session_key"?: string | null;
};

export type InternalObservabilityMetricsResponse = {
  "agent_id"?: string | null;
  "avg_mcp_calls_per_session"?: number | null;
  "avg_response_latency_ms"?: number | null;
  "avg_tool_calls_per_session"?: number | null;
  "cached_input_tokens"?: number;
  "error_count"?: number;
  "event_count"?: number;
  "first_token_latency_ms"?: number | null;
  "input_tokens"?: number;
  "max_response_latency_ms"?: number | null;
  "mcp_call_count"?: number;
  "output_tokens"?: number;
  "response_id"?: string | null;
  "run_count"?: number;
  "session_count"?: number;
  "session_key"?: string | null;
  "tool_call_count"?: number;
  "tool_call_counts_by_source"?: Record<string, number>;
  "truncated"?: boolean;
};

export type InternalObservabilityRunItem = {
  "agent_id": string;
  "created_at_ms": number;
  "effective_status": string;
  "ended_at_ms"?: number | null;
  "response_id": string;
  "session_key": string;
  "status": string;
  "stream": boolean;
  "updated_at_ms": number;
};

export type InternalObservabilityRunsResponse = {
  "agent_id"?: string | null;
  "response_id"?: string | null;
  "runs"?: Array<InternalObservabilityRunItem>;
  "session_key"?: string | null;
};

export type InternalObservabilitySummaryResponse = {
  "agent_id"?: string | null;
  "cached_input_tokens"?: number;
  "compaction_count"?: number;
  "effective_run_status"?: string | null;
  "event_count"?: number;
  "first_token_latency_ms"?: number | null;
  "input_chars"?: number;
  "input_tokens"?: number;
  "loop_warnings_count"?: number;
  "mcp_call_count"?: number;
  "output_chars"?: number;
  "output_tokens"?: number;
  "response_id": string;
  "run_status"?: string | null;
  "session_key"?: string | null;
  "skill_view_count"?: number;
  "subagent_spawns"?: number;
  "tool_call_count"?: number;
  "tool_call_counts_by_source"?: Record<string, number>;
  "total_response_latency_ms"?: number | null;
  "truncated"?: boolean;
  "turn_count"?: number;
  "turns"?: Array<InternalObservabilityTurnMetric>;
  "typed_event_count"?: number;
};

export type InternalObservabilityTimelineEvent = {
  "agent_id"?: string | null;
  "audit_ref"?: string | null;
  "category"?: string | null;
  "duration_ms"?: number | null;
  "level"?: "debug" | "info" | "warning" | "error" | null;
  "message"?: string | null;
  "payload"?: Record<string, unknown>;
  "response_id"?: string | null;
  "seq"?: number | null;
  "session_key"?: string | null;
  "source": "run" | "event" | "stage" | "observability" | "workspace" | "audit";
  "status"?: string | null;
  "tool_call_id"?: string | null;
  "tool_name"?: string | null;
  "tool_source"?: string | null;
  "trace_id"?: string | null;
  "ts_ms"?: number | null;
  "type": string;
};

export type InternalObservabilityTimelineResponse = {
  "agent_id"?: string | null;
  "events"?: Array<InternalObservabilityTimelineEvent>;
  "response_id"?: string | null;
  "session_key"?: string | null;
  "trace_id"?: string | null;
};

export type InternalObservabilityToolsResponse = {
  "agent_id"?: string | null;
  "response_id"?: string | null;
  "session_key"?: string | null;
  "tools"?: Array<InternalObservabilityToolStats>;
};

export type InternalObservabilityToolStats = {
  "audit_refs"?: Array<string>;
  "avg_duration_ms"?: number | null;
  "error_count"?: number;
  "last_status"?: string | null;
  "max_duration_ms"?: number | null;
  "planned_count"?: number;
  "result_count"?: number;
  "tool_name": string;
  "tool_source"?: string | null;
};

export type InternalObservabilityTraceResponse = {
  "audit_refs"?: Array<string>;
  "events"?: Array<InternalObservabilityTimelineEvent>;
  "response_ids"?: Array<string>;
  "trace_id": string;
};

export type InternalObservabilityTurnMetric = {
  "index": number;
  "input_chars"?: number;
  "output_chars"?: number;
};

export type InternalPromptBundlePreviewResponse = {
  "agent_id": string;
  "applied_body"?: Record<string, unknown>;
  "effective_body"?: Record<string, unknown>;
  "instruction_role": "developer" | "system";
  "manifest_tool_names"?: Array<string>;
  "manifest_tools"?: Array<AnyAgentFunctionToolParam>;
  "mcp_servers"?: Array<string>;
  "model"?: string | null;
  "prompt_cache_key"?: string | null;
  "prompt_context": PromptContextAudit;
  "rendered_fragments"?: Array<RenderedPromptFragment>;
  "selected_skill_ids"?: Array<string>;
  "session_key": string;
  "tool_context"?: Record<string, unknown>;
};

export type InternalResponseModelRequestResponse = {
  "applied_body"?: Record<string, unknown> | null;
  "prompt_cache_key"?: string | null;
  "response_id": string;
};

export type InternalResponsePromptContextResponse = {
  "audit_event"?: AnyAgentPromptContextEvent | null;
  "fallback"?: "rendered" | "audit" | "missing";
  "fragments"?: Array<RenderedPromptFragment>;
  "prompt_cache_key"?: string | null;
  "rendered_event"?: AnyAgentPromptContextRenderedEvent | null;
  "response_id": string;
  "total_chars"?: number;
};

export type InternalResponseToolExecutionsResponse = {
  "response_id": string;
  "tool_executions"?: Array<AnyAgentToolExecutionDetailEvent>;
};

export type InternalSessionDetailResponse = {
  "agent_id": string;
  "runs"?: Array<InternalObservabilityRunItem>;
  "session_key": string;
  "session_partition_key": string;
  "snapshot_json"?: Record<string, unknown> | null;
  "snapshot_version"?: number | null;
  "summary": InternalSessionSummary;
};

export type InternalSessionsListResponse = {
  "agent_id"?: string | null;
  "cursor_updated_before_ms"?: number | null;
  "next_cursor_updated_before_ms"?: number | null;
  "session_key"?: string | null;
  "sessions"?: Array<InternalSessionSummary>;
};

export type InternalSessionSummary = {
  "active_run_count"?: number;
  "agent_id": string;
  "created_at_ms"?: number;
  "error_run_count"?: number;
  "latest_effective_status"?: string | null;
  "latest_response_id"?: string | null;
  "latest_status"?: string | null;
  "run_count"?: number;
  "session_key": string;
  "session_partition_key": string;
  "snapshot_version"?: number | null;
  "updated_at_ms"?: number;
};

export type InternalSkillListItem = {
  "description"?: string | null;
  "enabled": boolean;
  "interface"?: Record<string, unknown> | null;
  "name": string;
  "path": string;
  "requested_tool_names"?: Array<string>;
  "scope": string;
  "selected"?: boolean;
  "short_description"?: string | null;
  "source_hash"?: string | null;
  "stable_id": string;
};

export type InternalSkillLoadError = {
  "path": string;
  "reason": string;
  "scope": "global" | "agent";
};

export type InternalSkillsListResponse = {
  "agent_id": string;
  "disabled_paths"?: Array<string>;
  "load_errors"?: Array<InternalSkillLoadError>;
  "skills"?: Array<InternalSkillListItem>;
};

export type InternalToolCatalogItem = {
  "decision"?: string;
  "description"?: string | null;
  "kind"?: string | null;
  "name": string;
  "parameters"?: Record<string, unknown> | null;
  "reason"?: string | null;
};

export type InternalToolCatalogResponse = {
  "agent_id": string;
  "requested_tool_names"?: Array<string>;
  "session_key": string;
  "tools"?: Array<InternalToolCatalogItem>;
  "toolset_version": number;
};

export type PromptRunBundleExampleOptions = {
  "include_mcp"?: boolean | null;
  "sandbox_mode"?: "opensandbox" | "external" | "local-unsafe" | "disabled" | null;
  "skill_count"?: number | null;
  "user_input"?: string | null;
};

export type PromptRunBundleExampleResponse = {
  "agent_id": string;
  "explanation": PromptRunBundleExplanation;
  "model": string;
  "model_response"?: Record<string, unknown>;
  "options"?: PromptRunBundleExampleOptions;
  "prompt_bundle": InternalPromptBundlePreviewResponse;
  "response_id": string;
  "scenario": "sandbox_file_write" | "multi_skill_research" | "toolset_retry";
  "scenario_label": string;
  "session_key": string;
  "stage_events"?: Array<AnyAgentModelStreamEvent | AnyAgentToolPlannedEvent | AnyAgentToolResultEvent | AnyAgentToolExecutionDetailEvent | AnyAgentCommandPlannedEvent | AnyAgentCommandResultEvent | AnyAgentPromptContextEvent | AnyAgentPromptContextRenderedEvent | AnyAgentModelRequestEvent | AnyAgentScriptedReplyEvent | AnyAgentWorkspaceLifecycleEvent | AnyAgentMcpServerLifecycleEvent | AnyAgentSubAgentSpawnedEvent | AnyAgentSubAgentCompletedEvent | AnyAgentSubAgentTimeoutEvent | AnyAgentContextCompactedEvent | AnyAgentLoopWarningEvent | AnyAgentLoopTerminatedEvent | AnyAgentDoneEvent>;
  "tool_loop_items"?: Array<PromptRunBundleToolLoopItem>;
};

export type PromptRunBundleExplanation = {
  "key_takeaways"?: Array<string>;
  "steps"?: Array<PromptRunBundleExplanationStep>;
  "summary": string;
  "why_this_shape": string;
};

export type PromptRunBundleExplanationStep = {
  "cites"?: Array<string>;
  "detail": string;
  "title": string;
};

export type PromptRunBundleScenarioDescriptor = {
  "default_options"?: PromptRunBundleExampleOptions;
  "label": string;
  "scenario": "sandbox_file_write" | "multi_skill_research" | "toolset_retry";
  "summary": string;
  "supports_mcp_toggle"?: boolean;
  "supports_sandbox_override"?: boolean;
  "supports_skill_count"?: boolean;
};

export type PromptRunBundleToolLoopItem = {
  "item"?: Record<string, unknown>;
  "phase": "model_function_call" | "tool_output_to_model" | "assistant_message";
};

export type ToolRequestSource = {
  "pattern": string;
  "selected"?: boolean | null;
  "skill_id"?: string | null;
  "skill_name"?: string | null;
  "source": "agent" | "skill" | "probe";
};

export type ToolVisibilityExplanation = {
  "agent_id": string;
  "effective_tool"?: InternalToolCatalogItem | null;
  "load_errors"?: Array<InternalSkillLoadError>;
  "notes"?: Array<string>;
  "policy_allow_tools"?: Array<string> | null;
  "policy_deny_tools"?: Array<string> | null;
  "request_sources"?: Array<ToolRequestSource>;
  "requested_patterns"?: Array<string>;
  "selected_skill_ids"?: Array<string>;
  "session_key": string;
  "tool_name": string;
  "visible": boolean;
  "visible_tools"?: Array<string>;
  "visible_without_probe": boolean;
};

export type AlertChannel = {
  "format"?: "json" | "feishu";
  "headers"?: Record<string, string>;
  "kind"?: "webhook";
  "url": string;
};

export type AlertEvent = {
  "agent_id"?: string | null;
  "alert_id": string;
  "message": string;
  "payload"?: Record<string, unknown>;
  "response_id"?: string | null;
  "rule_id": string;
  "rule_name": string;
  "session_key"?: string | null;
  "severity": "info" | "warning" | "error" | "critical";
  "source_event_type"?: string | null;
  "source_seq"?: number | null;
  "status"?: "active" | "resolved";
  "trace_id"?: string | null;
  "ts_ms"?: number;
  "type": string;
};

export type AlertEventsResponse = {
  "agent_id"?: string | null;
  "alerts"?: Array<AlertEvent>;
  "response_id"?: string | null;
  "session_key"?: string | null;
  "trace_id"?: string | null;
};

export type AlertRule = {
  "channels"?: Array<AlertChannel>;
  "enabled"?: boolean;
  "event_types"?: Array<string>;
  "kind"?: "stage_event";
  "name": string;
  "rule_id": string;
  "severity"?: "info" | "warning" | "error" | "critical";
};

export type AlertRulesResponse = {
  "rules"?: Array<AlertRule>;
};

export type CommandPlannedFields = {
  "command": string;
  "timeout_ms"?: number | null;
  "workdir"?: string | null;
};

export type CommandResultFields = {
  "exit_code"?: number | null;
  "stderr"?: unknown | null;
  "stdout"?: unknown | null;
};

export type ContextFragment = {
  "body"?: string;
  "cache_class"?: "stable_prefix" | "contextual" | "dynamic";
  "kind": "agents_instructions" | "skill" | "skill_catalog" | "business_context" | "channel_context" | "environment_context" | "mcp_server_ref" | "page_context" | "tool_catalog_delta" | "sandbox_guidance";
  "label"?: string | null;
  "metadata"?: Record<string, string>;
  "role"?: "developer" | "system";
  "scope"?: string | null;
  "source_hash"?: string | null;
  "source_path"?: string | null;
  "stable_id"?: string | null;
};

export type AdminCredentialDeleteResponse = {
  "credential_id": string;
  "deleted": boolean;
  "ok": boolean;
};

export type AdminCredentialListResponse = {
  "credentials": Array<AdminCredentialRef>;
};

export type AdminCredentialRef = {
  "credential_id": string;
  "expires_at"?: string | null;
  "kind": string;
  "metadata"?: Record<string, unknown>;
  "rotate_before"?: string | null;
  "scope": CredentialScope;
};

export type AdminCredentialSetRequest = {
  "credential_id": string;
  "expires_at"?: string | null;
  "kind": string;
  "metadata"?: Record<string, unknown>;
  "rotate_before"?: string | null;
  "scope": CredentialScope;
  "value": string;
};

export type CredentialBackendCapability = {
  "default_for"?: Array<string>;
  "description": string;
  "display_name": string;
  "kind": "resolver" | "admin_store";
  "mode": string;
  "read_only": boolean;
  "requires_env"?: Array<string>;
  "requires_extras"?: Array<string>;
  "source": string;
  "status"?: "stable" | "preview" | "planned";
  "supports_delete": boolean;
  "supports_list_refs": boolean;
  "supports_resolve": boolean;
  "supports_set": boolean;
};

export type CredentialBackendCapabilityMatrix = {
  "admin_store_modes": Array<CredentialBackendCapability>;
  "environment_variable"?: string;
  "resolver_modes": Array<CredentialBackendCapability>;
  "secret_value_returned"?: boolean;
};

export type CredentialScope = {
  "agent_id"?: string | null;
  "level": "global" | "agent" | "session";
  "session_key"?: string | null;
};

export type EvalCase = {
  "case_id": string;
  "expected_output"?: string | null;
  "input": string;
  "metadata"?: Record<string, unknown>;
};

export type EvalCaseResult = {
  "actual_output"?: string | null;
  "case_id": string;
  "error"?: string | null;
  "expected_output"?: string | null;
  "response_id"?: string | null;
  "score"?: number | null;
  "status": "passed" | "failed" | "unscored" | "error";
};

export type EvalDataset = {
  "agent_id"?: string | null;
  "cases"?: Array<EvalCase>;
  "created_at_ms"?: number;
  "dataset_id": string;
  "description"?: string | null;
  "metadata"?: Record<string, unknown>;
  "name": string;
  "updated_at_ms"?: number;
};

export type EvalDatasetResponse = {
  "dataset": EvalDataset;
};

export type EvalDatasetsResponse = {
  "datasets"?: Array<EvalDataset>;
};

export type EvalDatasetUpsertRequest = {
  "agent_id"?: string | null;
  "cases"?: Array<EvalCase>;
  "dataset_id"?: string | null;
  "description"?: string | null;
  "metadata"?: Record<string, unknown>;
  "name": string;
};

export type EvalRun = {
  "agent_id": string;
  "completed_at_ms"?: number | null;
  "created_at_ms"?: number;
  "dataset_id": string;
  "error_cases"?: number;
  "eval_run_id": string;
  "failed_cases"?: number;
  "metadata"?: Record<string, unknown>;
  "passed_cases"?: number;
  "results"?: Array<EvalCaseResult>;
  "status": "queued" | "running" | "completed" | "failed";
  "total_cases"?: number;
  "unscored_cases"?: number;
};

export type EvalRunRequest = {
  "agent_id"?: string | null;
  "dataset_id": string;
  "max_cases"?: number | null;
  "metadata"?: Record<string, unknown>;
  "model"?: string | null;
  "session_key_prefix"?: string;
};

export type EvalRunResponse = {
  "run": EvalRun;
};

export type EvalRunsResponse = {
  "dataset_id"?: string | null;
  "runs"?: Array<EvalRun>;
};

export type HealthResponse = {
  "agent_ids"?: Array<string>;
  "ok": boolean;
  "workspace": string;
};

export type MCPConfig = {
  "mcpServers": Record<string, MCPServerConfig>;
};

export type MCPServerAuthConfig = {
  "credential_id": string;
  "format"?: string;
  "injection"?: string;
  "ref_kind"?: string;
};

export type MCPServerConfig = {
  "args"?: Array<string> | null;
  "auth"?: MCPServerAuthConfig | null;
  "command"?: string | null;
  "cwd"?: string | null;
  "enabled"?: boolean;
  "env"?: Record<string, string> | null;
  "headers"?: Record<string, string> | null;
  "idle_timeout_seconds"?: number;
  "timeout_seconds"?: number;
  "tool_filter"?: MCPToolFilterConfig | null;
  "transport"?: MCPServerTransport | null;
  "url"?: string | null;
};

export type MCPToolFilterConfig = {
  "allowed_tool_names"?: Array<string> | null;
  "blocked_tool_names"?: Array<string> | null;
  "match_mode"?: "raw" | "sanitized" | "both";
};

export type AgentState = {
  "message"?: string | null;
  "status": "queued" | "running" | "completed" | "failed" | "closed";
};

export type CloseAgentArgs = {
  "id": string;
};

export type CloseAgentResult = {
  "ok": boolean;
};

export type ResumeAgentArgs = {
  "id": string;
};

export type ResumeAgentResult = {
  "ok": boolean;
};

export type SendInputArgs = {
  "id": string;
  "interrupt"?: boolean | null;
  "items"?: Array<Record<string, unknown>> | null;
  "message"?: string | null;
};

export type SendInputResult = {
  "submission_id": string;
};

export type SpawnAgentArgs = {
  "agent_id"?: string | null;
  "agent_type"?: string | null;
  "fork_context"?: boolean;
  "items"?: Array<Record<string, unknown>> | null;
  "message"?: string | null;
  "skills"?: Array<string> | null;
};

export type SpawnAgentResult = {
  "agent_id": string;
  "nickname"?: string | null;
  "thread_id": string;
};

export type TaskArgs = {
  "agent_id": string;
  "context_mode"?: "isolated" | "fork_last_n" | null;
  "description": string;
  "prompt": string;
};

export type TaskResult = {
  "agent_id": string;
  "output_text": string;
};

export type WaitArgs = {
  "ids": Array<string>;
  "timeout_ms"?: number;
};

export type WaitResult = {
  "agents_states": Record<string, AgentState>;
  "timed_out": boolean;
};

export type NormalizedTelemetryEvent = {
  "agent_id"?: string | null;
  "audit_ref"?: string | null;
  "category"?: string | null;
  "duration_ms"?: number | null;
  "level"?: "debug" | "info" | "warning" | "error" | null;
  "message"?: string | null;
  "payload"?: Record<string, unknown>;
  "response_id"?: string | null;
  "seq"?: number | null;
  "session_key"?: string | null;
  "source": "run" | "event" | "stage" | "observability" | "workspace" | "audit";
  "status"?: string | null;
  "tool_call_id"?: string | null;
  "tool_name"?: string | null;
  "tool_source"?: string | null;
  "trace_id"?: string | null;
  "ts_ms"?: number | null;
  "type": string;
};

export type ObservabilityEvent = {
  "category"?: "audit" | "runtime" | "security" | "mcp" | "server";
  "event": string;
  "level"?: "debug" | "info" | "warning" | "error";
  "payload"?: Record<string, unknown>;
  "ts_ms"?: number;
};

export type AnyAgentFunctionToolParam = {
  "description"?: string | null;
  "name": string;
  "parameters"?: Record<string, unknown>;
  "strict"?: boolean;
  "type"?: "function";
  "x-anyagent-cli"?: Record<string, unknown> | null;
  "x-anyagent-kind"?: "command" | "mcp" | null;
  "x-anyagent-source-name"?: string | null;
};

export type PluginCapability = {
  "capability": "channels" | "webhook_routes" | "skills" | "mcp_servers" | "tools" | "middlewares" | "hooks";
  "description": string;
  "host": "gateway" | "tool_runtime";
  "manifest_field"?: string | null;
  "registration_api"?: string | null;
  "source": string;
  "status"?: "stable" | "preview" | "planned";
};

export type PluginCapabilityMatrix = {
  "capabilities"?: Array<PluginCapability>;
  "manifest_schema": string;
  "manifest_version"?: string;
};

export type LoadedPluginCatalogItem = {
  "channels"?: Array<string>;
  "cite"?: Record<string, string>;
  "declared_hooks"?: Array<string>;
  "declared_mcp_servers"?: Array<string>;
  "declared_middlewares"?: Array<string>;
  "declared_skills"?: Array<string>;
  "description"?: string | null;
  "docs"?: Array<string>;
  "entrypoint": string;
  "plugin_dir": string;
  "plugin_id": string;
  "schemas"?: Array<string>;
  "tests"?: Array<string>;
  "tools"?: Array<PluginToolRef>;
};

export type PluginCatalogResponse = {
  "errors"?: Array<PluginLoadErrorItem>;
  "loaded"?: Array<LoadedPluginCatalogItem>;
  "plugin_roots"?: Array<string>;
};

export type PluginLoadErrorItem = {
  "plugin_dir": string;
  "reason": string;
};

export type PluginToolRef = {
  "category": string;
  "description"?: string | null;
  "kind"?: string | null;
  "name": string;
};

export type PromptContextAudit = {
  "compacted"?: boolean;
  "contextual_count"?: number;
  "dynamic_count"?: number;
  "fragment_count"?: number;
  "fragment_kinds"?: Array<string>;
  "fragments"?: Array<PromptFragmentSummary>;
  "prompt_cache_key"?: string | null;
  "retained_fragment_count"?: number;
  "stable_prefix_count"?: number;
};

export type PromptEnvelope = {
  "fragments"?: Array<ContextFragment>;
  "prompt_cache_key"?: string | null;
};

export type PromptFragmentSummary = {
  "cache_class": string;
  "kind": string;
  "scope"?: string | null;
  "source_hash"?: string | null;
  "source_path"?: string | null;
  "stable_id"?: string | null;
};

export type RenderedPromptFragment = {
  "cache_class": string;
  "kind": string;
  "label"?: string | null;
  "metadata"?: Record<string, string>;
  "rendered_text": string;
  "role": string;
  "scope"?: string | null;
  "source_hash"?: string | null;
  "source_path"?: string | null;
  "stable_id"?: string | null;
};

export type PromptVersionCreateRequest = {
  "agent_id": string;
  "label"?: string | null;
};

export type PromptVersionDiffResponse = {
  "agent_id": string;
  "diff": string;
  "from_version_id": string;
  "to_version_id": string;
};

export type PromptVersionResponse = {
  "version": PromptVersionSnapshot;
};

export type PromptVersionRestoreResponse = {
  "agent_id": string;
  "restored_paths"?: Array<string>;
  "version_id": string;
};

export type PromptVersionSnapshot = {
  "agent_id": string;
  "combined_sha256": string;
  "created_at_ms"?: number;
  "label"?: string | null;
  "sources"?: Array<PromptVersionSource>;
  "version_id": string;
};

export type PromptVersionSource = {
  "kind": "workspace_agents_md" | "agent_agents_md" | "agent_yaml" | "mcp_json";
  "path": string;
  "sha256": string;
  "text": string;
};

export type PromptVersionsResponse = {
  "agent_id": string;
  "versions"?: Array<PromptVersionSnapshot>;
};

export type AnyAgentResponseError = {
  "code"?: string | null;
  "message": string;
  "type": string;
};

export type AnyAgentResponseStatusPayload = {
  "error"?: AnyAgentResponseError | null;
  "id": string;
  "object"?: "response";
  "status": "in_progress" | "completed" | "failed" | "cancelled";
};

export type FileSystemSandboxPolicy = {
  "cold_retention_s"?: number | null;
  "hot_idle_ttl_s"?: number | null;
  "max_snapshot_bytes"?: number | null;
  "persistence_mode"?: "ephemeral" | "session_hot_cold";
  "workspace_root"?: string;
};

export type NetworkSandboxPolicy = {
  "allow_hosts"?: Array<string> | null;
  "deny_hosts"?: Array<string> | null;
  "enabled"?: boolean;
};

export type ResourceLimits = {
  "cpu_cores"?: number | null;
  "disk_mb"?: number | null;
  "memory_mb"?: number | null;
  "output_max_bytes"?: number | null;
};

export type SandboxPolicy = {
  "filesystem"?: FileSystemSandboxPolicy | null;
  "mode"?: "opensandbox" | "external" | "local-unsafe" | "disabled";
  "network"?: NetworkSandboxPolicy | null;
  "resource_limits"?: ResourceLimits | null;
  "ttl_seconds"?: number | null;
};

export type ScriptedReply = {
  "content_attributes"?: Record<string, unknown> | null;
  "content_type"?: string | null;
  "reason"?: string | null;
  "text": string;
  "variant_id"?: string | null;
};

export type PersistedSessionSnapshot = {
  "last_run"?: SessionLastRun | null;
  "provider"?: string;
  "resume_cursor"?: SessionResumeCursor;
  "runtime_config"?: Record<string, unknown>;
};

export type SessionLastRun = {
  "last_event_seq"?: number;
  "prompt_context"?: PromptContextAudit | null;
  "response_id"?: string | null;
  "updated_at_ms"?: number | null;
};

export type SessionResumeCursor = {
  "fallback_transcript_items"?: Array<Record<string, unknown>>;
  "last_response_id"?: string | null;
};

export type AnyAgentCommandPlannedEvent = {
  "command": StagePayloadSummary;
  "response_id": string;
  "seq"?: number | null;
  "source_tool_call_id": string;
  "source_tool_name": string;
  "timeout_ms"?: number | null;
  "trace_id"?: string | null;
  "ts_ms"?: number | null;
  "type"?: "anyagent.command.planned";
  "workdir"?: string | null;
};

export type AnyAgentCommandResultEvent = {
  "duration_ms"?: number | null;
  "exit_code"?: number | null;
  "response_id": string;
  "seq"?: number | null;
  "source_tool_call_id": string;
  "source_tool_name": string;
  "stderr"?: StagePayloadSummary | null;
  "stdout"?: StagePayloadSummary | null;
  "trace_id"?: string | null;
  "ts_ms"?: number | null;
  "type"?: "anyagent.command.result";
};

export type AnyAgentContextCompactedEvent = {
  "items_after": number;
  "items_before": number;
  "reason"?: string | null;
  "response_id": string;
  "seq"?: number | null;
  "skipped"?: boolean;
  "summary"?: StagePayloadSummary | null;
  "tokens_after": number;
  "tokens_before": number;
  "trace_id"?: string | null;
  "ts_ms"?: number | null;
  "type"?: "anyagent.context.compacted";
};

export type AnyAgentDoneEvent = {
  "response_id": string;
  "seq"?: number | null;
  "trace_id"?: string | null;
  "ts_ms"?: number | null;
  "type"?: "anyagent.done";
};

export type AnyAgentLoopTerminatedEvent = {
  "hard_limit": number;
  "repeat_count": number;
  "response_id": string;
  "seq"?: number | null;
  "tool_signature": string;
  "trace_id"?: string | null;
  "ts_ms"?: number | null;
  "type"?: "anyagent.agent.loop_terminated";
};

export type AnyAgentLoopWarningEvent = {
  "repeat_count": number;
  "response_id": string;
  "seq"?: number | null;
  "tool_signature": string;
  "trace_id"?: string | null;
  "ts_ms"?: number | null;
  "type"?: "anyagent.agent.loop_warning";
  "window_size": number;
};

export type AnyAgentMcpServerLifecycleEvent = {
  "error"?: StageError | null;
  "response_id": string;
  "seq"?: number | null;
  "server_label": string;
  "trace_id"?: string | null;
  "transport"?: string | null;
  "ts_ms"?: number | null;
  "type": "anyagent.mcp.server.starting" | "anyagent.mcp.server.ready" | "anyagent.mcp.server.failed";
};

export type AnyAgentModelRequestEvent = {
  "applied_body"?: Record<string, unknown>;
  "prompt_cache_key"?: string | null;
  "response_id": string;
  "seq"?: number | null;
  "trace_id"?: string | null;
  "ts_ms"?: number | null;
  "type"?: "anyagent.model.request";
};

export type AnyAgentModelStreamEvent = {
  "payload": Record<string, unknown>;
  "response_id": string;
  "seq"?: number | null;
  "sse_event"?: string | null;
  "trace_id"?: string | null;
  "ts_ms"?: number | null;
  "type"?: "anyagent.model.stream_event";
};

export type AnyAgentPromptContextEvent = {
  "compacted"?: boolean;
  "contextual_count"?: number;
  "dynamic_count"?: number;
  "fragment_count"?: number;
  "fragment_kinds"?: Array<string>;
  "fragments"?: Array<PromptFragmentSummary>;
  "prompt_cache_key"?: string | null;
  "response_id": string;
  "retained_fragment_count"?: number;
  "seq"?: number | null;
  "stable_prefix_count"?: number;
  "trace_id"?: string | null;
  "ts_ms"?: number | null;
  "type"?: "anyagent.prompt.context";
};

export type AnyAgentPromptContextRenderedEvent = {
  "fragments"?: Array<RenderedPromptFragment>;
  "prompt_cache_key"?: string | null;
  "response_id": string;
  "seq"?: number | null;
  "total_chars"?: number;
  "trace_id"?: string | null;
  "ts_ms"?: number | null;
  "type"?: "anyagent.prompt.context.rendered";
};

export type AnyAgentScriptedReplyEvent = {
  "provider": string;
  "reason"?: string | null;
  "response_id": string;
  "seq"?: number | null;
  "text_chars"?: number;
  "trace_id"?: string | null;
  "ts_ms"?: number | null;
  "type"?: "anyagent.response.scripted";
  "variant_id"?: string | null;
};

export type AnyAgentSubAgentCompletedEvent = {
  "agent_id": string;
  "child_response_id": string;
  "duration_ms"?: number | null;
  "response_id": string;
  "seq"?: number | null;
  "status": string;
  "trace_id"?: string | null;
  "ts_ms"?: number | null;
  "type"?: "anyagent.subagent.completed";
};

export type AnyAgentSubAgentSpawnedEvent = {
  "agent_id": string;
  "child_response_id": string;
  "depth": number;
  "parent_response_id": string;
  "response_id": string;
  "seq"?: number | null;
  "task_description": StagePayloadSummary;
  "trace_id"?: string | null;
  "ts_ms"?: number | null;
  "type"?: "anyagent.subagent.spawned";
};

export type AnyAgentSubAgentTimeoutEvent = {
  "agent_id": string;
  "child_response_id": string;
  "response_id": string;
  "seq"?: number | null;
  "timeout_ms": number;
  "trace_id"?: string | null;
  "ts_ms"?: number | null;
  "type"?: "anyagent.subagent.timeout";
};

export type AnyAgentToolExecutionDetailEvent = {
  "arguments_json"?: string;
  "audit_ref"?: string | null;
  "duration_ms"?: number | null;
  "error"?: StageError | null;
  "output"?: string | null;
  "output_truncated"?: boolean | null;
  "response_id": string;
  "seq"?: number | null;
  "status": string;
  "tool_call_id": string;
  "tool_name": string;
  "tool_source"?: string | null;
  "trace_id"?: string | null;
  "ts_ms"?: number | null;
  "type"?: "anyagent.tool.execution.detail";
};

export type AnyAgentToolPlannedEvent = {
  "arguments": StagePayloadSummary;
  "response_id": string;
  "seq"?: number | null;
  "tool_call_id": string;
  "tool_name": string;
  "tool_source"?: string | null;
  "trace_id"?: string | null;
  "ts_ms"?: number | null;
  "type"?: "anyagent.tool.planned";
};

export type AnyAgentToolResultEvent = {
  "error"?: StageError | null;
  "meta"?: AnyAgentToolResultMeta;
  "output"?: StagePayloadSummary | null;
  "response_id": string;
  "seq"?: number | null;
  "status": string;
  "tool_call_id": string;
  "tool_name": string;
  "tool_source"?: string | null;
  "trace_id"?: string | null;
  "ts_ms"?: number | null;
  "type"?: "anyagent.tool.result";
};

export type AnyAgentToolResultMeta = {
  "audit_ref"?: string | null;
  "duration_ms"?: number | null;
  "output_truncated"?: boolean | null;
};

export type AnyAgentWorkspaceLifecycleEvent = {
  "audit_ref"?: string | null;
  "duration_ms"?: number | null;
  "failure_code"?: string | null;
  "failure_message"?: string | null;
  "generation"?: number | null;
  "response_id": string;
  "runtime_diagnostics"?: AdminSandboxRuntimeDiagnostics | null;
  "sandbox_id"?: string | null;
  "seq"?: number | null;
  "session_partition_key": string;
  "snapshot_bytes"?: number | null;
  "snapshot_uri"?: string | null;
  "trace_id"?: string | null;
  "ts_ms"?: number | null;
  "type": "anyagent.sandbox.workspace.restoring" | "anyagent.sandbox.workspace.restored" | "anyagent.sandbox.workspace.checkpointing" | "anyagent.sandbox.workspace.checkpointed" | "anyagent.sandbox.workspace.hibernated" | "anyagent.sandbox.workspace.restore_failed" | "anyagent.sandbox.workspace.checkpoint_failed";
  "workspace_id": string;
};

export type StageError = {
  "code"?: string | null;
  "message": string;
  "retryable"?: boolean | null;
  "type": string;
};

export type StageEventBase = {
  "response_id": string;
  "seq"?: number | null;
  "trace_id"?: string | null;
  "ts_ms"?: number | null;
  "type": string;
};

export type StagePayloadSummary = {
  "bytes": number;
  "preview"?: string | null;
  "preview_truncated"?: boolean;
  "sha256": string;
};

export type AuthRef = {
  "kind"?: string | null;
  "ref"?: string | null;
};

export type CancelRequest = {
  "agent_id"?: string | null;
  "response_id": string;
  "session_key"?: string | null;
  "tenant_id"?: string | null;
  "tool_call_id": string;
  "tool_name"?: string | null;
};

export type CancelResponse = {
  "ok": boolean;
};

export type ChannelContext = {
  "account_id"?: string | null;
  "chat_id"?: string | null;
  "ext"?: Record<string, unknown> | null;
  "message_id"?: string | null;
  "provider"?: string | null;
  "thread_id"?: string | null;
};

export type ExecuteMeta = {
  "audit_ref"?: string | null;
  "duration_ms"?: number;
  "output_truncated"?: boolean;
};

export type ExecuteRequest = {
  "agent_id": string;
  "arguments_json": unknown;
  "context"?: ToolContext;
  "deadline_ms"?: number | null;
  "response_id": string;
  "session_key": string;
  "tenant_id"?: string | null;
  "tool_call_id": string;
  "tool_name": string;
  "toolset_version"?: number | null;
};

export type ExecuteResponseCancelled = {
  "error": ToolError;
  "meta": ExecuteMeta;
  "status": "cancelled";
};

export type ExecuteResponseCompleted = {
  "meta": ExecuteMeta;
  "output": string;
  "status": "completed";
};

export type ExecuteResponseError = {
  "error": ToolError;
  "meta": ExecuteMeta;
  "status": "error";
};

export type ManifestDecision = {
  "decision": "allow" | "deny";
  "reason": string;
  "tool_name": string;
};

export type ManifestRequest = {
  "agent_id"?: string | null;
  "context"?: ToolContext;
  "enabled_skills"?: Array<string> | null;
  "requested_tool_names"?: Array<string> | null;
  "requested_tools"?: Array<Record<string, unknown>> | null;
  "session_key"?: string | null;
  "tenant_id"?: string | null;
};

export type ManifestResponse = {
  "decisions"?: Array<ManifestDecision> | null;
  "tools": Array<AnyAgentFunctionToolParam>;
  "toolset_version": number;
};

export type PolicyHint = {
  "allow_tools"?: Array<string> | null;
  "deny_tools"?: Array<string> | null;
};

export type RequesterContext = {
  "display_name"?: string | null;
  "id"?: string | null;
  "is_owner"?: boolean | null;
};

export type ToolContext = {
  "auth_ref"?: AuthRef | null;
  "channel"?: ChannelContext | null;
  "policy"?: PolicyHint | null;
  "requester"?: RequesterContext | null;
  "trace"?: TraceContext | null;
};

export type ToolError = {
  "code": string;
  "message": string;
  "retryable"?: boolean;
  "type": string;
};

export type TraceContext = {
  "span_id"?: string | null;
  "trace_id"?: string | null;
};

export type WorkspaceDoctorFinding = {
  "code": string;
  "level": "info" | "warning" | "error";
  "message": string;
};

export type WorkspaceDoctorReport = {
  "findings": Array<WorkspaceDoctorFinding>;
  "ok": boolean;
  "workspace": string;
};

export type WorkspaceInitResult = {
  "agent_id": string;
  "created": Array<string>;
  "next": string;
  "ok": boolean;
  "skipped": Array<string>;
  "workspace": string;
};

export type StageEvent = AnyAgentModelStreamEvent | AnyAgentToolPlannedEvent | AnyAgentToolResultEvent | AnyAgentToolExecutionDetailEvent | AnyAgentCommandPlannedEvent | AnyAgentCommandResultEvent | AnyAgentPromptContextEvent | AnyAgentPromptContextRenderedEvent | AnyAgentModelRequestEvent | AnyAgentScriptedReplyEvent | AnyAgentWorkspaceLifecycleEvent | AnyAgentMcpServerLifecycleEvent | AnyAgentSubAgentSpawnedEvent | AnyAgentSubAgentCompletedEvent | AnyAgentSubAgentTimeoutEvent | AnyAgentContextCompactedEvent | AnyAgentLoopWarningEvent | AnyAgentLoopTerminatedEvent | AnyAgentDoneEvent;

export type ExecuteResponse = ExecuteResponseCompleted | ExecuteResponseCancelled | ExecuteResponseError;
