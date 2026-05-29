import OpenAI from "openai";

export type StudioSettings = {
  baseUrl: string;
  apiKey: string;
  adminKey: string;
  model: string;
  agentId: string;
  sessionKey: string;
};

export type AgentSummary = {
  agent_id: string;
  exposed?: boolean;
  model_default?: string | null;
  model_provider?: string | null;
  model_base_url_env?: string | null;
  model_api_key_env?: string | null;
  sandbox_mode?: string | null;
  requested_tool_names?: string[];
  default_selected_skills?: string[];
};

export type AgentDetail = AgentSummary & {
  agents_md?: {
    path?: string;
    sha256?: string;
    preview?: string;
  };
  mcp_servers?: string[];
  tools?: {
    requested_tool_names?: string[];
    allow_tools?: string[];
    deny_tools?: string[];
  };
  model?: {
    default?: string | null;
    provider?: string | null;
    base_url_env?: string | null;
    api_key_env?: string | null;
  };
  sandbox?: {
    mode?: string;
    [key: string]: unknown;
  };
  multiagent?: {
    spawn_allow_agent_ids?: string[];
  };
  skills?: {
    default_selected?: string[];
    disabled_paths?: string[];
  };
};

export type SkillSummary = {
  name?: unknown;
  stable_id?: string;
  path?: unknown;
  source_hash?: string;
  interface?: unknown;
  enabled?: boolean;
  selected?: boolean;
};

export type ToolCatalogItem = {
  name: string;
  description?: string;
  kind?: string;
  parameters?: Record<string, unknown>;
  decision?: string;
  reason?: string;
};

export type ToolCatalog = {
  agent_id: string;
  session_key: string;
  requested_tool_names?: string[];
  toolset_version: number;
  tools: ToolCatalogItem[];
};

export type CredentialRef = {
  credential_id: string;
  kind: string;
  scope: {
    level: "global" | "agent";
    agent_id?: string | null;
  };
  metadata?: Record<string, unknown>;
};

export type CredentialList = {
  credentials: CredentialRef[];
};

export type HealthStatus = {
  status?: string;
  [key: string]: unknown;
};

export type AdminStatus = {
  status?: string;
  [key: string]: unknown;
};

export type SkillChannel = "skills.sh" | "registry" | "github" | "local_upload";

export type McpServerDraft = {
  name: string;
  enabled: boolean;
  transport: "streamable_http" | "stdio" | "sse";
  url: string;
  command: string;
  credentialId: string;
};

export type StudioDebugEvent = {
  type?: string;
  seq?: number;
  tool_name?: string;
  tool_call_id?: string;
  status?: string;
  payload?: unknown;
  [key: string]: unknown;
};

export type ToolCallKind = "mcp" | "command" | "core";

export type ToolCallItem = {
  id: string;
  toolName: string;
  kind: ToolCallKind;
  status: "running" | "success" | "failed";
  arguments?: string;
  output?: string;
  error?: string;
  durationMs?: number;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  thinking?: string;
  toolCalls?: ToolCallItem[];
};

export type ChatRunResult = {
  responseId: string | null;
  assistantText: string;
  streamEvents: StudioDebugEvent[];
};

export type ObservabilitySummary = {
  response_id: string;
  agent_id?: string | null;
  session_key?: string | null;
  event_count?: number;
  typed_event_count?: number;
  tool_call_count?: number;
  mcp_call_count?: number;
  skill_view_count?: number;
  turn_count?: number;
  input_chars?: number;
  output_chars?: number;
  input_tokens?: number;
  output_tokens?: number;
  cached_input_tokens?: number;
  turns?: Array<{
    index: number;
    input_chars?: number;
    output_chars?: number;
  }>;
  first_token_latency_ms?: number | null;
  total_response_latency_ms?: number | null;
  run_status?: string | null;
  effective_run_status?: string | null;
};

export type ObservabilityRunItem = {
  response_id: string;
  agent_id: string;
  session_key: string;
  stream: boolean;
  status: string;
  effective_status: string;
  created_at_ms: number;
  updated_at_ms: number;
  ended_at_ms?: number | null;
};

export type ObservabilityRuns = {
  agent_id?: string | null;
  session_key?: string | null;
  response_id?: string | null;
  runs: ObservabilityRunItem[];
};

