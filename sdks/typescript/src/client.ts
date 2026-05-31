import type {
  AdminAgentConfigUpdateRequest,
  AdminAgentCreateRequest,
  AdminAgentCreateResponse,
  AdminAgentSkillsUpdateRequest,
  AdminCredentialDeleteResponse,
  AdminCredentialListResponse,
  AdminCredentialRef,
  AdminCredentialSetRequest,
  AdminMcpServerEnableRequest,
  AdminMcpServerEnableResponse,
  AdminMcpServersResponse,
  AdminMcpServerTestResponse,
  AdminSandboxWorkspaceListResponse,
  AdminSandboxWorkspaceReclaimResponse,
  AdminSandboxWorkspaceSnapshotsResponse,
  AdminSkillImportRequest,
  AdminSkillImportResponse,
  AdminSkillRegistryInstallRequest,
  AdminSkillUpdateCheckResponse,
  AdminToolCatalogResponse,
  AdminWorkspaceAgentFileUpdateRequest,
  AdminWorkspaceAgentFileUpdateResponse,
  AdminWorkspaceAgentFilesResponse,
  AlertEventsResponse,
  AnyAgentResponseStatusPayload,
  EvalDatasetResponse,
  EvalDatasetsResponse,
  EvalDatasetUpsertRequest,
  EvalRunRequest,
  EvalRunResponse,
  EvalRunsResponse,
  HealthResponse,
  InternalAgentDetailResponse,
  InternalAgentsListResponse,
  InternalAuditEventsResponse,
  InternalEventsListResponse,
  InternalEventsReplaySummary,
  InternalObservabilityErrorsResponse,
  InternalObservabilityMetricsResponse,
  InternalObservabilityRunsResponse,
  InternalObservabilitySummaryResponse,
  InternalObservabilityTimelineResponse,
  InternalObservabilityToolsResponse,
  InternalObservabilityTraceResponse,
  InternalPromptBundlePreviewResponse,
  InternalResponseModelRequestResponse,
  InternalResponsePromptContextResponse,
  InternalResponseToolExecutionsResponse,
  InternalSessionDetailResponse,
  InternalSessionsListResponse,
  InternalSkillsListResponse,
  InternalToolCatalogResponse,
  PluginCatalogResponse,
  PromptVersionCreateRequest,
  PromptVersionDiffResponse,
  PromptVersionResponse,
  PromptVersionRestoreResponse,
  PromptVersionsResponse,
  StorageHealthResponse,
  ToolVisibilityExplanation,
} from "../generated/protocol-types.js";
import { getProtocolEndpoint, type ProtocolEndpoint } from "./schemaBundle.js";
import { validateProtocolModel, validateProtocolRequest } from "./validate.js";

export type AnyAgentFetch = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;

export interface AnyAgentClientOptions {
  apiKey: string;
  baseUrl?: string;
  fetch?: AnyAgentFetch;
}

export type OpenAIResponsesCreateRequest = Record<string, unknown>;
export type OpenAIResponseJson = Record<string, unknown> & { id: string; object?: string; status?: string };

export interface ResponsesRequestOptions {
  agentId?: string;
  idempotencyKey?: string;
  skills?: string[];
  signal?: AbortSignal;
}

export interface AnyAgentSseEvent {
  id: string | null;
  event: string | null;
  data: string;
  json: unknown | null;
}

export interface ObservabilityQueryOptions {
  agentId?: string;
  sessionKey?: string;
  responseId?: string;
  traceId?: string;
  createdAfterMs?: number;
  createdBeforeMs?: number;
  limit?: number;
}

interface RequestOptions {
  path: string;
  params?: Record<string, string | number | boolean | undefined>;
  schemaName: string;
}

interface JsonRequestOptions {
  path: string;
  schemaName: string;
  body?: unknown;
  requestSchemaName?: string;
  headers?: Record<string, string | undefined>;
}

interface DeleteRequestOptions {
  path: string;
  schemaName?: string;
}

type EndpointPathParams = Record<string, string | number>;

interface EndpointRequestOptions {
  operation: string;
  pathParams?: EndpointPathParams;
  params?: RequestOptions["params"];
}

interface EndpointJsonRequestOptions {
  operation: string;
  pathParams?: EndpointPathParams;
  params?: RequestOptions["params"];
  body?: unknown;
  headers?: Record<string, string | undefined>;
}

interface EndpointDeleteRequestOptions {
  operation: string;
  pathParams?: EndpointPathParams;
}

function normalizeBaseUrl(baseUrl: string): string {
  return baseUrl.replace(/\/+$/, "");
}

