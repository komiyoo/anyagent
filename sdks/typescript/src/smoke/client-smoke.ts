import { AnyAgentClient, AnyAgentSchemaValidationError, type AnyAgentFetch } from "../index.js";
import { SdkConformanceFixtureStore } from "./conformanceFixture.js";

interface RecordedRequest {
  url: string;
  method: string;
  authorization: string | null;
  agentId: string | null;
  body: unknown;
}

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) {
    throw new Error(message);
  }
}

const seen: RecordedRequest[] = [];

const fixture = new SdkConformanceFixtureStore();

const fakeFetch: AnyAgentFetch = async (input, init) => {
  const url = new URL(String(input));
  seen.push({
    url: url.toString(),
    method: init?.method ?? "GET",
    authorization: new Headers(init?.headers).get("authorization"),
    agentId: new Headers(init?.headers).get("x-agent-id"),
    body: typeof init?.body === "string" ? JSON.parse(init.body) : null,
  });

  let body: unknown;
  if (url.pathname === "/healthz") {
    body = fixture.payload("health.ok");
  } else if (url.pathname === "/v1/responses" && init?.method === "POST") {
    const requestBody = typeof init.body === "string" ? JSON.parse(init.body) : {};
    if (requestBody.stream === true) {
      return new Response(
        [...fixture.fixture.response_stream_sse_blocks, ""].join("\n\n"),
        {
          status: 200,
          headers: { "content-type": "text/event-stream" },
        },
      );
    }
    body = fixture.openAIResponsePayload("responses.create.completed");
  } else if (url.pathname === "/v1/responses/resp_1") {
    body = fixture.openAIResponsePayload("responses.retrieve.in_progress");
  } else if (url.pathname === "/v1/responses/resp_1/cancel") {
    body = fixture.openAIResponsePayload("responses.cancel.cancelled");
  } else if (url.pathname === "/internal/events/list") {
    body = fixture.payload("events.list.empty_done");
  } else if (url.pathname === "/internal/responses/resp_1/prompt-context") {
    body = fixture.payload("responses.prompt_context.rendered");
  } else if (url.pathname === "/internal/responses/resp_1/tool-executions") {
    body = fixture.payload("responses.tool_executions.detail");
  } else if (url.pathname === "/internal/responses/resp_1/model-request") {
    body = fixture.payload("responses.model_request.applied_body");
  } else if (url.pathname === "/internal/agents") {
    body = fixture.payload("agents.list.main");
  } else if (url.pathname === "/internal/agents/main") {
    body = fixture.payload("agents.detail.main");
  } else if (url.pathname === "/internal/tools/catalog") {
    body = fixture.payload("tools.catalog.exec");
  } else if (url.pathname === "/internal/skills/list") {
    body = fixture.payload("skills.list.repo_helper");
  } else if (url.pathname === "/internal/prompt/bundle" && init?.method === "POST") {
    body = fixture.payload("prompt.bundle.preview");
  } else if (url.pathname === "/internal/observability/summary") {
    body = fixture.payload("observability.summary");
  } else if (url.pathname === "/internal/observability/runs") {
    body = fixture.payload("observability.runs");
  } else if (url.pathname === "/internal/observability/timeline") {
    body = fixture.payload("observability.timeline");
  } else if (url.pathname === "/internal/observability/metrics") {
    body = fixture.payload("observability.metrics");
  } else if (url.pathname === "/internal/observability/tools") {
    body = fixture.payload("observability.tools");
  } else if (url.pathname === "/internal/observability/errors") {
    body = fixture.payload("observability.errors");
  } else if (url.pathname === "/internal/observability/traces/trace_1") {
    body = fixture.payload("observability.trace");
  } else if (url.pathname === "/admin/storage/health") {
    body = fixture.payload("admin.storage.health");
  } else if (url.pathname === "/admin/tools/catalog") {
    body = fixture.payload("admin.tools.catalog");
  } else if (url.pathname === "/admin/plugins/catalog") {
    body = fixture.payload("admin.plugins.catalog");
  } else if (url.pathname === "/admin/workspace/agents" && init?.method === "POST") {
    body = fixture.payload("admin.workspace.agent.create");
  } else if (url.pathname === "/admin/workspace/agents/main") {
    body = fixture.payload("agents.detail.main");
  } else if (url.pathname === "/admin/credentials" && init?.method === "POST") {
    body = fixture.payload("admin.credentials.set");
  } else if (url.pathname === "/admin/credentials") {
    body = fixture.payload("admin.credentials.list");
  } else if (url.pathname === "/admin/credentials/cred_demo" && init?.method === "DELETE") {
    body = fixture.payload("admin.credentials.delete");
  } else if (url.pathname === "/admin/workspace/agents/main/files") {
    body = fixture.payload("admin.workspace.agent.files");
  } else if (url.pathname === "/admin/workspace/agents/main/files/agents_md" && init?.method === "PUT") {
    body = fixture.payload("admin.workspace.agent.file.update");
  } else if (url.pathname === "/admin/workspace/agents/main/skills/import" && init?.method === "POST") {
    body = fixture.payload("admin.skill.import");
  } else if (url.pathname === "/admin/workspace/agents/main/skills/install" && init?.method === "POST") {
    body = fixture.payload("admin.skill.install");
  } else if (url.pathname === "/admin/workspace/agents/main/skills/repo-helper/update/check") {
    body = fixture.payload("admin.skill.update.check");
  } else if (url.pathname === "/admin/workspace/agents/main/skills/repo-helper/update/apply" && init?.method === "POST") {
    body = fixture.payload("admin.skill.update.apply");
  } else if (url.pathname === "/admin/workspace/agents/main/skills" && init?.method === "PUT") {
    body = fixture.payload("admin.agent.skills.update");
  } else if (url.pathname === "/admin/workspace/agents/main/config" && init?.method === "PUT") {
    body = fixture.payload("admin.agent.config.update");
  } else {
    return new Response(JSON.stringify({ error: "not found" }), { status: 404 });
  }

  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
};