export type ObservabilityFilters = {
  agentId?: string;
  sessionKey?: string;
  responseId?: string;
  traceId?: string;
  createdAfterMs?: number;
  createdBeforeMs?: number;
  limit?: number;
};

export type ObservabilitySource = "run" | "event" | "stage" | "observability" | "workspace" | "audit";

export type ObservabilityTimelineEvent = {
  source: ObservabilitySource;
  type: string;
  ts_ms?: number | null;
  response_id?: string | null;
  agent_id?: string | null;
  session_key?: string | null;
  trace_id?: string | null;
  seq?: number | null;
  level?: "debug" | "info" | "warning" | "error" | null;
  category?: string | null;
  status?: string | null;
  tool_name?: string | null;
  tool_call_id?: string | null;
  duration_ms?: number | null;
  audit_ref?: string | null;
  message?: string | null;
  payload?: Record<string, unknown>;
};

export type ObservabilityTimeline = {
  agent_id?: string | null;
  session_key?: string | null;
  response_id?: string | null;
  trace_id?: string | null;
  events: ObservabilityTimelineEvent[];
};

export type ObservabilityMetrics = {
  agent_id?: string | null;
  session_key?: string | null;
  response_id?: string | null;
  run_count: number;
  event_count: number;
  tool_call_count: number;
  mcp_call_count: number;
  error_count: number;
  input_tokens: number;
  output_tokens: number;
  cached_input_tokens: number;
  avg_response_latency_ms?: number | null;
  max_response_latency_ms?: number | null;
  first_token_latency_ms?: number | null;
};

export type ObservabilityToolStats = {
  tool_name: string;
  planned_count: number;
  result_count: number;
  error_count: number;
  avg_duration_ms?: number | null;
  max_duration_ms?: number | null;
  last_status?: string | null;
  audit_refs?: string[];
};

export type ObservabilityTools = {
  agent_id?: string | null;
  session_key?: string | null;
  response_id?: string | null;
  tools: ObservabilityToolStats[];
};

export type ObservabilityErrorItem = {
  source: ObservabilitySource;
  type: string;
  message?: string | null;
  status?: string | null;
  ts_ms?: number | null;
  response_id?: string | null;
  agent_id?: string | null;
  session_key?: string | null;
  trace_id?: string | null;
  tool_name?: string | null;
  tool_call_id?: string | null;
  audit_ref?: string | null;
  retryable?: boolean | null;
  payload?: Record<string, unknown>;
};

export type ObservabilityErrors = {
  agent_id?: string | null;
  session_key?: string | null;
  response_id?: string | null;
  errors: ObservabilityErrorItem[];
};

export type ObservabilityTrace = {
  trace_id: string;
  response_ids: string[];
  audit_refs: string[];
  events: ObservabilityTimelineEvent[];
};

export type ToolExecutionDetail = {
  response_id?: string;
  type?: string;
  tool_call_id: string;
  tool_name: string;
  arguments_json: string;
  output?: string | null;
  error?: {
    type?: string;
    code?: string | null;
    message?: string;
    retryable?: boolean | null;
  } | null;
  status: string;
  duration_ms?: number | null;
  output_truncated?: boolean | null;
  audit_ref?: string | null;
  trace_id?: string | null;
  ts_ms?: number | null;
};

export type ToolExecutionsResponse = {
  response_id: string;
  tool_executions: ToolExecutionDetail[];
};

export type ModelRequestResponse = {
  response_id: string;
  applied_body?: Record<string, unknown> | null;
  prompt_cache_key?: string | null;
};

export type PromptContextFragment = {
  kind: string;
  role: string;
  cache_class: string;
  label?: string | null;
  stable_id?: string | null;
  source_path?: string | null;
  source_hash?: string | null;
  scope?: string | null;
  metadata?: Record<string, string>;
  rendered_text: string;
};

export type PromptContextResponse = {
  response_id: string;
  prompt_cache_key?: string | null;
  total_chars?: number;
  fragments?: PromptContextFragment[];
  fallback?: "rendered" | "audit" | "missing";
};

export type AgentFileKind = "agents_md" | "agent_yaml" | "mcp_json";