function appendParams(url: URL, params: RequestOptions["params"]): void {
  if (!params) {
    return;
  }
  for (const [key, value] of Object.entries(params)) {
    if (typeof value === "undefined") {
      continue;
    }
    url.searchParams.set(key, String(value));
  }
}

function applyPathParams(path: string, pathParams: EndpointPathParams = {}): string {
  return path.replace(/\{([^}]+)\}/g, (_match, rawName: string) => {
    const value = pathParams[rawName];
    if (typeof value === "undefined") {
      throw new Error(`Missing path param for protocol endpoint: ${rawName}`);
    }
    return encodeURIComponent(String(value));
  });
}

function observabilityParams(options: ObservabilityQueryOptions = {}): RequestOptions["params"] {
  return {
    agent_id: options.agentId,
    session_key: options.sessionKey,
    response_id: options.responseId,
    trace_id: options.traceId,
    created_after_ms: options.createdAfterMs,
    created_before_ms: options.createdBeforeMs,
    limit: options.limit,
  };
}

async function parseJsonResponse(response: Response): Promise<unknown> {
  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;
  if (!response.ok) {
    throw new Error(`AnyAgent request failed: ${response.status} ${response.statusText} ${text}`.trim());
  }
  return payload;
}

function assertRequestObject(request: OpenAIResponsesCreateRequest): void {
  if (typeof request !== "object" || request === null || Array.isArray(request)) {
    throw new Error("Responses request body must be a JSON object");
  }
}

function validateOpenAIResponsePayload(payload: unknown): OpenAIResponseJson {
  if (
    typeof payload !== "object" ||
    payload === null ||
    Array.isArray(payload) ||
    typeof (payload as { id?: unknown }).id !== "string"
  ) {
    throw new Error("Response does not match OpenAI Responses object payload");
  }
  return payload as OpenAIResponseJson;
}

function withSkillMentions(request: OpenAIResponsesCreateRequest, skills?: string[]): OpenAIResponsesCreateRequest {
  const mentions = (skills ?? []).map((skill) => skill.trim()).filter(Boolean);
  if (!mentions.length) {
    return request;
  }
  const metadata = request.metadata;
  if (metadata !== undefined && (typeof metadata !== "object" || metadata === null || Array.isArray(metadata))) {
    throw new Error("Responses request metadata must be an object when skills are provided");
  }
  const existing = metadata as Record<string, unknown> | undefined;
  const existingMentions = metadataSkillList(existing?.skills);
  return {
    ...request,
    metadata: {
      ...(existing ?? {}),
      skills: Array.from(new Set([...existingMentions, ...mentions])),
    },
  };
}

function metadataSkillList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.filter((item): item is string => typeof item === "string" && item.trim().length > 0).map((item) => item.trim());
  }
  if (typeof value !== "string" || !value.trim()) {
    return [];
  }
  try {
    const parsed: unknown = JSON.parse(value);
    return Array.isArray(parsed)
      ? parsed.filter((item): item is string => typeof item === "string" && item.trim().length > 0).map((item) => item.trim())
      : [];
  } catch {
    return [];
  }
}

function buildResponseHeaders(apiKey: string, options: ResponsesRequestOptions): Headers {
  const headers = new Headers({
    authorization: `Bearer ${apiKey}`,
    "content-type": "application/json",
  });
  if (options.agentId) {
    headers.set("x-agent-id", options.agentId);
  }
  if (options.idempotencyKey) {
    headers.set("idempotency-key", options.idempotencyKey);
  }
  return headers;
}

function parseJsonData(data: string): unknown | null {
  if (data === "[DONE]") {
    return null;
  }
  try {
    return JSON.parse(data);
  } catch {
    return null;
  }
}

async function* parseSseEvents(body: ReadableStream<Uint8Array>): AsyncGenerator<AnyAgentSseEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const drain = function* (final = false): Generator<AnyAgentSseEvent> {
    while (true) {
      const separator = /\r?\n\r?\n/.exec(buffer);
      if (!separator || typeof separator.index === "undefined") {
        break;
      }
      const rawBlock = buffer.slice(0, separator.index);
      buffer = buffer.slice(separator.index + separator[0].length);
      const parsed = parseSseBlock(rawBlock);
      if (parsed) {
        yield parsed;
      }
    }
    if (final && buffer.trim()) {
      const parsed = parseSseBlock(buffer);
      buffer = "";
      if (parsed) {
        yield parsed;
      }
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      buffer += decoder.decode();
      for (const event of drain(true)) {
        yield event;
      }
      return;
    }
    buffer += decoder.decode(value, { stream: true });
    for (const event of drain()) {
      yield event;
    }
  }
}

