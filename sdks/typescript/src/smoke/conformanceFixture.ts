import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { AnyAgentSchemaValidationError, validateProtocolRequest, validateProtocolTypeAdapter } from "../index.js";

export interface FixtureCase {
  name: string;
  schema?: string;
  payload: unknown;
  error_path?: string;
  pydantic_error_path?: string;
}

export interface MinimumMatrixOperation {
  name: string;
  kind: "protocol_model" | "openai_response" | "sse_stream" | "type_adapter" | "request_negative" | "type_adapter_negative";
  fixture: string;
  protocol_version: string;
}

export interface SdkMinimumMatrix {
  schema_version: string;
  operations: MinimumMatrixOperation[];
}

export interface SdkConformanceFixture {
  schema_version: string;
  openai_response_cases: FixtureCase[];
  cases: FixtureCase[];
  type_adapter_cases: FixtureCase[];
  type_adapter_negative_cases: FixtureCase[];
  response_stream_sse_blocks: string[];
  request_negative_cases: FixtureCase[];
}

export function loadSdkConformanceFixture(): SdkConformanceFixture {
  const fixturePath = resolve(process.cwd(), "../../tests/fixtures/sdk_conformance/core_surface.json");
  return JSON.parse(readFileSync(fixturePath, "utf-8")) as SdkConformanceFixture;
}

export function loadSdkMinimumMatrix(): SdkMinimumMatrix {
  const matrixPath = resolve(process.cwd(), "../../tests/fixtures/sdk_conformance/minimum_matrix.json");
  return JSON.parse(readFileSync(matrixPath, "utf-8")) as SdkMinimumMatrix;
}

export class SdkConformanceFixtureStore {
  constructor(
    readonly fixture: SdkConformanceFixture = loadSdkConformanceFixture(),
    readonly minimumMatrix: SdkMinimumMatrix = loadSdkMinimumMatrix(),
  ) {}

  payload<T = unknown>(name: string): T {
    const found = this.fixture.cases.find((item) => item.name === name);
    if (!found) {
      throw new Error(`Missing SDK conformance fixture case: ${name}`);
    }
    return structuredClone(found.payload) as T;
  }

  openAIResponsePayload<T = unknown>(name: string): T {
    const found = this.fixture.openai_response_cases.find((item) => item.name === name);
    if (!found) {
      throw new Error(`Missing SDK conformance OpenAI response fixture case: ${name}`);
    }
    return structuredClone(found.payload) as T;
  }

  negativePayload<T = unknown>(name: string): T {
    return structuredClone(this.negativeCase(name).payload) as T;
  }

  negativeCase(name: string): FixtureCase {
    const found = this.fixture.request_negative_cases.find((item) => item.name === name);
    if (!found) {
      throw new Error(`Missing SDK conformance negative fixture case: ${name}`);
    }
    return found;
  }

  typeAdapterPayload<T = unknown>(name: string): T {
    const found = this.fixture.type_adapter_cases.find((item) => item.name === name);
    if (!found) {
      throw new Error(`Missing SDK conformance type adapter fixture case: ${name}`);
    }
    return structuredClone(found.payload) as T;
  }

  assertTypeAdapterCases(names: string[]): void {
    for (const name of names) {
      const found = this.fixture.type_adapter_cases.find((item) => item.name === name);
      if (!found) {
        throw new Error(`Missing SDK conformance type adapter fixture case: ${name}`);
      }
      if (!found.schema) {
        throw new Error(`Missing type adapter schema for SDK conformance fixture case: ${name}`);
      }
      validateProtocolTypeAdapter(found.schema, structuredClone(found.payload));
    }
  }