export type AgentWorkspaceFile = {
  kind: AgentFileKind;
  path: string;
  exists: boolean;
  sha256?: string;
  text?: string;
};

export type ImportedSkill = {
  agent_id: string;
  stable_id: string;
  name: string;
  path: string;
  sha256: string;
  reloaded_agent_ids?: string[];
};

export type SkillUpdateCheck = {
  agent_id: string;
  directory_name: string;
  channel?: string | null;
  source_ref?: string | null;
  current_hash?: string | null;
  latest_hash?: string | null;
  update_available: boolean;
  updatable: boolean;
  reason?: string | null;
};

export type CreatedAgent = {
  agent: AgentDetail;
  reloaded_agent_ids?: string[];
};

const trimTrailingSlash = (value: string) => value.replace(/\/+$/, "");

const internalBaseUrl = (baseUrl: string) => {
  const trimmed = trimTrailingSlash(baseUrl);
  return trimmed.endsWith("/v1") ? trimmed.slice(0, -3) : trimmed;
};

const openAiBaseUrl = (baseUrl: string) => {
  const trimmed = trimTrailingSlash(baseUrl);
  return trimmed.endsWith("/v1") ? trimmed : `${trimmed}/v1`;
};

const authHeaders = (apiKey: string) => ({
  Authorization: `Bearer ${apiKey || "anyagent-studio"}`,
});