function parseSseBlock(rawBlock: string): AnyAgentSseEvent | null {
  let id: string | null = null;
  let event: string | null = null;
  const data: string[] = [];
  for (const line of rawBlock.split(/\r?\n/)) {
    if (line.startsWith("id:")) {
      id = line.slice("id:".length).trim() || null;
    } else if (line.startsWith("event:")) {
      event = line.slice("event:".length).trim() || null;
    } else if (line.startsWith("data:")) {
      data.push(line.slice("data:".length).trimStart());
    }
  }
  if (id === null && event === null && data.length === 0) {
    return null;
  }
  const text = data.join("\n");
  return { id, event, data: text, json: parseJsonData(text) };
}

class AnyAgentHttp {
  readonly baseUrl: string;
  readonly apiKey: string;
  readonly fetchImpl: AnyAgentFetch;

  constructor(options: AnyAgentClientOptions) {
    this.baseUrl = normalizeBaseUrl(options.baseUrl ?? "http://127.0.0.1:8787");
    this.apiKey = options.apiKey;
    this.fetchImpl = options.fetch ?? fetch;
  }

  async get<T>(options: RequestOptions): Promise<T> {
    const url = new URL(`${this.baseUrl}${options.path}`);
    appendParams(url, options.params);
    const response = await this.fetchImpl(url, {
      method: "GET",
      headers: {
        authorization: `Bearer ${this.apiKey}`,
      },
    });
    const payload = await parseJsonResponse(response);
    return validateProtocolModel<T>(options.schemaName, payload);
  }

  endpointPath(operation: string, pathParams: EndpointPathParams = {}): string {
    return applyPathParams(this.endpoint(operation).path, pathParams);
  }

  async getEndpoint<T>(options: EndpointRequestOptions): Promise<T> {
    const endpoint = this.endpoint(options.operation);
    return this.get<T>({
      path: applyPathParams(endpoint.path, options.pathParams),
      params: options.params,
      schemaName: this.responseSchema(endpoint),
    });
  }

  async post<T>(options: JsonRequestOptions): Promise<T> {
    return this.requestJson<T>("POST", options);
  }

  async postEndpoint<T>(options: EndpointJsonRequestOptions): Promise<T> {
    const endpoint = this.endpoint(options.operation);
    let path = applyPathParams(endpoint.path, options.pathParams);
    if (options.params) {
      const url = new URL(`${this.baseUrl}${path}`);
      appendParams(url, options.params);
      path = url.pathname + url.search;
    }
    return this.post<T>({
      path,
      body: options.body,
      headers: options.headers,
      requestSchemaName: endpoint.request_model,
      schemaName: this.responseSchema(endpoint),
    });
  }

  async put<T>(options: JsonRequestOptions): Promise<T> {
    return this.requestJson<T>("PUT", options);
  }

  async putEndpoint<T>(options: EndpointJsonRequestOptions): Promise<T> {
    const endpoint = this.endpoint(options.operation);
    let path = applyPathParams(endpoint.path, options.pathParams);
    if (options.params) {
      const url = new URL(`${this.baseUrl}${path}`);
      appendParams(url, options.params);
      path = url.pathname + url.search;
    }
    return this.put<T>({
      path,
      body: options.body,
      headers: options.headers,
      requestSchemaName: endpoint.request_model,
      schemaName: this.responseSchema(endpoint),
    });
  }

  private async requestJson<T>(method: "POST" | "PUT", options: JsonRequestOptions): Promise<T> {
    const url = new URL(`${this.baseUrl}${options.path}`);
    const body = options.requestSchemaName
      ? validateProtocolRequest(options.requestSchemaName, options.body)
      : options.body;
    const response = await this.fetchImpl(url, {
      method,
      headers: {
        authorization: `Bearer ${this.apiKey}`,
        ...(typeof body === "undefined" ? {} : { "content-type": "application/json" }),
        ...Object.fromEntries(
          Object.entries(options.headers ?? {}).filter((entry): entry is [string, string] => typeof entry[1] === "string"),
        ),
      },
      body: typeof body === "undefined" ? undefined : JSON.stringify(body),
    });
    const payload = await parseJsonResponse(response);
    return validateProtocolModel<T>(options.schemaName, payload);
  }

  async delete<T = unknown>(options: DeleteRequestOptions): Promise<T> {
    const url = new URL(`${this.baseUrl}${options.path}`);
    const response = await this.fetchImpl(url, {
      method: "DELETE",
      headers: {
        authorization: `Bearer ${this.apiKey}`,
      },
    });
    const payload = await parseJsonResponse(response);
    return options.schemaName ? validateProtocolModel<T>(options.schemaName, payload) : (payload as T);
  }

