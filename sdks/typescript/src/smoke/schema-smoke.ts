import {
  generateProtocolTypes,
  getProtocolEndpoint,
  getProtocolModelSchema,
  getProtocolSemanticRules,
  getProtocolTypeAdapterSchema,
  protocolSchemaBundle,
} from "../index.js";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) {
    throw new Error(message);
  }
}

const health = getProtocolModelSchema("anyagent.protocol.health.HealthResponse");
assert(health.type === "object", "HealthResponse schema should be an object");

const internalEvents = getProtocolModelSchema("anyagent.protocol.agent_api_internal.InternalEventsListResponse");
assert(internalEvents.type === "object", "InternalEventsListResponse schema should be an object");

const stageEvent = getProtocolTypeAdapterSchema("anyagent.protocol.stage_events.StageEvent");
const discriminator = stageEvent.discriminator as { propertyName?: unknown } | undefined;
assert(discriminator?.propertyName === "type", "StageEvent schema should discriminate on type");

assert(protocolSchemaBundle.protocol_package === "anyagent.protocol", "schema bundle should come from anyagent.protocol");
assert(Object.keys(protocolSchemaBundle.models).length > 100, "schema bundle should include protocol models");
const storageHealthEndpoint = getProtocolEndpoint("admin.storage.health");
assert(storageHealthEndpoint.path === "/admin/storage/health", "endpoint manifest should expose admin storage health");
assert(
  storageHealthEndpoint.response_model === "anyagent.protocol.admin_storage.StorageHealthResponse",
  "endpoint manifest should bind storage health to its protocol response model",
);
const credentialSetEndpoint = getProtocolEndpoint("admin.credentials.set");
assert(
  credentialSetEndpoint.request_model === "anyagent.protocol.credential_vault.AdminCredentialSetRequest",
  "endpoint manifest should bind credential set to its protocol request model",
);
const responsesStreamEndpoint = getProtocolEndpoint("responses.stream");
assert(
  responsesStreamEndpoint.response_format === "responses_sse_stream",
  "endpoint manifest should mark streaming Responses helpers as SSE",
);
const credentialRules = getProtocolSemanticRules("anyagent.protocol.credential_vault.CredentialScope");
assert(
  credentialRules.some((rule) => rule.id === "credential_scope_agent_id_matches_level"),
  "CredentialScope semantic rules should include agent scope cross-field rule",
);
const toolContextRules = getProtocolSemanticRules("anyagent.protocol.tool_runtime.ToolContext");
assert(
  toolContextRules.some((rule) => rule.id === "tool_context_rejects_plaintext_secret_fields"),
  "ToolContext semantic rules should include plaintext secret rejection rule",
);

const generatedTypes = generateProtocolTypes();
assert(generatedTypes.includes("export type HealthResponse"), "generated types should include HealthResponse");
assert(generatedTypes.includes("export type StageEvent"), "generated types should include StageEvent");
assert(generatedTypes.includes("schema_version: 2026-09-07"), "generated types should include schema version");

console.log(
  `ok: protocol schema ${protocolSchemaBundle.schema_version} models=${Object.keys(protocolSchemaBundle.models).length}`,
);