async function fetchJson<T>(settings: StudioSettings, path: string): Promise<T> {
  const response = await fetch(`${internalBaseUrl(settings.baseUrl)}${path}`, {
    headers: authHeaders(settings.apiKey),
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

export async function listAgents(settings: StudioSettings, includeUnexposed = false): Promise<AgentSummary[]> {
  const suffix = includeUnexposed ? "?include_unexposed=true" : "";
  const payload = await fetchJson<{ agents?: AgentSummary[] }>(settings, `/internal/agents${suffix}`);
  return payload.agents ?? [];
}

export async function getHealth(settings: StudioSettings): Promise<HealthStatus> {
  return fetchJson<HealthStatus>(settings, "/healthz");
}

export async function getStorageHealth(settings: StudioSettings): Promise<AdminStatus> {
  return fetchJson<AdminStatus>({ ...settings, apiKey: settings.adminKey || settings.apiKey }, "/admin/storage/health");
}

export async function getCredentialCapabilities(settings: StudioSettings): Promise<AdminStatus> {
  return fetchJson<AdminStatus>({ ...settings, apiKey: settings.adminKey || settings.apiKey }, "/admin/credentials/capabilities");
}

export async function createAgent(
  settings: StudioSettings,
  agentId: string,
  instructions: string,
  requestedToolNames: string[],
): Promise<CreatedAgent> {
  const response = await fetch(`${internalBaseUrl(settings.baseUrl)}/admin/workspace/agents`, {
    method: "POST",
    headers: {
      ...authHeaders(settings.adminKey || settings.apiKey),
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      agent_id: agentId,
      instructions,
      requested_tool_names: requestedToolNames,
      exposed: true,
      sandbox_mode: "disabled",
    }),
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}: ${await response.text()}`);
  }
  return (await response.json()) as CreatedAgent;
}

export async function getAgent(settings: StudioSettings, agentId: string): Promise<AgentDetail | null> {
  if (!agentId) {
    return null;
  }
  return fetchJson<AgentDetail>(settings, `/internal/agents/${encodeURIComponent(agentId)}`);
}

export async function getAdminAgent(settings: StudioSettings, agentId: string): Promise<AgentDetail | null> {
  if (!agentId) {
    return null;
  }
  return fetchJson<AgentDetail>(
    { ...settings, apiKey: settings.adminKey || settings.apiKey },
    `/admin/workspace/agents/${encodeURIComponent(agentId)}`,
  );
}

export async function listSkills(settings: StudioSettings, agentId: string): Promise<SkillSummary[]> {
  if (!agentId) {
    return [];
  }
  const payload = await fetchJson<{ skills?: SkillSummary[] }>(
    settings,
    `/internal/skills/list?agent_id=${encodeURIComponent(agentId)}`,
  );
  return payload.skills ?? [];
}

export async function listTools(settings: StudioSettings, agentId: string, requestedToolNames: string[] = []): Promise<ToolCatalog> {
  const params = new URLSearchParams({
    agent_id: agentId,
    session_key: settings.sessionKey || "studio-catalog",
  });
  if (requestedToolNames.length > 0) {
    params.set("requested_tool_names", requestedToolNames.join(","));
  }
  return fetchJson<ToolCatalog>(settings, `/internal/tools/catalog?${params.toString()}`);
}

export async function listAvailableTools(settings: StudioSettings): Promise<ToolCatalog> {
  return fetchJson<ToolCatalog>({ ...settings, apiKey: settings.adminKey || settings.apiKey }, "/admin/tools/catalog");
}

export async function updateAgentSkills(
  settings: StudioSettings,
  agentId: string,
  defaultSelected: string[],
): Promise<CreatedAgent> {
  const response = await fetch(`${internalBaseUrl(settings.baseUrl)}/admin/workspace/agents/${encodeURIComponent(agentId)}/skills`, {
    method: "PUT",
    headers: {
      ...authHeaders(settings.adminKey || settings.apiKey),
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ default_selected: defaultSelected }),
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}: ${await response.text()}`);
  }
  return (await response.json()) as CreatedAgent;
}

export type AgentConfigUpdate = {
  exposed?: boolean;
  model_default?: string | null;
  model_provider?: string | null;
  model_base_url_env?: string | null;
  model_api_key_env?: string | null;
  requested_tool_names?: string[];
  sandbox_mode?: string;
  spawn_allow_agent_ids?: string[];
  disabled_skill_paths?: string[];
};

export async function updateAgentConfig(
  settings: StudioSettings,
  agentId: string,
  config: AgentConfigUpdate,
): Promise<CreatedAgent> {
  const response = await fetch(`${internalBaseUrl(settings.baseUrl)}/admin/workspace/agents/${encodeURIComponent(agentId)}/config`, {
    method: "PUT",
    headers: {
      ...authHeaders(settings.adminKey || settings.apiKey),
      "Content-Type": "application/json",
    },
    body: JSON.stringify(config),
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}: ${await response.text()}`);
  }
  return (await response.json()) as CreatedAgent;
}

export async function listCredentials(settings: StudioSettings): Promise<CredentialList> {
  return fetchJson<CredentialList>({ ...settings, apiKey: settings.adminKey || settings.apiKey }, "/admin/credentials");
}

export async function setCredential(
  settings: StudioSettings,
  credentialId: string,
  kind: string,
  value: string,
  scopeLevel: "global" | "agent",
  agentId?: string,
): Promise<CredentialRef> {
  const response = await fetch(`${internalBaseUrl(settings.baseUrl)}/admin/credentials`, {
    method: "POST",
    headers: {
      ...authHeaders(settings.adminKey || settings.apiKey),
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      credential_id: credentialId,
      kind,
      value,
      scope: {
        level: scopeLevel,
        agent_id: scopeLevel === "agent" ? agentId || settings.agentId : undefined,
      },
      metadata: {},
    }),
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}: ${await response.text()}`);
  }
  return (await response.json()) as CredentialRef;
}