  async deleteEndpoint<T = unknown>(options: EndpointDeleteRequestOptions): Promise<T> {
    const endpoint = this.endpoint(options.operation);
    return this.delete<T>({
      path: applyPathParams(endpoint.path, options.pathParams),
      schemaName: this.responseSchema(endpoint),
    });
  }

  private endpoint(operation: string): ProtocolEndpoint {
    return getProtocolEndpoint(operation);
  }

  private responseSchema(endpoint: ProtocolEndpoint): string {
    if (!endpoint.response_model) {
      throw new Error(`Protocol endpoint does not declare a response model: ${endpoint.operation}`);
    }
    return endpoint.response_model;
  }
}

export class AnyAgentResponses {
  constructor(private readonly http: AnyAgentHttp) {}

  async create(
    request: OpenAIResponsesCreateRequest,
    options: ResponsesRequestOptions = {},
  ): Promise<OpenAIResponseJson> {
    assertRequestObject(request);
    const body = withSkillMentions({ ...request, stream: false }, options.skills);
    const response = await this.http.fetchImpl(new URL(`${this.http.baseUrl}${this.http.endpointPath("responses.create")}`), {
      method: "POST",
      headers: buildResponseHeaders(this.http.apiKey, options),
      body: JSON.stringify(body),
      signal: options.signal,
    });
    return validateOpenAIResponsePayload(await parseJsonResponse(response));
  }

  async *stream(
    request: OpenAIResponsesCreateRequest,
    options: ResponsesRequestOptions = {},
  ): AsyncGenerator<AnyAgentSseEvent> {
    assertRequestObject(request);
    const body = withSkillMentions({ ...request, stream: true }, options.skills);
    const response = await this.http.fetchImpl(new URL(`${this.http.baseUrl}${this.http.endpointPath("responses.stream")}`), {
      method: "POST",
      headers: buildResponseHeaders(this.http.apiKey, options),
      body: JSON.stringify(body),
      signal: options.signal,
    });
    if (!response.ok) {
      await parseJsonResponse(response);
      return;
    }
    if (!response.body) {
      throw new Error("Streaming response does not include a readable body");
    }
    for await (const event of parseSseEvents(response.body)) {
      yield event;
    }
  }

  async retrieve(responseId: string): Promise<AnyAgentResponseStatusPayload> {
    return this.http.getEndpoint<AnyAgentResponseStatusPayload>({
      operation: "responses.retrieve",
      pathParams: { response_id: responseId },
    });
  }

  async cancel(responseId: string): Promise<AnyAgentResponseStatusPayload> {
    return this.http.postEndpoint<AnyAgentResponseStatusPayload>({
      operation: "responses.cancel",
      pathParams: { response_id: responseId },
    });
  }
}

export class AnyAgentEvents {
  constructor(private readonly http: AnyAgentHttp) {}

  async list(
    responseId: string,
    options: { lastSeq?: number; limit?: number } = {},
  ): Promise<InternalEventsListResponse> {
    return this.http.getEndpoint<InternalEventsListResponse>({
      operation: "events.list",
      params: {
        response_id: responseId,
        last_seq: options.lastSeq ?? 0,
        limit: options.limit ?? 200,
      },
    });
  }

  async toolExecutions(responseId: string): Promise<InternalResponseToolExecutionsResponse> {
    return this.http.getEndpoint<InternalResponseToolExecutionsResponse>({
      operation: "responses.tool_executions",
      pathParams: { response_id: responseId },
    });
  }

  async promptContext(responseId: string): Promise<InternalResponsePromptContextResponse> {
    return this.http.getEndpoint<InternalResponsePromptContextResponse>({
      operation: "responses.prompt_context",
      pathParams: { response_id: responseId },
    });
  }

  async modelRequest(responseId: string): Promise<InternalResponseModelRequestResponse> {
    return this.http.getEndpoint<InternalResponseModelRequestResponse>({
      operation: "responses.model_request",
      pathParams: { response_id: responseId },
    });
  }
}

export class AnyAgentSessions {
  constructor(private readonly http: AnyAgentHttp) {}

  async list(
    options: {
      agentId?: string;
      sessionKey?: string;
      cursorUpdatedBeforeMs?: number;
      limit?: number;
    } = {},
  ): Promise<InternalSessionsListResponse> {
    return this.http.getEndpoint<InternalSessionsListResponse>({
      operation: "sessions.list",
      params: {
        agent_id: options.agentId,
        session_key: options.sessionKey,
        cursor_updated_before_ms: options.cursorUpdatedBeforeMs,
        limit: options.limit ?? 100,
      },
    });
  }

