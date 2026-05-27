import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";

import { protocolSchemaBundle, type JsonSchema } from "./schemaBundle.js";

const CORE_ADAPTER_NAMES = [
  "anyagent.protocol.stage_events.StageEvent",
  "anyagent.protocol.tool_runtime.ExecuteResponse",
] as const;

function shortName(qualifiedName: string): string {
  const value = qualifiedName.split(".").at(-1);
  if (!value) {
    throw new Error(`Invalid qualified schema name: ${qualifiedName}`);
  }
  return value;
}

function refName(ref: string): string {
  const value = decodeURIComponent(ref.split("/").at(-1) ?? "");
  if (!value) {
    return "unknown";
  }
  return value.replace(/[^A-Za-z0-9_$]/g, "_");
}

function literalType(value: unknown): string {
  if (value === null) {
    return "null";
  }
  if (typeof value === "string") {
    return JSON.stringify(value);
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return JSON.stringify(value);
  }
  return "unknown";
}

function schemaToType(schema: unknown): string {
  if (!schema || typeof schema !== "object" || Array.isArray(schema)) {
    return "unknown";
  }
  const obj = schema as JsonSchema;

  if (typeof obj.const !== "undefined") {
    return literalType(obj.const);
  }
  if (typeof obj.$ref === "string") {
    return refName(obj.$ref);
  }
  if (Array.isArray(obj.enum)) {
    return obj.enum.map(literalType).join(" | ") || "unknown";
  }
  if (Array.isArray(obj.anyOf)) {
    return obj.anyOf.map(schemaToType).join(" | ") || "unknown";
  }
  if (Array.isArray(obj.oneOf)) {
    return obj.oneOf.map(schemaToType).join(" | ") || "unknown";
  }
  if (Array.isArray(obj.allOf)) {
    return obj.allOf.map(schemaToType).join(" & ") || "unknown";
  }

  switch (obj.type) {
    case "string":
      return "string";
    case "integer":
    case "number":
      return "number";
    case "boolean":
      return "boolean";
    case "null":
      return "null";
    case "array": {
      const itemType = schemaToType(obj.items);
      return `Array<${itemType}>`;
    }
    case "object":
      return objectSchemaToType(obj);
    default:
      if (obj.properties && typeof obj.properties === "object") {
        return objectSchemaToType(obj);
      }
      return "unknown";
  }
}

function objectSchemaToType(schema: JsonSchema): string {
  const properties = schema.properties;
  if (!properties || typeof properties !== "object" || Array.isArray(properties)) {
    if (schema.additionalProperties && typeof schema.additionalProperties === "object") {
      return `Record<string, ${schemaToType(schema.additionalProperties)}>`;
    }
    return "Record<string, unknown>";
  }

  const required = new Set(Array.isArray(schema.required) ? schema.required.filter((item) => typeof item === "string") : []);
  const fields = Object.entries(properties as Record<string, unknown>).map(([key, value]) => {
    const optional = required.has(key) ? "" : "?";
    return `  ${JSON.stringify(key)}${optional}: ${schemaToType(value)};`;
  });
  return `{\n${fields.join("\n")}\n}`;
}

function emitTypeAlias(exportName: string, schema: JsonSchema): string {
  return `export type ${exportName} = ${schemaToType(schema)};\n`;
}

function collectDefinitions(schema: unknown, out: Map<string, JsonSchema>): void {
  if (!schema || typeof schema !== "object" || Array.isArray(schema)) {
    return;
  }
  const obj = schema as JsonSchema;
  const defs = obj.$defs;
  if (defs && typeof defs === "object" && !Array.isArray(defs)) {
    for (const [name, definition] of Object.entries(defs as Record<string, unknown>)) {
      if (definition && typeof definition === "object" && !Array.isArray(definition)) {
        out.set(refName(name), definition as JsonSchema);
      }
    }
  }
}

export function generateProtocolTypes(): string {
  const chunks: string[] = [
    "/* eslint-disable */",
    "// Generated from anyagent.protocol schema bundle. Do not edit by hand.",
    `// schema_version: ${protocolSchemaBundle.schema_version}`,
    "",
  ];

  const reservedNames = new Set<string>();
  for (const name of Object.keys(protocolSchemaBundle.models)) {
    reservedNames.add(shortName(name));
  }
  for (const name of CORE_ADAPTER_NAMES) {
    reservedNames.add(shortName(name));
  }

  const definitions = new Map<string, JsonSchema>();
  for (const schema of Object.values(protocolSchemaBundle.models)) {
    collectDefinitions(schema, definitions);
  }
  for (const schema of Object.values(protocolSchemaBundle.type_adapters)) {
    collectDefinitions(schema, definitions);
  }
  for (const [name, schema] of [...definitions.entries()].sort(([left], [right]) => left.localeCompare(right))) {
    if (!reservedNames.has(name)) {
      chunks.push(emitTypeAlias(name, schema));
    }
  }

  for (const [name, schema] of Object.entries(protocolSchemaBundle.models).sort(([left], [right]) => left.localeCompare(right))) {
    if (!schema) {
      throw new Error(`Missing protocol model schema: ${name}`);
    }
    chunks.push(emitTypeAlias(shortName(name), schema));
  }

  for (const name of CORE_ADAPTER_NAMES) {
    const schema = protocolSchemaBundle.type_adapters[name];
    if (!schema) {
      throw new Error(`Missing protocol type adapter schema: ${name}`);
    }
    chunks.push(emitTypeAlias(shortName(name), schema));
  }

  return chunks.join("\n");
}

export function writeProtocolTypes(outPath = "generated/protocol-types.ts"): void {
  const resolved = resolve(outPath);
  mkdirSync(dirname(resolved), { recursive: true });
  writeFileSync(resolved, generateProtocolTypes(), "utf-8");
}

if (import.meta.url === `file://${process.argv[1]}`) {
  writeProtocolTypes(process.argv[2]);
}
