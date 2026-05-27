import schemaBundle from "../generated/protocol-schema.json" with { type: "json" };

export type JsonSchema = Record<string, unknown>;

export interface SemanticRule {
  id: string;
  kind: string;
  mode: "before_validation" | "after_validation";
  fields: string[];
  description: string;
  examples: {
    valid: unknown[];
    invalid: unknown[];
  };
}

export interface ProtocolEndpoint {
  operation: string;
  method: "DELETE" | "GET" | "POST" | "PUT";
  path: string;
  request_model?: string;
  request_format?: string;
  response_model?: string;
  response_format?: string;
}

export interface ProtocolSchemaBundle {
  schema_version: string;
  protocol_package: "anyagent.protocol";
  endpoints: ProtocolEndpoint[];
  models: Record<string, JsonSchema>;
  semantic_rules: Record<string, SemanticRule[]>;
  type_adapters: Record<string, JsonSchema>;
}

export const protocolSchemaBundle = schemaBundle as ProtocolSchemaBundle;

export function getProtocolModelSchema(name: string): JsonSchema {
  const schema = protocolSchemaBundle.models[name];
  if (!schema) {
    throw new Error(`Unknown anyagent protocol model schema: ${name}`);
  }
  return schema;
}

export function getProtocolTypeAdapterSchema(name: string): JsonSchema {
  const schema = protocolSchemaBundle.type_adapters[name];
  if (!schema) {
    throw new Error(`Unknown anyagent protocol type adapter schema: ${name}`);
  }
  return schema;
}

export function getProtocolSemanticRules(name: string): SemanticRule[] {
  return protocolSchemaBundle.semantic_rules[name] ?? [];
}

export function getProtocolEndpoint(operation: string): ProtocolEndpoint {
  const endpoint = protocolSchemaBundle.endpoints.find((item) => item.operation === operation);
  if (!endpoint) {
    throw new Error(`Unknown anyagent protocol endpoint operation: ${operation}`);
  }
  return endpoint;
}