  async get(
    sessionKey: string,
    options: { agentId?: string; limit?: number } = {},
  ): Promise<InternalSessionDetailResponse> {
    return this.http.getEndpoint<InternalSessionDetailResponse>({
      operation: "sessions.get",
      pathParams: { session_key: sessionKey },
      params: {
        agent_id: options.agentId,
        limit: options.limit ?? 100,
      },
    });
  }
}

export class AnyAgentEvaluations {
  constructor(private readonly http: AnyAgentHttp) {}

  async listDatasets(options: { agentId?: string } = {}): Promise<EvalDatasetsResponse> {
    return this.http.getEndpoint<EvalDatasetsResponse>({
      operation: "evaluations.datasets.list",
      params: options.agentId ? { agent_id: options.agentId } : undefined,
    });
  }

  async upsertDataset(request: EvalDatasetUpsertRequest): Promise<EvalDatasetResponse> {
    return this.http.postEndpoint<EvalDatasetResponse>({
      operation: "evaluations.datasets.upsert",
      body: request,
    });
  }

  async getDataset(datasetId: string): Promise<EvalDatasetResponse> {
    return this.http.getEndpoint<EvalDatasetResponse>({
      operation: "evaluations.datasets.get",
      pathParams: { dataset_id: datasetId },
    });
  }

  async deleteDataset(datasetId: string): Promise<Record<string, unknown>> {
    return this.http.delete<Record<string, unknown>>({
      path: this.http.endpointPath("evaluations.datasets.delete", { dataset_id: datasetId }),
    });
  }

  async run(request: EvalRunRequest): Promise<EvalRunResponse> {
    return this.http.postEndpoint<EvalRunResponse>({
      operation: "evaluations.run",
      body: request,
    });
  }

  async listRuns(
    options: { datasetId?: string; limit?: number } = {},
  ): Promise<EvalRunsResponse> {
    return this.http.getEndpoint<EvalRunsResponse>({
      operation: "evaluations.runs.list",
      params: {
        dataset_id: options.datasetId,
        limit: options.limit ?? 100,
      },
    });
  }

  async getRun(evalRunId: string): Promise<EvalRunResponse> {
    return this.http.getEndpoint<EvalRunResponse>({
      operation: "evaluations.runs.get",
      pathParams: { eval_run_id: evalRunId },
    });
  }
}

export class AnyAgentAudit {
  constructor(private readonly http: AnyAgentHttp) {}

  async events(
    options: {
      credentialId?: string;
      agentId?: string;
      sessionKey?: string;
      responseId?: string;
      traceId?: string;
      createdAfterMs?: number;
      createdBeforeMs?: number;
      limit?: number;
    } = {},
  ): Promise<InternalAuditEventsResponse> {
    return this.http.getEndpoint<InternalAuditEventsResponse>({
      operation: "audit.events",
      params: {
        credential_id: options.credentialId,
        agent_id: options.agentId,
        session_key: options.sessionKey,
        response_id: options.responseId,
        trace_id: options.traceId,
        created_after_ms: options.createdAfterMs,
        created_before_ms: options.createdBeforeMs,
        limit: options.limit ?? 100,
      },
    });
  }
}

export class AnyAgentAgents {
  constructor(private readonly http: AnyAgentHttp) {}

  async list(options: { includeUnexposed?: boolean } = {}): Promise<InternalAgentsListResponse> {
    return this.http.getEndpoint<InternalAgentsListResponse>({
      operation: "agents.list",
      params: {
        include_unexposed: options.includeUnexposed ?? false,
      },
    });
  }

  async get(agentId: string, options: { includePrompt?: boolean } = {}): Promise<InternalAgentDetailResponse> {
    return this.http.getEndpoint<InternalAgentDetailResponse>({
      operation: "agents.get",
      pathParams: { agent_id: agentId },
      params: {
        include_prompt: options.includePrompt ?? false,
      },
    });
  }
}

export class AnyAgentTools {
  constructor(private readonly http: AnyAgentHttp) {}

  async catalog(
    options: {
      agentId?: string;
      sessionKey?: string;
      requestedToolNames?: string[];
    } = {},
  ): Promise<InternalToolCatalogResponse> {
    const requested = options.requestedToolNames?.filter(Boolean).join(",");
    return this.http.getEndpoint<InternalToolCatalogResponse>({
      operation: "tools.catalog",
      params: {
        agent_id: options.agentId ?? "main",
        session_key: options.sessionKey ?? "sdk-catalog",
        requested_tool_names: requested || undefined,
      },
    });
  }