const client = new AnyAgentClient({
  apiKey: "test-key",
  baseUrl: "http://example.test/",
  fetch: fakeFetch,
});

assert(typeof client.responses.create === "function", "MVU should expose responses.create");
assert(typeof client.responses.stream === "function", "MVU should expose responses.stream");
assert(typeof client.responses.cancel === "function", "MVU should expose responses.cancel");
assert(typeof client.agents.list === "function", "MVU should expose agents namespace");
assert(typeof client.tools.catalog === "function", "MVU should expose tools namespace");
assert(typeof client.skills.list === "function", "MVU should expose skills namespace");

const health = await client.health();
assert(health.ok === true, "health should decode response");

const created = await client.responses.create(
  { model: "test-model", input: "hello", metadata: { skills: ["existing"] } },
  { agentId: "main", idempotencyKey: "idem_1", skills: ["repo-helper", "existing"] },
);
assert(created.id === "resp_create", "responses.create should decode OpenAI response payload");

const streamEvents = [];
for await (const event of client.responses.stream({ model: "test-model", input: "hello" }, { agentId: "main" })) {
  streamEvents.push(event);
}
assert(streamEvents.length === 3, "responses.stream should parse SSE blocks");
assert(streamEvents[1]?.event === "response.completed", "responses.stream should preserve event names");
assert(
  typeof streamEvents[1]?.json === "object" && streamEvents[1]?.json !== null,
  "responses.stream should parse JSON data when possible",
);

const retrieved = await client.responses.retrieve("resp_1");
assert(retrieved.status === "in_progress", "responses.retrieve should decode response status");

const cancelled = await client.responses.cancel("resp_1");
assert(cancelled.status === "cancelled", "responses.cancel should decode response status");

const events = await client.events.list("resp_1", { lastSeq: 2, limit: 10 });
assert(events.response_id === "resp_1", "events.list should pass response_id");
assert(events.requested_last_seq === 2, "events.list should pass last_seq");