export async function deleteCredential(settings: StudioSettings, credentialId: string): Promise<void> {
  const response = await fetch(`${internalBaseUrl(settings.baseUrl)}/admin/credentials/${encodeURIComponent(credentialId)}`, {
    method: "DELETE",
    headers: authHeaders(settings.adminKey || settings.apiKey),
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}: ${await response.text()}`);
  }
}

export async function listEvents(settings: StudioSettings, responseId: string): Promise<StudioDebugEvent[]> {
  if (!responseId) {
    return [];
  }
  const payload = await fetchJson<{ events?: StudioDebugEvent[] }>(
    settings,
    `/internal/events/list?response_id=${encodeURIComponent(responseId)}&include_model_events=false`,
  );
  return payload.events ?? [];
}

export type ResponseStatus = {
  id?: string;
  status?: string;
  [key: string]: unknown;
};

export async function retrieveResponse(settings: StudioSettings, responseId: string): Promise<ResponseStatus | null> {
  if (!responseId) {
    return null;
  }
  const response = await fetch(`${openAiBaseUrl(settings.baseUrl)}/responses/${encodeURIComponent(responseId)}`, {
    headers: authHeaders(settings.apiKey),
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return (await response.json()) as ResponseStatus;
}

export async function cancelResponse(settings: StudioSettings, responseId: string): Promise<ResponseStatus | null> {
  if (!responseId) {
    return null;
  }
  const response = await fetch(`${openAiBaseUrl(settings.baseUrl)}/responses/${encodeURIComponent(responseId)}/cancel`, {
    method: "POST",
    headers: authHeaders(settings.apiKey),
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return (await response.json()) as ResponseStatus;
}

export function streamPersistedEvents(
  settings: StudioSettings,
  responseId: string,
  options: { lastSeq?: number; onEvent: (event: StudioDebugEvent) => void; onError?: (error: unknown) => void } = { onEvent: () => {} },
): () => void {
  if (!responseId) {
    return () => {};
  }
  const params = new URLSearchParams({ response_id: responseId });
  if (typeof options.lastSeq === "number") {
    params.set("last_seq", String(options.lastSeq));
  }
  const controller = new AbortController();
  let stopped = false;
  let attempt = 0;

  async function connect() {
    try {
      const response = await fetch(`${internalBaseUrl(settings.baseUrl)}/internal/events/stream?${params.toString()}`, {
        headers: { ...authHeaders(settings.apiKey), Accept: "text/event-stream" },
        signal: controller.signal,
      });
      if (!response.ok || !response.body) {
        throw new Error(`${response.status} ${response.statusText}`);
      }
      attempt = 0;
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (!stopped) {
        const { done, value } = await reader.read();
        if (done) {
          break;
        }
        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split("\n\n");
        buffer = frames.pop() ?? "";
        for (const frame of frames) {
          const lines = frame.split("\n");
          const idLine = lines.find((line) => line.startsWith("id:"));
          const dataLines = lines.filter((line) => line.startsWith("data:")).map((line) => line.slice(5).replace(/^ /, ""));
          if (idLine) {
            params.set("last_seq", idLine.slice(3).trim());
          }
          const raw = dataLines.join("\n").trim();
          if (!raw || raw === "[DONE]") {
            continue;
          }
          try {
            const event = JSON.parse(raw) as StudioDebugEvent;
            if (typeof event.seq === "number") {
              params.set("last_seq", String(event.seq));
            }
            options.onEvent(event);
          } catch {
            // skip malformed frame
          }
        }
      }
    } catch (error) {
      if (stopped || controller.signal.aborted) {
        return;
      }
      options.onError?.(error);
      attempt += 1;
      if (attempt <= 4) {
        const delay = Math.min(8000, 1000 * 2 ** (attempt - 1));
        setTimeout(() => {
          if (!stopped) {
            void connect();
          }
        }, delay);
      }
    }
  }

  void connect();
  return () => {
    stopped = true;
    controller.abort();
  };
}

export async function loadObservabilitySummary(
  settings: StudioSettings,
  responseId: string,
): Promise<ObservabilitySummary | null> {
  if (!responseId) {
    return null;
  }
  return fetchJson<ObservabilitySummary>(
    settings,
    `/internal/observability/summary?response_id=${encodeURIComponent(responseId)}`,
  );
}

export async function loadObservabilityRuns(
  settings: StudioSettings,
  filters: ObservabilityFilters = {},
): Promise<ObservabilityRuns> {
  return fetchJson<ObservabilityRuns>(settings, `/internal/observability/runs${observabilityQuery(filters)}`);
}

export async function loadObservabilityTimeline(
  settings: StudioSettings,
  filters: ObservabilityFilters = {},
): Promise<ObservabilityTimeline> {
  return fetchJson<ObservabilityTimeline>(settings, `/internal/observability/timeline${observabilityQuery(filters)}`);
}

export async function loadObservabilityMetrics(
  settings: StudioSettings,
  filters: ObservabilityFilters = {},
): Promise<ObservabilityMetrics> {
  return fetchJson<ObservabilityMetrics>(settings, `/internal/observability/metrics${observabilityQuery(filters)}`);
}

export async function loadObservabilityTools(
  settings: StudioSettings,
  filters: ObservabilityFilters = {},
): Promise<ObservabilityTools> {
  return fetchJson<ObservabilityTools>(settings, `/internal/observability/tools${observabilityQuery(filters)}`);
}

export async function loadObservabilityErrors(
  settings: StudioSettings,
  filters: ObservabilityFilters = {},
): Promise<ObservabilityErrors> {
  return fetchJson<ObservabilityErrors>(settings, `/internal/observability/errors${observabilityQuery(filters)}`);
}

export async function loadObservabilityTrace(
  settings: StudioSettings,
  traceId: string,
  limit = 500,
): Promise<ObservabilityTrace | null> {
  if (!traceId.trim()) {
    return null;
  }
  const params = new URLSearchParams({ limit: String(limit) });
  return fetchJson<ObservabilityTrace>(
    settings,
    `/internal/observability/traces/${encodeURIComponent(traceId.trim())}?${params.toString()}`,
  );
}

export async function loadToolExecutions(
  settings: StudioSettings,
  responseId: string,
): Promise<ToolExecutionsResponse> {
  return fetchJson<ToolExecutionsResponse>(
    settings,
    `/internal/responses/${encodeURIComponent(responseId)}/tool-executions`,
  );
}

export async function loadModelRequest(
  settings: StudioSettings,
  responseId: string,
): Promise<ModelRequestResponse> {
  return fetchJson<ModelRequestResponse>(
    settings,
    `/internal/responses/${encodeURIComponent(responseId)}/model-request`,
  );
}

export async function loadPromptContext(
  settings: StudioSettings,
  responseId: string,
): Promise<PromptContextResponse> {
  return fetchJson<PromptContextResponse>(
    settings,
    `/internal/responses/${encodeURIComponent(responseId)}/prompt-context`,
  );
}

function observabilityQuery(filters: ObservabilityFilters): string {
  const params = new URLSearchParams();
  if (filters.agentId) params.set("agent_id", filters.agentId);
  if (filters.sessionKey) params.set("session_key", filters.sessionKey);
  if (filters.responseId) params.set("response_id", filters.responseId);
  if (filters.traceId) params.set("trace_id", filters.traceId);
  if (typeof filters.createdAfterMs === "number") params.set("created_after_ms", String(filters.createdAfterMs));
  if (typeof filters.createdBeforeMs === "number") params.set("created_before_ms", String(filters.createdBeforeMs));
  if (typeof filters.limit === "number") params.set("limit", String(filters.limit));
  return params.toString() ? `?${params.toString()}` : "";
}

export async function previewPromptBundle(
  settings: StudioSettings,
  input: string,
): Promise<Record<string, unknown>> {
  const model = settings.model.trim();
  const response = await fetch(`${internalBaseUrl(settings.baseUrl)}/internal/prompt/bundle`, {
    method: "POST",
    headers: {
      ...authHeaders(settings.apiKey),
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      ...(model ? { model } : {}),
      input,
      metadata: {
        agent_id: settings.agentId,
        session_key: settings.sessionKey,
      },
    }),
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return (await response.json()) as Record<string, unknown>;
}

export async function listAgentFiles(settings: StudioSettings, agentId: string): Promise<AgentWorkspaceFile[]> {
  if (!agentId) {
    return [];
  }
  const payload = await fetchJson<{ files?: AgentWorkspaceFile[] }>(
    { ...settings, apiKey: settings.adminKey || settings.apiKey },
    `/admin/workspace/agents/${encodeURIComponent(agentId)}/files`,
  );
  return payload.files ?? [];
}

export async function updateAgentFile(
  settings: StudioSettings,
  agentId: string,
  kind: AgentFileKind,
  text: string,
  expectedSha256?: string,
): Promise<AgentWorkspaceFile> {
  const response = await fetch(
    `${internalBaseUrl(settings.baseUrl)}/admin/workspace/agents/${encodeURIComponent(agentId)}/files/${kind}`,
    {
      method: "PUT",
      headers: {
        ...authHeaders(settings.adminKey || settings.apiKey),
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        text,
        expected_sha256: expectedSha256,
      }),
    },
  );
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}: ${await response.text()}`);
  }
  const payload = (await response.json()) as { file?: AgentWorkspaceFile };
  if (!payload.file) {
    throw new Error("missing updated file payload");
  }
  return payload.file;
}