  async search(
    query: string,
    options: {
      agentId?: string;
      sessionKey?: string;
      requestedToolNames?: string[];
      limit?: number;
    } = {},
  ): Promise<InternalToolCatalogResponse> {
    const catalog = await this.catalog({
      agentId: options.agentId,
      sessionKey: options.sessionKey ?? "sdk-tool-search",
      requestedToolNames: options.requestedToolNames,
    });
    const needle = query.trim().toLowerCase();
    const limit = Math.max(0, options.limit ?? 10);
    const tools = catalog.tools ?? [];
    if (!needle) {
      return { ...catalog, tools: tools.slice(0, limit) };
    }
    return {
      ...catalog,
      tools: tools
        .filter((tool) =>
          tool.name.toLowerCase().includes(needle) ||
          (tool.description ?? "").toLowerCase().includes(needle) ||
          (tool.kind ?? "").toLowerCase().includes(needle) ||
          (tool.decision ?? "").toLowerCase().includes(needle),
        )
        .slice(0, limit),
    };
  }
}

export class AnyAgentSkills {
  constructor(private readonly http: AnyAgentHttp) {}

  async list(options: { agentId?: string } = {}): Promise<InternalSkillsListResponse> {
    return this.http.getEndpoint<InternalSkillsListResponse>({
      operation: "skills.list",
      params: {
        agent_id: options.agentId ?? "main",
      },
    });
  }
}

export class AnyAgentPrompts {
  constructor(private readonly http: AnyAgentHttp) {}

  async preview(
    request: OpenAIResponsesCreateRequest,
    options: { agentId?: string } = {},
  ): Promise<InternalPromptBundlePreviewResponse> {
    assertRequestObject(request);
    return this.http.postEndpoint<InternalPromptBundlePreviewResponse>({
      operation: "prompts.preview",
      body: request,
      headers: {
        "x-agent-id": options.agentId,
      },
    });
  }

  async listVersions(
    agentId: string,
    options: { limit?: number } = {},
  ): Promise<PromptVersionsResponse> {
    return this.http.getEndpoint<PromptVersionsResponse>({
      operation: "prompts.versions.list",
      params: {
        agent_id: agentId,
        limit: options.limit ?? 100,
      },
    });
  }

  async createVersion(request: PromptVersionCreateRequest): Promise<PromptVersionResponse> {
    return this.http.postEndpoint<PromptVersionResponse>({
      operation: "prompts.versions.create",
      body: request,
    });
  }

  async getVersion(agentId: string, versionId: string): Promise<PromptVersionResponse> {
    return this.http.getEndpoint<PromptVersionResponse>({
      operation: "prompts.versions.get",
      pathParams: { version_id: versionId },
      params: { agent_id: agentId },
    });
  }

  async diffVersions(
    agentId: string,
    fromVersionId: string,
    toVersionId: string,
  ): Promise<PromptVersionDiffResponse> {
    return this.http.getEndpoint<PromptVersionDiffResponse>({
      operation: "prompts.versions.diff",
      params: {
        agent_id: agentId,
        from_version_id: fromVersionId,
        to_version_id: toVersionId,
      },
    });
  }

  async restoreVersion(
    agentId: string,
    versionId: string,
  ): Promise<PromptVersionRestoreResponse> {
    return this.http.postEndpoint<PromptVersionRestoreResponse>({
      operation: "prompts.versions.restore",
      pathParams: { version_id: versionId },
      params: { agent_id: agentId },
    });
  }
}

export class AnyAgentObservability {
  constructor(private readonly http: AnyAgentHttp) {}

  async summary(responseId: string): Promise<InternalObservabilitySummaryResponse> {
    return this.http.getEndpoint<InternalObservabilitySummaryResponse>({
      operation: "observability.summary",
      params: {
        response_id: responseId,
      },
    });
  }

  async runs(options: Omit<ObservabilityQueryOptions, "traceId"> = {}): Promise<InternalObservabilityRunsResponse> {
    return this.http.getEndpoint<InternalObservabilityRunsResponse>({
      operation: "observability.runs",
      params: observabilityParams({ limit: 100, ...options }),
    });
  }

  async timeline(options: ObservabilityQueryOptions = {}): Promise<InternalObservabilityTimelineResponse> {
    return this.http.getEndpoint<InternalObservabilityTimelineResponse>({
      operation: "observability.timeline",
      params: observabilityParams({ limit: 200, ...options }),
    });
  }

  async metrics(options: Omit<ObservabilityQueryOptions, "traceId"> = {}): Promise<InternalObservabilityMetricsResponse> {
    return this.http.getEndpoint<InternalObservabilityMetricsResponse>({
      operation: "observability.metrics",
      params: observabilityParams({ limit: 100, ...options }),
    });
  }