const promptContext = await client.events.promptContext("resp_1");
assert(
  promptContext.fragments?.[0]?.kind === "agents_instructions",
  "events.promptContext should decode rendered prompt context",
);

const toolExecutions = await client.events.toolExecutions("resp_1");
assert(
  toolExecutions.tool_executions?.[0]?.tool_name === "exec",
  "events.toolExecutions should decode tool execution details",
);

const modelRequest = await client.events.modelRequest("resp_1");
assert(
  modelRequest.applied_body?.["model"] === "test-model",
  "events.modelRequest should decode historical applied model request",
);

const agents = await client.agents.list({ includeUnexposed: true });
assert(Array.isArray(agents.agents), "agents.list should decode agents");
assert(agents.agents?.[0]?.agent_id === "main", "agents.list should decode agent catalog entries");

const agent = await client.agents.get("main", { includePrompt: true });
assert(agent.agent_id === "main", "agents.get should decode agent detail");

const tools = await client.tools.catalog({
  agentId: "main",
  sessionKey: "session_1",
  requestedToolNames: ["exec"],
});
assert(tools.toolset_version === 1, "tools.catalog should decode catalog");

const searchTools = await client.tools.search("exec", {
  agentId: "main",
  sessionKey: "session_1",
  requestedToolNames: ["exec"],
});
assert(searchTools.tools?.[0]?.name === "exec", "tools.search should filter catalog results");

const skills = await client.skills.list({ agentId: "main" });
assert(skills.skills?.[0]?.stable_id === "repo-helper", "skills.list should decode skills catalog");

const prompt = await client.prompts.preview({ model: "test-model", input: "hello" }, { agentId: "main" });
assert(prompt.prompt_cache_key === "prompt-cache-demo", "prompts.preview should decode prompt bundle");

const obsSummary = await client.observability.summary("resp_obs");
assert(obsSummary.response_id === "resp_obs", "observability.summary should decode summary");

const obsRuns = await client.observability.runs({
  agentId: "main",
  sessionKey: "session_1",
  responseId: "resp_obs",
  createdAfterMs: 1,
  createdBeforeMs: 10,
  limit: 5,
});
assert(obsRuns.runs?.[0]?.response_id === "resp_obs", "observability.runs should decode runs");

const obsTimeline = await client.observability.timeline({ traceId: "trace_1", limit: 3 });
assert(obsTimeline.events?.[0]?.trace_id === "trace_1", "observability.timeline should decode events");

const obsMetrics = await client.observability.metrics({ agentId: "main" });
assert(obsMetrics.run_count === 1, "observability.metrics should decode counters");

const obsTools = await client.observability.tools({ responseId: "resp_obs" });
assert(obsTools.tools?.[0]?.tool_name === "exec", "observability.tools should decode tool stats");

const obsErrors = await client.observability.errors({ traceId: "trace_1" });
assert(obsErrors.errors?.[0]?.type === "tool.error", "observability.errors should decode errors");

const obsTrace = await client.observability.trace("trace_1", { limit: 7 });
assert(obsTrace.trace_id === "trace_1", "observability.trace should decode trace");

const storage = await client.admin.storageHealth();
assert(storage.ok === true, "admin.storageHealth should decode storage health");

const adminTools = await client.admin.toolCatalog();
assert(adminTools.toolset_version === 1, "admin.toolCatalog should decode tool catalog");

const plugins = await client.admin.pluginCatalog();
assert(plugins.loaded?.[0]?.plugin_id === "demo", "admin.pluginCatalog should decode plugin catalog");

const credential = await client.admin.setCredential({
  credential_id: "cred_demo",
  kind: "bearer_token",
  value: "secret-value",
  scope: { level: "global" },
  metadata: {},
});
assert(credential.credential_id === "cred_demo", "admin.setCredential should decode credential ref");

const credentials = await client.admin.listCredentials();
assert(credentials.credentials.length === 1, "admin.listCredentials should decode credential refs");