export async function importAgentSkill(
  settings: StudioSettings,
  agentId: string,
  directoryName: string,
  skillMd: string,
  overwrite = false,
): Promise<ImportedSkill> {
  const response = await fetch(
    `${internalBaseUrl(settings.baseUrl)}/admin/workspace/agents/${encodeURIComponent(agentId)}/skills/import`,
    {
      method: "POST",
      headers: {
        ...authHeaders(settings.adminKey || settings.apiKey),
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        directory_name: directoryName,
        skill_md: skillMd,
        overwrite,
      }),
    },
  );
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}: ${await response.text()}`);
  }
  return (await response.json()) as ImportedSkill;
}

export async function installAgentSkill(
  settings: StudioSettings,
  agentId: string,
  channel: Exclude<SkillChannel, "local_upload">,
  packageName: string,
  skillName: string,
  directoryName?: string,
  overwrite = false,
  github?: { repo?: string; ref?: string; path?: string },
): Promise<ImportedSkill> {
  const response = await fetch(
    `${internalBaseUrl(settings.baseUrl)}/admin/workspace/agents/${encodeURIComponent(agentId)}/skills/install`,
    {
      method: "POST",
      headers: {
        ...authHeaders(settings.adminKey || settings.apiKey),
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        channel,
        package: packageName,
        skill: skillName,
        directory_name: directoryName || undefined,
        github_repo: github?.repo || undefined,
        github_ref: github?.ref || undefined,
        github_path: github?.path || undefined,
        overwrite,
      }),
    },
  );
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}: ${await response.text()}`);
  }
  return (await response.json()) as ImportedSkill;
}