  async tools(options: Omit<ObservabilityQueryOptions, "traceId"> = {}): Promise<InternalObservabilityToolsResponse> {
    return this.http.getEndpoint<InternalObservabilityToolsResponse>({
      operation: "observability.tools",
      params: observabilityParams({ limit: 100, ...options }),
    });
  }

  async errors(options: ObservabilityQueryOptions = {}): Promise<InternalObservabilityErrorsResponse> {
    return this.http.getEndpoint<InternalObservabilityErrorsResponse>({
      operation: "observability.errors",
      params: observabilityParams({ limit: 100, ...options }),
    });
  }

  async trace(traceId: string, options: { limit?: number } = {}): Promise<InternalObservabilityTraceResponse> {
    return this.http.getEndpoint<InternalObservabilityTraceResponse>({
      operation: "observability.trace",
      pathParams: { trace_id: traceId },
      params: {
        limit: options.limit ?? 500,
      },
    });
  }

  async alerts(options: ObservabilityQueryOptions = {}): Promise<AlertEventsResponse> {
    return this.http.getEndpoint<AlertEventsResponse>({
      operation: "observability.alerts",
      params: observabilityParams({ limit: 100, ...options }),
    });
  }
}

export class AnyAgentAdmin {
  constructor(private readonly http: AnyAgentHttp) {}

  async storageHealth(): Promise<StorageHealthResponse> {
    return this.http.getEndpoint<StorageHealthResponse>({
      operation: "admin.storage.health",
    });
  }

  async toolCatalog(): Promise<AdminToolCatalogResponse> {
    return this.http.getEndpoint<AdminToolCatalogResponse>({
      operation: "admin.tools.catalog",
    });
  }

  async pluginCatalog(): Promise<PluginCatalogResponse> {
    return this.http.getEndpoint<PluginCatalogResponse>({
      operation: "admin.plugins.catalog",
    });
  }

  async setCredential(request: AdminCredentialSetRequest): Promise<AdminCredentialRef> {
    return this.http.postEndpoint<AdminCredentialRef>({
      operation: "admin.credentials.set",
      body: request,
    });
  }

  async listCredentials(): Promise<AdminCredentialListResponse> {
    return this.http.getEndpoint<AdminCredentialListResponse>({
      operation: "admin.credentials.list",
    });
  }

  async deleteCredential(credentialId: string): Promise<AdminCredentialDeleteResponse> {
    const payload = await this.http.deleteEndpoint<AdminCredentialDeleteResponse>({
      operation: "admin.credentials.delete",
      pathParams: { credential_id: credentialId },
    });
    return payload;
  }

  async createAgent(request: AdminAgentCreateRequest): Promise<AdminAgentCreateResponse> {
    return this.http.postEndpoint<AdminAgentCreateResponse>({
      operation: "admin.workspace.agent.create",
      body: request,
    });
  }

  async getAgent(agentId: string, options: { includePrompt?: boolean } = {}): Promise<InternalAgentDetailResponse> {
    return this.http.getEndpoint<InternalAgentDetailResponse>({
      operation: "admin.workspace.agent.get",
      pathParams: { agent_id: agentId },
      params: {
        include_prompt: options.includePrompt ?? false,
      },
    });
  }

  async listAgentFiles(agentId: string): Promise<AdminWorkspaceAgentFilesResponse> {
    return this.http.getEndpoint<AdminWorkspaceAgentFilesResponse>({
      operation: "admin.workspace.agent.files",
      pathParams: { agent_id: agentId },
    });
  }

  async updateAgentFile(
    agentId: string,
    kind: "agents_md" | "agent_yaml" | "mcp_json",
    request: AdminWorkspaceAgentFileUpdateRequest,
  ): Promise<AdminWorkspaceAgentFileUpdateResponse> {
    return this.http.putEndpoint<AdminWorkspaceAgentFileUpdateResponse>({
      operation: "admin.workspace.agent.file.update",
      pathParams: { agent_id: agentId, kind },
      body: request,
    });
  }

  async importAgentSkill(agentId: string, request: AdminSkillImportRequest): Promise<AdminSkillImportResponse> {
    return this.http.postEndpoint<AdminSkillImportResponse>({
      operation: "admin.skill.import",
      pathParams: { agent_id: agentId },
      body: request,
    });
  }

  async installAgentSkill(agentId: string, request: AdminSkillRegistryInstallRequest): Promise<AdminSkillImportResponse> {
    return this.http.postEndpoint<AdminSkillImportResponse>({
      operation: "admin.skill.install",
      pathParams: { agent_id: agentId },
      body: request,
    });
  }

  async checkAgentSkillUpdate(agentId: string, directoryName: string): Promise<AdminSkillUpdateCheckResponse> {
    return this.http.getEndpoint<AdminSkillUpdateCheckResponse>({
      operation: "admin.skill.update.check",
      pathParams: { agent_id: agentId, directory_name: directoryName },
    });
  }