const deleted = await client.admin.deleteCredential("cred_demo");
assert(deleted.deleted === true, "admin.deleteCredential should decode delete payload");

const createdAgent = await client.admin.createAgent({
  agent_id: "worker",
  instructions: "Help with focused tasks.",
  exposed: false,
  requested_tool_names: ["exec"],
});
assert(createdAgent.agent.agent_id === "worker", "admin.createAgent should decode created agent");

const adminAgent = await client.admin.getAgent("main", { includePrompt: true });
assert(adminAgent.agent_id === "main", "admin.getAgent should decode hidden/admin agent detail");

const files = await client.admin.listAgentFiles("main");
assert(files.files?.[0]?.kind === "agents_md", "admin.listAgentFiles should decode files");

const updated = await client.admin.updateAgentFile("main", "agents_md", {
  text: "new instructions",
  expected_sha256: "old-sha",
});
assert(updated.file.sha256 === "new-sha", "admin.updateAgentFile should decode updated file");

const importedSkill = await client.admin.importAgentSkill("main", {
  directory_name: "local-helper",
  skill_md: "---\nname: local-helper\n---\nUse local helper.",
});
assert(importedSkill.sha256 === "skill-import-sha", "admin.importAgentSkill should decode imported skill");

const installedSkill = await client.admin.installAgentSkill("main", {
  channel: "skills.sh",
  package: "repo-helper",
  skill: "repo-helper",
});
assert(installedSkill.sha256 === "skill-install-sha", "admin.installAgentSkill should decode installed skill");

const skillUpdate = await client.admin.checkAgentSkillUpdate("main", "repo-helper");
assert(skillUpdate.update_available === true, "admin.checkAgentSkillUpdate should decode update status");

const appliedSkillUpdate = await client.admin.applyAgentSkillUpdate("main", "repo-helper");
assert(appliedSkillUpdate.sha256 === "skill-update-sha", "admin.applyAgentSkillUpdate should decode updated skill");

const skillsUpdated = await client.admin.updateAgentSkills("main", {
  default_selected: ["repo-helper"],
});
assert(
  skillsUpdated.agent.skills.default_selected?.[0] === "repo-helper",
  "admin.updateAgentSkills should decode updated agent detail",
);

const configUpdated = await client.admin.updateAgentConfig("main", {
  exposed: false,
  requested_tool_names: ["core.web_fetch"],
});
assert(configUpdated.agent.exposed === false, "admin.updateAgentConfig should decode updated agent detail");

