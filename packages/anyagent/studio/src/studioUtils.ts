import { AgentFileKind, AgentWorkspaceFile, ObservabilityTimelineEvent, StudioDebugEvent } from "./anyagentClient";

export const compactJson = (value: unknown) => JSON.stringify(value, null, 2);

export const shortHash = (value?: string) => (value ? value.slice(0, 12) : "none");

export const csvToList = (value: string) =>
  value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);

export const fileLabels: Record<AgentFileKind, string> = {
  agents_md: "AGENTS.md",
  agent_yaml: "agent.yaml",
  mcp_json: "mcp.json",
};

export function displayText(value: unknown, fallback = "unknown"): string {
  if (typeof value === "string" && value.trim()) {
    return value;
  }
  if (value && typeof value === "object") {
    const candidate = value as { display_name?: unknown; name?: unknown; stable_id?: unknown; short_description?: unknown };
    for (const item of [candidate.display_name, candidate.name, candidate.stable_id, candidate.short_description]) {
      if (typeof item === "string" && item.trim()) {
        return item;
      }
    }
    return JSON.stringify(value);
  }
  return fallback;
}

export function eventSummary(event: StudioDebugEvent): { title: string; detail: string; meta: string } {
  const payload = event as Record<string, unknown>;
  const type = typeof payload.type === "string" ? payload.type : "event";
  const seq = typeof payload.seq === "number" ? `#${payload.seq}` : "";
  if (type === "anyagent.tool.planned") {
    return {
      title: `Tool planned: ${displayText(payload.tool_name, "tool")}`,
      detail: compactJson(payload.arguments ?? {}),
      meta: seq,
    };
  }
  if (type === "anyagent.tool.result") {
    return {
      title: `Tool result: ${displayText(payload.tool_name, "tool")}`,
      detail: compactJson({ status: payload.status, output: payload.output, error: payload.error }),
      meta: seq,
    };
  }
  if (type === "anyagent.command.planned") {
    return {
      title: "Command planned",
      detail: compactJson({ command: payload.command, workdir: payload.workdir, timeout_ms: payload.timeout_ms }),
      meta: seq,
    };
  }
  if (type === "anyagent.command.result") {
    return {
      title: "Command result",
      detail: compactJson({ exit_code: payload.exit_code, stdout: payload.stdout, stderr: payload.stderr }),
      meta: seq,
    };
  }
  if (type === "anyagent.prompt.context") {
    return {
      title: "Prompt context assembled",
      detail: compactJson({
        fragments: payload.fragment_kinds,
        selected_skill_ids: payload.selected_skill_ids,
        prompt_cache_key: payload.prompt_cache_key,
      }),
      meta: seq,
    };
  }
  if (type === "anyagent.done") {
    return { title: "Run completed", detail: "Done", meta: seq };
  }
  return { title: type, detail: compactJson(event), meta: seq };
}

export function numericValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function eventType(event: StudioDebugEvent): string {
  const payload = event as Record<string, unknown>;
  return typeof payload.type === "string" ? payload.type : "event";
}

export function firstNumber(payload: Record<string, unknown>, keys: string[]): number | null {
  for (const key of keys) {
    const direct = numericValue(payload[key]);
    if (direct !== null) {
      return direct;
    }
    const segments = key.split(".");
    let cursor: unknown = payload;
    for (const segment of segments) {
      cursor = cursor && typeof cursor === "object" ? (cursor as Record<string, unknown>)[segment] : undefined;
    }
    const nested = numericValue(cursor);
    if (nested !== null) {
      return nested;
    }
  }
  return null;
}

export function formatCount(value: number): string {
  return Number.isFinite(value) ? value.toLocaleString() : "-";
}

export function formatMs(value: number | null): string {
  return value === null ? "-" : `${Math.round(value)} ms`;
}

export function timelineMeta(event: ObservabilityTimelineEvent): string {
  return [event.source, event.status, event.tool_name, event.trace_id ? `trace ${event.trace_id}` : ""].filter(Boolean).join(" · ");
}

export function fileByKind(files: AgentWorkspaceFile[], kind: AgentFileKind): AgentWorkspaceFile | undefined {
  return files.find((file) => file.kind === kind);
}
