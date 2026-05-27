import { getProtocolModelSchema, getProtocolTypeAdapterSchema, type JsonSchema } from "./schemaBundle.js";

export class AnyAgentSchemaValidationError extends Error {
  constructor(
    readonly schemaName: string,
    readonly path: string,
    message: string,
  ) {
    super(`Response does not match ${schemaName} at ${path}: ${message}`);
    this.name = "AnyAgentSchemaValidationError";
  }
}

interface ValidationContext {
  schemaName: string;
  root: JsonSchema;
  semanticName?: string;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function localRefSchema(root: JsonSchema, ref: string): JsonSchema | undefined {
  const prefix = "#/$defs/";
  if (!ref.startsWith(prefix)) {
    return undefined;
  }
  const rawName = decodeURIComponent(ref.slice(prefix.length));
  const defs = root.$defs;
  if (!isObject(defs)) {
    return undefined;
  }
  const value = defs[rawName];
  return isObject(value) ? value : undefined;
}

function fail(ctx: ValidationContext, path: string, message: string): never {
  throw new AnyAgentSchemaValidationError(ctx.schemaName, path, message);
}

function numberConstraint(schema: Record<string, unknown>, key: string): number | undefined {
  return typeof schema[key] === "number" ? schema[key] : undefined;
}

function validateSchema(schema: unknown, value: unknown, ctx: ValidationContext, path: string): void {
  if (!isObject(schema)) {
    return;
  }

  if (typeof schema.$ref === "string") {
    const resolved = localRefSchema(ctx.root, schema.$ref);
    if (!resolved) {
      return;
    }
    validateSchema(resolved, value, { ...ctx, semanticName: refName(schema.$ref) }, path);
    return;
  }

  if (Object.prototype.hasOwnProperty.call(schema, "const") && value !== schema.const) {
    fail(ctx, path, `expected const ${JSON.stringify(schema.const)}`);
  }

  if (Array.isArray(schema.enum) && !schema.enum.includes(value)) {
    fail(ctx, path, `expected one of ${schema.enum.map((item) => JSON.stringify(item)).join(", ")}`);
  }

  if (Array.isArray(schema.anyOf)) {
    validateAnyOf(schema.anyOf, value, ctx, path, "anyOf");
    return;
  }
  if (Array.isArray(schema.oneOf)) {
    validateAnyOf(schema.oneOf, value, ctx, path, "oneOf");
    return;
  }
  if (Array.isArray(schema.allOf)) {
    for (const item of schema.allOf) {
      validateSchema(item, value, ctx, path);
    }
    return;
  }

  switch (schema.type) {
    case "string":
      if (typeof value !== "string") fail(ctx, path, "expected string");
      validateStringConstraints(schema, value, ctx, path);
      return;
    case "integer":
      if (typeof value !== "number" || !Number.isInteger(value)) fail(ctx, path, "expected integer");
      validateNumberConstraints(schema, value, ctx, path);
      return;
    case "number":
      if (typeof value !== "number") fail(ctx, path, "expected number");
      validateNumberConstraints(schema, value, ctx, path);
      return;
    case "boolean":
      if (typeof value !== "boolean") fail(ctx, path, "expected boolean");
      return;
    case "null":
      if (value !== null) fail(ctx, path, "expected null");
      return;
    case "array":
      if (!Array.isArray(value)) fail(ctx, path, "expected array");
      validateArrayConstraints(schema, value, ctx, path);
      for (const [index, item] of value.entries()) {
        validateSchema(schema.items, item, ctx, `${path}[${index}]`);
      }
      return;
    case "object":
      validateObject(schema, value, ctx, path);
      runSemanticRules(value, ctx, path);
      return;
    default:
      if (schema.properties || schema.required) {
        validateObject(schema, value, ctx, path);
        runSemanticRules(value, ctx, path);
      }
  }
}

function refName(ref: string): string | undefined {
  const prefix = "#/$defs/";
  if (!ref.startsWith(prefix)) {
    return undefined;
  }
  return decodeURIComponent(ref.slice(prefix.length));
}

function validateAnyOf(schemas: unknown[], value: unknown, ctx: ValidationContext, path: string, label: string): void {
  const errors: string[] = [];
  for (const schema of schemas) {
    try {
      validateSchema(schema, value, ctx, path);
      return;
    } catch (error) {
      errors.push(error instanceof Error ? error.message : String(error));
    }
  }
  fail(ctx, path, `did not match ${label}: ${errors.slice(0, 3).join("; ")}`);
}

function validateNumberConstraints(schema: JsonSchema, value: number, ctx: ValidationContext, path: string): void {
  const minimum = numberConstraint(schema, "minimum");
  if (typeof minimum === "number" && value < minimum) {
    fail(ctx, path, `expected number >= ${minimum}`);
  }
  const maximum = numberConstraint(schema, "maximum");
  if (typeof maximum === "number" && value > maximum) {
    fail(ctx, path, `expected number <= ${maximum}`);
  }
  const exclusiveMinimum = numberConstraint(schema, "exclusiveMinimum");
  if (typeof exclusiveMinimum === "number" && value <= exclusiveMinimum) {
    fail(ctx, path, `expected number > ${exclusiveMinimum}`);
  }
  const exclusiveMaximum = numberConstraint(schema, "exclusiveMaximum");
  if (typeof exclusiveMaximum === "number" && value >= exclusiveMaximum) {
    fail(ctx, path, `expected number < ${exclusiveMaximum}`);
  }
  const multipleOf = numberConstraint(schema, "multipleOf");
  if (typeof multipleOf === "number" && multipleOf !== 0 && value / multipleOf % 1 !== 0) {
    fail(ctx, path, `expected multiple of ${multipleOf}`);
  }
}

function validateStringConstraints(schema: JsonSchema, value: string, ctx: ValidationContext, path: string): void {
  const minLength = numberConstraint(schema, "minLength");
  if (typeof minLength === "number" && value.length < minLength) {
    fail(ctx, path, `expected string length >= ${minLength}`);
  }
  const maxLength = numberConstraint(schema, "maxLength");
  if (typeof maxLength === "number" && value.length > maxLength) {
    fail(ctx, path, `expected string length <= ${maxLength}`);
  }
  if (typeof schema.pattern === "string" && !new RegExp(schema.pattern).test(value)) {
    fail(ctx, path, `expected string matching pattern ${schema.pattern}`);
  }
}

function validateArrayConstraints(schema: JsonSchema, value: unknown[], ctx: ValidationContext, path: string): void {
  const minItems = numberConstraint(schema, "minItems");
  if (typeof minItems === "number" && value.length < minItems) {
    fail(ctx, path, `expected array length >= ${minItems}`);
  }
  const maxItems = numberConstraint(schema, "maxItems");
  if (typeof maxItems === "number" && value.length > maxItems) {
    fail(ctx, path, `expected array length <= ${maxItems}`);
  }
}

function validateObject(schema: JsonSchema, value: unknown, ctx: ValidationContext, path: string): void {
  if (!isObject(value)) {
    fail(ctx, path, "expected object");
  }

  const minProperties = numberConstraint(schema, "minProperties");
  if (typeof minProperties === "number" && Object.keys(value).length < minProperties) {
    fail(ctx, path, `expected object property count >= ${minProperties}`);
  }
  const maxProperties = numberConstraint(schema, "maxProperties");
  if (typeof maxProperties === "number" && Object.keys(value).length > maxProperties) {
    fail(ctx, path, `expected object property count <= ${maxProperties}`);
  }

  const required = Array.isArray(schema.required) ? schema.required.filter((item) => typeof item === "string") : [];
  for (const key of required) {
    if (!Object.prototype.hasOwnProperty.call(value, key)) {
      fail(ctx, `${path}.${key}`, "missing required property");
    }
  }

  const properties = schema.properties;
  if (isObject(properties)) {
    for (const [key, propertySchema] of Object.entries(properties)) {
      if (Object.prototype.hasOwnProperty.call(value, key)) {
        validateSchema(propertySchema, value[key], ctx, `${path}.${key}`);
      }
    }
  }

  if (schema.additionalProperties === false && isObject(properties)) {
    for (const key of Object.keys(value)) {
      if (!Object.prototype.hasOwnProperty.call(properties, key)) {
        fail(ctx, `${path}.${key}`, "unexpected property");
      }
    }
  }
}

export function validateProtocolModel<T>(schemaName: string, value: unknown): T {
  const schema = getProtocolModelSchema(schemaName);
  validateSchema(schema, value, { schemaName, root: schema, semanticName: schemaName.split(".").at(-1) }, "$");
  return value as T;
}

export function validateProtocolRequest<T>(schemaName: string, value: T): T {
  const schema = getProtocolModelSchema(schemaName);
  validateSchema(schema, value, { schemaName, root: schema, semanticName: schemaName.split(".").at(-1) }, "$");
  return value;
}

export function validateProtocolTypeAdapter<T>(schemaName: string, value: unknown): T {
  const schema = getProtocolTypeAdapterSchema(schemaName);
  validateSchema(schema, value, { schemaName, root: schema, semanticName: schemaName.split(".").at(-1) }, "$");
  return value as T;
}

function runSemanticRules(value: unknown, ctx: ValidationContext, path: string): void {
  if (!isObject(value)) {
    return;
  }

  switch (ctx.semanticName) {
    case "CredentialScope":
      validateCredentialScope(value, ctx, path);
      return;
    case "MCPServerConfig":
      validateMcpServerConfig(value, ctx, path);
      return;
    case "SpawnAgentArgs":
      validateSpawnAgentArgs(value, ctx, path);
      return;
    case "SendInputArgs":
      validateSendInputArgs(value, ctx, path);
      return;
    case "ToolContext":
      validateToolContext(value, ctx, path);
      return;
    default:
      return;
  }
}

function validateCredentialScope(value: Record<string, unknown>, ctx: ValidationContext, path: string): void {
  if (value.level === "agent" && typeof value.agent_id !== "string") {
    fail(ctx, `${path}.agent_id`, "agent_id is required when scope.level=agent");
  }
  if (value.level !== "agent" && typeof value.agent_id !== "undefined" && value.agent_id !== null) {
    fail(ctx, `${path}.agent_id`, "agent_id must be null unless scope.level=agent");
  }
}

function validateMcpServerConfig(value: Record<string, unknown>, ctx: ValidationContext, path: string): void {
  const hasUrl = typeof value.url === "string" && value.url.trim().length > 0;
  const hasCommand = typeof value.command === "string" && value.command.trim().length > 0;
  if (hasUrl && hasCommand) {
    fail(ctx, path, "mcp server config cannot define both url and command");
  }
  if (!hasUrl && !hasCommand) {
    fail(ctx, path, "mcp server config must define either url or command");
  }
  if (hasCommand && (value.transport === "sse" || value.transport === "streamable_http")) {
    fail(ctx, `${path}.transport`, "mcp server transport with command source must be stdio");
  }
  if (hasUrl && value.transport === "stdio") {
    fail(ctx, `${path}.transport`, "mcp server transport with url source cannot be stdio");
  }
}

function validateSpawnAgentArgs(value: Record<string, unknown>, ctx: ValidationContext, path: string): void {
  const agentId = typeof value.agent_id === "string" && value.agent_id.trim() ? value.agent_id.trim() : null;
  const agentType = typeof value.agent_type === "string" && value.agent_type.trim() ? value.agent_type.trim() : null;
  if (!agentId && !agentType) {
    fail(ctx, `${path}.agent_id`, "spawn_agent requires agent_id");
  }
  if (agentId && agentType && agentId !== agentType) {
    fail(ctx, `${path}.agent_type`, "agent_type must match agent_id when both are present");
  }
}

function validateSendInputArgs(value: Record<string, unknown>, ctx: ValidationContext, path: string): void {
  const hasMessage = typeof value.message === "string" && value.message.trim().length > 0;
  const hasItems = Array.isArray(value.items) && value.items.length > 0;
  if (!hasMessage && !hasItems) {
    fail(ctx, path, "send_input requires message or items");
  }
}

function validateToolContext(value: Record<string, unknown>, ctx: ValidationContext, path: string): void {
  const forbiddenPath = findPlaintextSecretPath(value, "$");
  if (forbiddenPath) {
    fail(ctx, forbiddenPath, "tool context must reference credentials via auth_ref, not plaintext secret field");
  }
}

const PLAINTEXT_SECRET_KEYS = new Set([
  "api_key",
  "apikey",
  "authorization",
  "bearer_token",
  "credential_value",
  "password",
  "refresh_token",
  "secret",
  "token",
]);
const PLAINTEXT_SECRET_SUFFIXES = ["_api_key", "_apikey", "_password", "_refresh_token", "_secret", "_token"];

function findPlaintextSecretPath(value: unknown, path: string): string | null {
  if (Array.isArray(value)) {
    for (const [index, item] of value.entries()) {
      const found = findPlaintextSecretPath(item, `${path}[${index}]`);
      if (found) {
        return found;
      }
    }
    return null;
  }
  if (!isObject(value)) {
    return null;
  }
  for (const [key, item] of Object.entries(value)) {
    const currentPath = `${path}.${key}`;
    const normalized = key.toLowerCase().replace(/-/g, "_");
    if (normalized === "auth_ref" || normalized === "credential_id") {
      continue;
    }
    if (PLAINTEXT_SECRET_KEYS.has(normalized) || PLAINTEXT_SECRET_SUFFIXES.some((suffix) => normalized.endsWith(suffix))) {
      return currentPath;
    }
    const found = findPlaintextSecretPath(item, currentPath);
    if (found) {
      return found;
    }
  }
  return null;
}