  assertTypeAdapterNegativeCases(names: string[]): void {
    for (const name of names) {
      const found = this.fixture.type_adapter_negative_cases.find((item) => item.name === name);
      if (!found) {
        throw new Error(`Missing SDK conformance type adapter negative fixture case: ${name}`);
      }
      let failed = false;
      try {
        if (!found.schema) {
          throw new Error(`Missing type adapter schema for SDK conformance negative fixture case: ${name}`);
        }
        validateProtocolTypeAdapter(found.schema, structuredClone(found.payload));
      } catch (error) {
        const expectedPath = found.error_path ? `$.${found.error_path}` : "$";
        failed = error instanceof AnyAgentSchemaValidationError && error.message.includes(expectedPath);
      }
      if (!failed) {
        throw new Error(`validateProtocolTypeAdapter should reject ${name}`);
      }
    }
  }

  assertRequestNegativeCases(names: string[]): void {
    for (const name of names) {
      const found = this.negativeCase(name);
      let failed = false;
      try {
        if (!found.schema) {
          throw new Error(`Missing request schema for SDK conformance negative fixture case: ${name}`);
        }
        validateProtocolRequest(found.schema, structuredClone(found.payload));
      } catch (error) {
        const expectedPath = found.error_path ? `$.${found.error_path}` : "$";
        failed = error instanceof AnyAgentSchemaValidationError && error.message.includes(expectedPath);
      }
      if (!failed) {
        throw new Error(`validateProtocolRequest should reject ${name}`);
      }
    }
  }

  assertMinimumMatrixReferences(): void {
    if (this.minimumMatrix.schema_version !== this.fixture.schema_version) {
      throw new Error("SDK minimum matrix schema_version must match conformance fixture schema_version");
    }

    const operations = new Set<string>();
    const protocolCases = new Set(this.fixture.cases.map((item) => item.name));
    const openaiCases = new Set(this.fixture.openai_response_cases.map((item) => item.name));
    const typeAdapterCases = new Set(this.fixture.type_adapter_cases.map((item) => item.name));
    const requestNegativeCases = new Set(this.fixture.request_negative_cases.map((item) => item.name));
    const typeAdapterNegativeCases = new Set(this.fixture.type_adapter_negative_cases.map((item) => item.name));

    for (const operation of this.minimumMatrix.operations) {
      if (operations.has(operation.name)) {
        throw new Error(`Duplicate SDK minimum matrix operation: ${operation.name}`);
      }
      if (!operation.protocol_version) {
        throw new Error(`SDK minimum matrix operation missing protocol_version: ${operation.name}`);
      }
      operations.add(operation.name);
      if (operation.kind === "protocol_model" && !protocolCases.has(operation.fixture)) {
        throw new Error(`SDK minimum matrix references missing protocol fixture: ${operation.fixture}`);
      }
      if (operation.kind === "openai_response" && !openaiCases.has(operation.fixture)) {
        throw new Error(`SDK minimum matrix references missing OpenAI response fixture: ${operation.fixture}`);
      }
      if (operation.kind === "sse_stream" && operation.fixture !== "response_stream_sse_blocks") {
        throw new Error(`SDK minimum matrix references unknown SSE fixture: ${operation.fixture}`);
      }
      if (operation.kind === "type_adapter" && !typeAdapterCases.has(operation.fixture)) {
        throw new Error(`SDK minimum matrix references missing type adapter fixture: ${operation.fixture}`);
      }
      if (operation.kind === "request_negative" && !requestNegativeCases.has(operation.fixture)) {
        throw new Error(`SDK minimum matrix references missing request negative fixture: ${operation.fixture}`);
      }
      if (operation.kind === "type_adapter_negative" && !typeAdapterNegativeCases.has(operation.fixture)) {
        throw new Error(`SDK minimum matrix references missing type adapter negative fixture: ${operation.fixture}`);
      }
    }

    for (const required of [
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
      "admin.credentials.set",
      "admin.credentials.delete",
      "admin.workspace.agent.create",
      "admin.workspace.agent.file.update",
      "admin.skill.import",
      "admin.skill.install",
      "admin.skill.update.apply",
      "admin.agent.skills.update",
      "admin.agent.config.update",
    ]) {
      if (!operations.has(required)) {
        throw new Error(`SDK minimum matrix missing required operation: ${required}`);
      }
    }
  }
}