  async applyAgentSkillUpdate(agentId: string, directoryName: string): Promise<AdminSkillImportResponse> {
    return this.http.postEndpoint<AdminSkillImportResponse>({
      operation: "admin.skill.update.apply",
      pathParams: { agent_id: agentId, directory_name: directoryName },
      body: {},
    });
  }

  async updateAgentSkills(agentId: string, request: AdminAgentSkillsUpdateRequest): Promise<AdminAgentCreateResponse> {
    return this.http.putEndpoint<AdminAgentCreateResponse>({
      operation: "admin.agent.skills.update",
      pathParams: { agent_id: agentId },
      body: request,
    });
  }

  async updateAgentConfig(agentId: string, request: AdminAgentConfigUpdateRequest): Promise<AdminAgentCreateResponse> {
    return this.http.putEndpoint<AdminAgentCreateResponse>({
      operation: "admin.agent.config.update",
      pathParams: { agent_id: agentId },
      body: request,
    });
  }

  async listSandboxes(): Promise<AdminSandboxWorkspaceListResponse> {
    return this.http.getEndpoint<AdminSandboxWorkspaceListResponse>({
      operation: "admin.sandboxes.list",
    });
  }

  async listWorkspaceSnapshots(workspaceId: string): Promise<AdminSandboxWorkspaceSnapshotsResponse> {
    return this.http.getEndpoint<AdminSandboxWorkspaceSnapshotsResponse>({
      operation: "admin.sandboxes.workspace.snapshots",
      pathParams: { workspace_id: workspaceId },
    });
  }

  async reclaimWorkspace(workspaceId: string): Promise<AdminSandboxWorkspaceReclaimResponse> {
    return this.http.postEndpoint<AdminSandboxWorkspaceReclaimResponse>({
      operation: "admin.sandboxes.workspace.reclaim",
      pathParams: { workspace_id: workspaceId },
    });
  }

  async listAgentMcpServers(agentId: string): Promise<AdminMcpServersResponse> {
    return this.http.getEndpoint<AdminMcpServersResponse>({
      operation: "admin.workspace.agent.mcp.servers",
      pathParams: { agent_id: agentId },
    });
  }

  async setAgentMcpServerEnabled(
    agentId: string,
    serverLabel: string,
    request: AdminMcpServerEnableRequest,
  ): Promise<AdminMcpServerEnableResponse> {
    return this.http.putEndpoint<AdminMcpServerEnableResponse>({
      operation: "admin.workspace.agent.mcp.server.enabled",
      pathParams: { agent_id: agentId, server_label: serverLabel },
      body: request,
    });
  }

  async testAgentMcpServer(
    agentId: string,
    serverLabel: string,
    options: { sessionKey?: string } = {},
  ): Promise<AdminMcpServerTestResponse> {
    return this.http.postEndpoint<AdminMcpServerTestResponse>({
      operation: "admin.workspace.agent.mcp.server.test",
      pathParams: { agent_id: agentId, server_label: serverLabel },
      params: options.sessionKey ? { session_key: options.sessionKey } : undefined,
    });
  }
}

export class AnyAgentClient {
  readonly responses: AnyAgentResponses;
  readonly events: AnyAgentEvents;
  readonly sessions: AnyAgentSessions;
  readonly evaluations: AnyAgentEvaluations;
  readonly audit: AnyAgentAudit;
  readonly agents: AnyAgentAgents;
  readonly tools: AnyAgentTools;
  readonly skills: AnyAgentSkills;
  readonly prompts: AnyAgentPrompts;
  readonly observability: AnyAgentObservability;
  readonly admin: AnyAgentAdmin;

  private readonly http: AnyAgentHttp;

  constructor(options: AnyAgentClientOptions) {
    this.http = new AnyAgentHttp(options);
    this.responses = new AnyAgentResponses(this.http);
    this.events = new AnyAgentEvents(this.http);
    this.sessions = new AnyAgentSessions(this.http);
    this.evaluations = new AnyAgentEvaluations(this.http);
    this.audit = new AnyAgentAudit(this.http);
    this.agents = new AnyAgentAgents(this.http);
    this.tools = new AnyAgentTools(this.http);
    this.skills = new AnyAgentSkills(this.http);
    this.prompts = new AnyAgentPrompts(this.http);
    this.observability = new AnyAgentObservability(this.http);
    this.admin = new AnyAgentAdmin(this.http);
  }

  async health(): Promise<HealthResponse> {
    return this.http.getEndpoint<HealthResponse>({
      operation: "health",
    });
  }
}