assert(
  seen.some((item) => item.url.endsWith("/v1/responses/resp_1/cancel") && item.method === "POST"),
  "responses.cancel should use POST",
);
assert(
  seen.some((item) => item.url.endsWith("/internal/responses/resp_1/tool-executions") && item.method === "GET"),
  "events.toolExecutions should use response-scoped replay endpoint",
);
assert(
  seen.some((item) => item.url.endsWith("/internal/responses/resp_1/model-request") && item.method === "GET"),
  "events.modelRequest should use response-scoped replay endpoint",
);
assert(
  seen.some(
    (item) =>
      item.url.endsWith("/v1/responses") &&
      item.method === "POST" &&
      typeof item.body === "object" &&
      item.body !== null &&
      (item.body as { stream?: unknown }).stream === false &&
      JSON.stringify((item.body as { metadata?: unknown }).metadata).includes("repo-helper"),
  ),
  "responses.create should POST non-stream requests with skill metadata",
);
assert(
  seen.some(
    (item) =>
      item.url.endsWith("/v1/responses") &&
      item.method === "POST" &&
      typeof item.body === "object" &&
      item.body !== null &&
      (item.body as { stream?: unknown }).stream === true,
  ),
  "responses.stream should POST stream requests",
);
assert(seen.every((item) => item.authorization === "Bearer test-key"), "client should send bearer auth");
assert(
  seen.some((item) => item.url.includes("include_unexposed=true")),
  "agents.list should encode include_unexposed",
);
assert(
  seen.some((item) => item.url.includes("requested_tool_names=exec")),
  "tools.catalog should encode requested tools",
);
assert(
  seen.some((item) => item.url.includes("/internal/skills/list?agent_id=main")),
  "skills.list should encode agent_id",
);
assert(
  seen.some(
    (item) =>
      item.url.endsWith("/internal/prompt/bundle") &&
      item.method === "POST" &&
      item.agentId === "main" &&
      typeof item.body === "object" &&
      item.body !== null &&
      (item.body as { input?: unknown }).input === "hello",
  ),
  "prompts.preview should POST request body with x-agent-id",
);
assert(
  seen.some((item) => item.url.includes("/internal/observability/runs?") && item.url.includes("created_after_ms=1")),
  "observability.runs should encode time window filters",
);
assert(
  seen.some((item) => item.url.includes("/internal/observability/timeline?") && item.url.includes("trace_id=trace_1")),
  "observability.timeline should encode trace filter",
);
assert(
  seen.some((item) => item.url.endsWith("/internal/observability/traces/trace_1?limit=7")),
  "observability.trace should encode trace id and limit",
);
assert(
  seen.some((item) => item.url.endsWith("/admin/storage/health") && item.method === "GET"),
  "admin.storageHealth should use GET",
);
assert(
  seen.some(
    (item) =>
      item.url.endsWith("/admin/workspace/agents") &&
      item.method === "POST" &&
      typeof item.body === "object" &&
      item.body !== null &&
      (item.body as { agent_id?: unknown }).agent_id === "worker",
  ),
  "admin.createAgent should send validated JSON body",
);
assert(
  seen.some((item) => item.url.endsWith("/admin/workspace/agents/main?include_prompt=true")),
  "admin.getAgent should encode include_prompt",
);
assert(
  seen.some(
    (item) =>
      item.url.endsWith("/admin/credentials") &&
      item.method === "POST" &&
      typeof item.body === "object" &&
      item.body !== null &&
      (item.body as { value?: unknown }).value === "secret-value",
  ),
  "admin.setCredential should send validated JSON body",
);
assert(
  seen.some(
    (item) =>
      item.url.endsWith("/admin/workspace/agents/main/files/agents_md") &&
      item.method === "PUT" &&
      typeof item.body === "object" &&
      item.body !== null &&
      (item.body as { expected_sha256?: unknown }).expected_sha256 === "old-sha",
  ),
  "admin.updateAgentFile should send validated JSON body",
);
assert(
  seen.some(
    (item) =>
      item.url.endsWith("/admin/workspace/agents/main/skills/import") &&
      item.method === "POST" &&
      typeof item.body === "object" &&
      item.body !== null &&
      (item.body as { directory_name?: unknown }).directory_name === "local-helper",
  ),
  "admin.importAgentSkill should send validated JSON body",
);
assert(
  seen.some(
    (item) =>
      item.url.endsWith("/admin/workspace/agents/main/skills/install") &&
      item.method === "POST" &&
      typeof item.body === "object" &&
      item.body !== null &&
      (item.body as { skill?: unknown }).skill === "repo-helper",
  ),
  "admin.installAgentSkill should send validated JSON body",
);
assert(
  seen.some(
    (item) =>
      item.url.endsWith("/admin/workspace/agents/main/skills") &&
      item.method === "PUT" &&
      typeof item.body === "object" &&
      item.body !== null &&
      Array.isArray((item.body as { default_selected?: unknown }).default_selected),
  ),
  "admin.updateAgentSkills should send validated JSON body",
);
assert(
  seen.some(
    (item) =>
      item.url.endsWith("/admin/workspace/agents/main/config") &&
      item.method === "PUT" &&
      typeof item.body === "object" &&
      item.body !== null &&
      (item.body as { exposed?: unknown }).exposed === false,
  ),
  "admin.updateAgentConfig should send validated JSON body",
);

const invalidClient = new AnyAgentClient({
  apiKey: "test-key",
  fetch: async () =>
    new Response(JSON.stringify({ ok: true, agent_ids: [] }), {
      status: 200,
      headers: { "content-type": "application/json" },
    }),
});