export async function checkAgentSkillUpdate(
  settings: StudioSettings,
  agentId: string,
  directoryName: string,
): Promise<SkillUpdateCheck> {
  return fetchJson<SkillUpdateCheck>(
    { ...settings, apiKey: settings.adminKey || settings.apiKey },
    `/admin/workspace/agents/${encodeURIComponent(agentId)}/skills/${encodeURIComponent(directoryName)}/update/check`,
  );
}

export async function applyAgentSkillUpdate(
  settings: StudioSettings,
  agentId: string,
  directoryName: string,
): Promise<ImportedSkill> {
  const response = await fetch(
    `${internalBaseUrl(settings.baseUrl)}/admin/workspace/agents/${encodeURIComponent(agentId)}/skills/${encodeURIComponent(directoryName)}/update/apply`,
    {
      method: "POST",
      headers: authHeaders(settings.adminKey || settings.apiKey),
    },
  );
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}: ${await response.text()}`);
  }
  return (await response.json()) as ImportedSkill;
}

function readEventResponseId(event: unknown): string | null {
  if (!event || typeof event !== "object") {
    return null;
  }
  const candidate = event as { response?: { id?: unknown }; data?: { id?: unknown }; id?: unknown };
  const value = candidate.response?.id ?? candidate.data?.id ?? candidate.id;
  return typeof value === "string" && value.startsWith("resp_") ? value : null;
}

function readEventTextDelta(event: unknown): string {
  if (!event || typeof event !== "object") {
    return "";
  }
  const candidate = event as { type?: unknown; delta?: unknown };
  // Only accept the assistant's visible output-text increments.
  // Other ".delta" events (reasoning summaries, refusals, function-call
  // arguments) and full-text events (".done"/".completed") must be ignored,
  // otherwise the message gets duplicated or polluted with chain-of-thought.
  if (candidate.type !== "response.output_text.delta") {
    return "";
  }
  return typeof candidate.delta === "string" ? candidate.delta : "";
}

function readEventThinkingDelta(event: unknown): string {
  if (!event || typeof event !== "object") {
    return "";
  }
  const candidate = event as { type?: unknown; delta?: unknown; summary_text?: unknown };
  if (candidate.type === "response.reasoning_summary_text.delta") {
    return typeof candidate.delta === "string" ? candidate.delta : "";
  }
  if (candidate.type === "response.reasoning_summary_part.delta") {
    return typeof candidate.delta === "string" ? candidate.delta : "";
  }
  return "";
}

function readFinalResponseText(response: unknown): string {
  if (!response || typeof response !== "object") {
    return "";
  }
  const candidate = response as {
    output_text?: unknown;
    output?: Array<{ content?: Array<{ text?: unknown; type?: string }> }>;
  };
  if (typeof candidate.output_text === "string") {
    return candidate.output_text;
  }
  const chunks: string[] = [];
  for (const item of candidate.output ?? []) {
    for (const content of item.content ?? []) {
      if (typeof content.text === "string") {
        chunks.push(content.text);
      }
    }
  }
  return chunks.join("\n").trim();
}

export async function runChat(
  settings: StudioSettings,
  messages: ChatMessage[],
  onDelta: (delta: string) => void,
  onEvent: (event: StudioDebugEvent) => void,
  signal?: AbortSignal,
  onThinkingDelta?: (delta: string) => void,
): Promise<ChatRunResult> {
  const client = new OpenAI({
    apiKey: settings.apiKey || "anyagent-studio",
    baseURL: openAiBaseUrl(settings.baseUrl),
    dangerouslyAllowBrowser: true,
  });
  const input = messages.map((message) => ({
    role: message.role,
    content: message.content,
  }));
  const model = settings.model.trim();
  const stream = await client.responses.create(
    {
      ...(model ? { model } : {}),
      input,
      stream: true,
      metadata: {
        agent_id: settings.agentId,
        session_key: settings.sessionKey,
      },
    },
    signal ? { signal } : undefined,
  );

  let assistantText = "";
  let responseId: string | null = null;
  let finalResponse: unknown = null;
  const streamEvents: StudioDebugEvent[] = [];

  for await (const event of stream) {
    const debugEvent = event as unknown as StudioDebugEvent;
    streamEvents.push(debugEvent);
    onEvent(debugEvent);
    responseId = responseId ?? readEventResponseId(event);
    const delta = readEventTextDelta(event);
    if (delta) {
      assistantText += delta;
      onDelta(delta);
    }
    if (onThinkingDelta) {
      const thinkingDelta = readEventThinkingDelta(event);
      if (thinkingDelta) {
        onThinkingDelta(thinkingDelta);
      }
    }
    if ("response" in debugEvent && debugEvent.response) {
      finalResponse = debugEvent.response;
    }
  }

  // Fallback only when no incremental text was streamed (e.g. the transport
  // delivered a single non-streaming response). Never combine with deltas.
  if (!assistantText && finalResponse) {
    const finalText = readFinalResponseText(finalResponse);
    if (finalText) {
      assistantText = finalText;
      onDelta(finalText);
    }
  }

  return {
    responseId,
    assistantText,
    streamEvents,
  };
}

export function buildMcpJson(drafts: McpServerDraft[]): string {
  const mcpServers = Object.fromEntries(
    drafts
      .filter((draft) => draft.name.trim())
      .map((draft) => {
        if (draft.transport === "stdio") {
          return [
            draft.name.trim(),
            {
              command: draft.command.trim(),
              transport: draft.transport,
              enabled: draft.enabled,
            },
          ];
        }
        return [
          draft.name.trim(),
          {
            url: draft.url.trim(),
            transport: draft.transport,
            enabled: draft.enabled,
            auth: draft.credentialId.trim()
              ? {
                  credential_id: draft.credentialId.trim(),
                  ref_kind: "bearer_token",
                  injection: "header:Authorization",
                  format: "Bearer {value}",
                }
              : undefined,
          },
        ];
      }),
  );
  return JSON.stringify({ mcpServers }, null, 2);
}

export function parseMcpDrafts(text: string): McpServerDraft[] {
  if (!text.trim()) {
    return [];
  }
  const payload = JSON.parse(text) as { mcpServers?: unknown };
  if (!payload || typeof payload !== "object" || !payload.mcpServers || typeof payload.mcpServers !== "object") {
    return [];
  }
  return Object.entries(payload.mcpServers as Record<string, unknown>).map(([name, raw]) => {
    const server = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
    const transport = server.transport === "stdio" || server.transport === "sse" ? server.transport : "streamable_http";
    const auth = server.auth && typeof server.auth === "object" ? (server.auth as Record<string, unknown>) : {};
    return {
      name,
      enabled: server.enabled !== false,
      transport,
      url: typeof server.url === "string" ? server.url : "",
      command: typeof server.command === "string" ? server.command : "",
      credentialId: typeof auth.credential_id === "string" ? auth.credential_id : "",
    };
  });
}