let validationFailed = false;
try {
  await invalidClient.health();
} catch (error) {
  validationFailed = error instanceof AnyAgentSchemaValidationError && error.message.includes("$.workspace");
}
assert(validationFailed, "client should validate response payloads against protocol schemas");

const requestValidationCount = seen.length;
let requestValidationFailed = false;
try {
  await client.admin.setCredential(fixture.negativePayload("credential.agent_scope_missing_agent_id"));
} catch (error) {
  requestValidationFailed = error instanceof AnyAgentSchemaValidationError && error.message.includes("$.scope.agent_id");
}
assert(requestValidationFailed, "client should validate admin credential request payloads before POST");
assert(seen.length === requestValidationCount, "invalid admin request should not call fetch");

let globalScopeValidationFailed = false;
try {
  await client.admin.setCredential(fixture.negativePayload("credential.global_scope_forbids_agent_id"));
} catch (error) {
  globalScopeValidationFailed = error instanceof AnyAgentSchemaValidationError && error.message.includes("$.scope.agent_id");
}
assert(globalScopeValidationFailed, "client should reject agent_id for global credential scope");
assert(seen.length === requestValidationCount, "invalid global credential scope should not call fetch");

let fileUpdateValidationFailed = false;
try {
  await client.admin.updateAgentFile("main", "agents_md", fixture.negativePayload("admin.file_update_missing_text"));
} catch (error) {
  fileUpdateValidationFailed = error instanceof AnyAgentSchemaValidationError && error.message.includes("$.text");
}
assert(fileUpdateValidationFailed, "client should validate admin file update request payloads before PUT");
assert(seen.length === requestValidationCount, "invalid admin file update should not call fetch");

let createAgentValidationFailed = false;
try {
  await client.admin.createAgent(fixture.negativePayload("admin.create_agent_missing_agent_id"));
} catch (error) {
  createAgentValidationFailed = error instanceof AnyAgentSchemaValidationError && error.message.includes("$.agent_id");
}
assert(createAgentValidationFailed, "client should validate admin create agent request payloads before POST");
assert(seen.length === requestValidationCount, "invalid admin create agent should not call fetch");

let skillImportValidationFailed = false;
try {
  await client.admin.importAgentSkill("main", fixture.negativePayload("admin.skill_import_missing_skill_md"));
} catch (error) {
  skillImportValidationFailed = error instanceof AnyAgentSchemaValidationError && error.message.includes("$.skill_md");
}
assert(skillImportValidationFailed, "client should validate admin skill import request payloads before POST");
assert(seen.length === requestValidationCount, "invalid admin skill import should not call fetch");

let configValidationFailed = false;
try {
  await client.admin.updateAgentConfig("main", fixture.negativePayload("admin.config_invalid_sandbox_mode"));
} catch (error) {
  configValidationFailed = error instanceof AnyAgentSchemaValidationError && error.message.includes("$.sandbox_mode");
}
assert(configValidationFailed, "client should validate admin config update request payloads before PUT");
assert(seen.length === requestValidationCount, "invalid admin config update should not call fetch");

const directNegativeCaseNames = [
  "mcp.server_config_url_and_command",
  "mcp.server_config_url_stdio",
  "multi_agent.spawn_missing_agent_id",
  "multi_agent.spawn_agent_type_mismatch",
  "multi_agent.send_input_empty",
  "tool_context_plaintext_token",
  "tool_context_nested_api_key",
];
fixture.assertRequestNegativeCases(directNegativeCaseNames);

fixture.assertTypeAdapterCases([
  "stage_event.tool.planned",
  "stage_event.command.result",
  "tool_runtime.execute.response",
]);
fixture.assertTypeAdapterNegativeCases([
  "stage_event.seq_zero",
  "tool_runtime.execute.invalid_status",
]);
fixture.assertMinimumMatrixReferences();

console.log(`ok: anyagent client smoke requests=${seen.length}`);
