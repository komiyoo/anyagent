import { useEffect, useMemo, useState } from "react";
import {
  ChatMessage,
  ModelRequestResponse,
  ObservabilityErrorItem,
  ObservabilityMetrics,
  ObservabilityRunItem,
  ObservabilitySource,
  ObservabilitySummary,
  ObservabilityTimelineEvent,
  ObservabilityToolStats,
  ObservabilityTrace,
  PromptContextResponse,
  StudioDebugEvent,
  StudioSettings,
  ToolExecutionDetail,
  listEvents,
  loadModelRequest,
  loadObservabilityErrors,
  loadObservabilityMetrics,
  loadObservabilityRuns,
  loadObservabilitySummary,
  loadObservabilityTimeline,
  loadObservabilityTools,
  loadObservabilityTrace,
  loadPromptContext,
  loadToolExecutions,
} from "../anyagentClient";
import { StudioTab } from "../navigation";
import { eventType, firstNumber, formatCount, formatMs } from "../studioUtils";

type ObservabilityStatus = "all" | "error" | "warning" | "success" | "denied";
type ActiveObservabilityStatus = Exclude<ObservabilityStatus, "all">;

type UseObservabilityOptions = {
  activeResponseId: string;
  messages: ChatMessage[];
  selectedSkillCount: number;
  setActiveResponseId: (value: string) => void;
  setStageEvents: (value: StudioDebugEvent[] | ((current: StudioDebugEvent[]) => StudioDebugEvent[])) => void;
  stageEvents: StudioDebugEvent[];
  streamEvents: StudioDebugEvent[];
};

export function useObservability(settings: StudioSettings, options: UseObservabilityOptions) {
  const [selectedResponseId, setSelectedResponseId] = useState<string>("");
  const [observabilitySummary, setObservabilitySummary] = useState<ObservabilitySummary | null>(null);
  const [observabilityRuns, setObservabilityRuns] = useState<ObservabilityRunItem[]>([]);
  const [observabilityMetrics, setObservabilityMetrics] = useState<ObservabilityMetrics | null>(null);
  const [observabilityTools, setObservabilityTools] = useState<ObservabilityToolStats[]>([]);
  const [observabilityErrors, setObservabilityErrors] = useState<ObservabilityErrorItem[]>([]);
  const [observabilityTimeline, setObservabilityTimeline] = useState<ObservabilityTimelineEvent[]>([]);
  const [observabilityTrace, setObservabilityTrace] = useState<ObservabilityTrace | null>(null);
  const [observabilityTraceId, setObservabilityTraceId] = useState("");
  const [observabilitySources, setObservabilitySources] = useState<ObservabilitySource[]>([]);
  const [observabilityStatuses, setObservabilityStatuses] = useState<ActiveObservabilityStatus[]>([]);
  const [observabilityToolFilter, setObservabilityToolFilter] = useState("");
  const [observabilityRefreshNonce, setObservabilityRefreshNonce] = useState(0);
  const [observabilityWindow, setObservabilityWindow] = useState<"all" | "hour" | "day">("all");
  const [observabilityLimit, setObservabilityLimit] = useState(20);
  const [replayToolExecutions, setReplayToolExecutions] = useState<ToolExecutionDetail[]>([]);
  const [replayModelRequest, setReplayModelRequest] = useState<ModelRequestResponse | null>(null);
  const [replayPromptContext, setReplayPromptContext] = useState<PromptContextResponse | null>(null);
  const allDebugEvents = useMemo(() => [...options.streamEvents, ...options.stageEvents], [options.streamEvents, options.stageEvents]);

  const localObservability = useMemo(() => {
    const userTurns = options.messages.filter((message) => message.role === "user");
    const assistantTurns = options.messages.filter((message) => message.role === "assistant" && message.content.trim());
    const eventPayloads = allDebugEvents.map((event) => event as Record<string, unknown>);
    const eventTypes = allDebugEvents.map(eventType);
    const toolCalls = eventTypes.filter((type) => type === "anyagent.tool.planned" || type === "anyagent.tool.result").length;
    const mcpCalls = eventPayloads.filter((payload) => {
      const type = typeof payload.type === "string" ? payload.type : "";
      const server = typeof payload.server_label === "string" || typeof payload.mcp_server_label === "string";
      return type.includes("mcp") || server;
    }).length;
    const selectedSkillIds = new Set<string>();
    eventPayloads.forEach((payload) => {
      const ids = payload.selected_skill_ids;
      if (Array.isArray(ids)) {
        ids.forEach((id) => {
          if (typeof id === "string" && id.trim()) {
            selectedSkillIds.add(id);
          }
        });
      }
    });
    const inputChars = userTurns.reduce((total, message) => total + message.content.length, 0);
    const outputChars = assistantTurns.reduce((total, message) => total + message.content.length, 0);
    const inputTokens = eventPayloads.reduce(
      (total, payload) => total + (firstNumber(payload, ["usage.input_tokens", "usage.prompt_tokens", "input_tokens"]) ?? 0),
      0,
    );
    const outputTokens = eventPayloads.reduce(
      (total, payload) => total + (firstNumber(payload, ["usage.output_tokens", "usage.completion_tokens", "output_tokens"]) ?? 0),
      0,
    );
    const cachedTokens = eventPayloads.reduce(
      (total, payload) =>
        total + (firstNumber(payload, ["usage.input_tokens_details.cached_tokens", "usage.prompt_tokens_details.cached_tokens", "cached_tokens"]) ?? 0),
      0,
    );
    const firstTokenLatency = eventPayloads
      .map((payload) => firstNumber(payload, ["first_token_ms", "latency.first_token_ms", "ttft_ms"]))
      .find((value): value is number => value !== null) ?? null;
    const totalLatency = eventPayloads
      .map((payload) => firstNumber(payload, ["total_latency_ms", "latency.total_ms", "duration_ms", "elapsed_ms"]))
      .filter((value): value is number => value !== null)
      .at(-1) ?? null;
    return {
      runCount: options.activeResponseId ? 1 : 0,
      turnCount: userTurns.length,
      eventCount: allDebugEvents.length,
      toolCalls,
      mcpCalls,
      skillViews: selectedSkillIds.size || options.selectedSkillCount,
      inputChars,
      outputChars,
      avgInputChars: userTurns.length ? Math.round(inputChars / userTurns.length) : 0,
      avgOutputChars: assistantTurns.length ? Math.round(outputChars / assistantTurns.length) : 0,
      inputTokens,
      outputTokens,
      cachedTokens,
      firstTokenLatency,
      totalLatency,
    };
  }, [allDebugEvents, options.activeResponseId, options.messages, options.selectedSkillCount]);

  const displayObservability = useMemo(() => {
    if (!observabilitySummary) {
      return localObservability;
    }
    return {
      ...localObservability,
      runCount: observabilityMetrics?.run_count ?? (observabilitySummary.response_id ? 1 : localObservability.runCount),
      turnCount: observabilitySummary.turn_count ?? localObservability.turnCount,
      eventCount: observabilityMetrics?.event_count ?? observabilitySummary.event_count ?? localObservability.eventCount,
      toolCalls: observabilityMetrics?.tool_call_count ?? observabilitySummary.tool_call_count ?? localObservability.toolCalls,
      mcpCalls: observabilityMetrics?.mcp_call_count ?? observabilitySummary.mcp_call_count ?? localObservability.mcpCalls,
      skillViews: observabilitySummary.skill_view_count ?? localObservability.skillViews,
      inputChars: observabilitySummary.input_chars ?? localObservability.inputChars,
      outputChars: observabilitySummary.output_chars ?? localObservability.outputChars,
      inputTokens: observabilityMetrics?.input_tokens ?? observabilitySummary.input_tokens ?? localObservability.inputTokens,
      outputTokens: observabilityMetrics?.output_tokens ?? observabilitySummary.output_tokens ?? localObservability.outputTokens,
      cachedTokens: observabilityMetrics?.cached_input_tokens ?? observabilitySummary.cached_input_tokens ?? localObservability.cachedTokens,
      firstTokenLatency: observabilityMetrics?.first_token_latency_ms ?? observabilitySummary.first_token_latency_ms ?? localObservability.firstTokenLatency,
      totalLatency: observabilityMetrics?.max_response_latency_ms ?? observabilitySummary.total_response_latency_ms ?? localObservability.totalLatency,
    };
  }, [localObservability, observabilityMetrics, observabilitySummary]);

  const selectedRun = useMemo(
    () => observabilityRuns.find((run) => run.response_id === selectedResponseId) ?? observabilityRuns[0] ?? null,
    [selectedResponseId, observabilityRuns],
  );
  const filteredObservabilityTools = useMemo(() => {
    const needle = observabilityToolFilter.trim().toLowerCase();
    return needle ? observabilityTools.filter((tool) => tool.tool_name.toLowerCase().includes(needle)) : observabilityTools;
  }, [observabilityToolFilter, observabilityTools]);
  const filteredObservabilityErrors = useMemo(() => {
    const needle = observabilityToolFilter.trim().toLowerCase();
    return observabilityErrors.filter((error) => {
      if (observabilitySources.length && !observabilitySources.includes(error.source)) return false;
      if (observabilityStatuses.length && !observabilityStatuses.some((item) => error.status === item || error.payload?.status === item)) return false;
      if (!needle) return true;
      return [error.tool_name, error.type, error.message, error.trace_id].some((value) => String(value ?? "").toLowerCase().includes(needle));
    });
  }, [observabilityErrors, observabilitySources, observabilityStatuses, observabilityToolFilter]);
  const filteredObservabilityTimeline = useMemo(() => {
    const needle = observabilityToolFilter.trim().toLowerCase();
    return observabilityTimeline.filter((event) => {
      if (observabilitySources.length && !observabilitySources.includes(event.source)) return false;
      if (observabilityStatuses.length && !observabilityStatuses.some((item) => event.status === item || event.level === item)) return false;
      if (!needle) return true;
      return [event.tool_name, event.type, event.message, event.trace_id, event.audit_ref].some((value) =>
        String(value ?? "").toLowerCase().includes(needle),
      );
    });
  }, [observabilitySources, observabilityStatuses, observabilityTimeline, observabilityToolFilter]);

  const iterationSuggestions = useMemo(() => {
    const suggestions: Array<{ title: string; detail: string; target: StudioTab }> = [];
    if (displayObservability.totalLatency !== null && displayObservability.totalLatency > 3000) {
      suggestions.push({
        title: "Review latency",
        detail: `Total response time is ${formatMs(displayObservability.totalLatency)} for the selected run.`,
        target: "debug",
      });
    }
    if (displayObservability.inputTokens + displayObservability.outputTokens > 6000) {
      suggestions.push({
        title: "Trim prompt context",
        detail: `${formatCount(displayObservability.inputTokens + displayObservability.outputTokens)} tokens were used.`,
        target: "files",
      });
    }
    if (displayObservability.toolCalls > 4 || displayObservability.mcpCalls > 2) {
      suggestions.push({
        title: "Inspect tool routing",
        detail: `${formatCount(displayObservability.toolCalls + displayObservability.mcpCalls)} tool/MCP calls were observed.`,
        target: "tools",
      });
    }
    if (displayObservability.skillViews > Math.max(3, options.selectedSkillCount)) {
      suggestions.push({
        title: "Prune skill disclosure",
        detail: `${formatCount(displayObservability.skillViews)} skills were disclosed or selected.`,
        target: "skills",
      });
    }
    if (displayObservability.avgInputChars > 2000 || displayObservability.avgOutputChars > 4000) {
      suggestions.push({
        title: "Check turn length",
        detail: `Average turn length is ${formatCount(displayObservability.avgInputChars)} input chars and ${formatCount(displayObservability.avgOutputChars)} output chars.`,
        target: "observability",
      });
    }
    return suggestions.length
      ? suggestions
      : [{ title: "No optimization flags", detail: "Selected run metrics are within the current thresholds.", target: "observability" as StudioTab }];
  }, [displayObservability, options.selectedSkillCount]);

  async function selectObservabilityRun(responseId: string) {
    setSelectedResponseId(responseId);
    options.setActiveResponseId(responseId);
    options.setStageEvents([]);
    setObservabilitySummary(null);
    setObservabilityTimeline([]);
    setReplayToolExecutions([]);
    setReplayModelRequest(null);
    setReplayPromptContext(null);
    try {
      const [summary, replay, timeline, toolExecs, promptCtx] = await Promise.all([
        loadObservabilitySummary(settings, responseId),
        listEvents(settings, responseId),
        loadObservabilityTimeline(settings, { responseId, limit: 200 }),
        loadToolExecutions(settings, responseId).catch(() => ({ response_id: responseId, tool_executions: [] })),
        loadPromptContext(settings, responseId).catch(() => ({ response_id: responseId })),
      ]);
      setObservabilitySummary(summary);
      options.setStageEvents(replay);
      setObservabilityTimeline(timeline.events ?? []);
      setReplayToolExecutions(toolExecs.tool_executions ?? []);
      setReplayPromptContext(promptCtx);
    } catch {
      options.setStageEvents([]);
      setObservabilitySummary(null);
      setObservabilityTimeline([]);
      setReplayPromptContext(null);
    }
    try {
      const modelReq = await loadModelRequest(settings, responseId);
      setReplayModelRequest(modelReq);
    } catch {
      setReplayModelRequest(null);
    }
  }

  async function inspectObservabilityTrace(traceId: string) {
    const normalized = traceId.trim();
    if (!normalized) {
      setObservabilityTrace(null);
      return;
    }
    setObservabilityTraceId(normalized);
    try {
      const trace = await loadObservabilityTrace(settings, normalized, 500);
      setObservabilityTrace(trace);
      setObservabilityTimeline(trace?.events ?? []);
    } catch {
      setObservabilityTrace(null);
    }
  }

  useEffect(() => {
    const now = Date.now();
    const createdAfterMs =
      observabilityWindow === "hour" ? now - 60 * 60 * 1000 : observabilityWindow === "day" ? now - 24 * 60 * 60 * 1000 : undefined;
    const filters = {
      agentId: settings.agentId,
      sessionKey: settings.sessionKey,
      createdAfterMs,
      limit: observabilityLimit,
    };
    void loadObservabilityRuns(settings, filters)
      .then((payload) => {
        const runs = payload.runs ?? [];
        setObservabilityRuns(runs);
        setSelectedResponseId((current) => current || options.activeResponseId || runs[0]?.response_id || "");
      })
      .catch(() => setObservabilityRuns([]));
    void Promise.all([
      loadObservabilityMetrics(settings, filters),
      loadObservabilityTools(settings, filters),
      loadObservabilityErrors(settings, { ...filters, limit: 50 }),
      loadObservabilityTimeline(settings, { ...filters, limit: 200 }),
    ])
      .then(([metrics, tools, errors, timeline]) => {
        setObservabilityMetrics(metrics);
        setObservabilityTools(tools.tools ?? []);
        setObservabilityErrors(errors.errors ?? []);
        setObservabilityTimeline(timeline.events ?? []);
      })
      .catch(() => {
        setObservabilityMetrics(null);
        setObservabilityTools([]);
        setObservabilityErrors([]);
        setObservabilityTimeline([]);
      });
  }, [
    settings.baseUrl,
    settings.apiKey,
    settings.agentId,
    settings.sessionKey,
    options.activeResponseId,
    observabilityWindow,
    observabilityLimit,
    observabilityRefreshNonce,
  ]);

  useEffect(() => {
    if (!selectedResponseId) {
      setObservabilitySummary(null);
      return;
    }
    void loadObservabilitySummary(settings, selectedResponseId)
      .then((summary) => setObservabilitySummary(summary))
      .catch(() => setObservabilitySummary(null));
    void loadObservabilityTimeline(settings, { responseId: selectedResponseId, limit: 200 })
      .then((timeline) => setObservabilityTimeline(timeline.events ?? []))
      .catch(() => setObservabilityTimeline([]));
  }, [settings.baseUrl, settings.apiKey, selectedResponseId]);

  return {
    displayObservability,
    filteredObservabilityErrors,
    filteredObservabilityTimeline,
    filteredObservabilityTools,
    inspectObservabilityTrace,
    iterationSuggestions,
    observabilityErrors,
    observabilityLimit,
    observabilityMetrics,
    observabilityRefreshNonce,
    observabilityRuns,
    observabilitySources,
    observabilityStatuses,
    observabilitySummary,
    observabilityTimeline,
    observabilityToolFilter,
    observabilityTools,
    observabilityTrace,
    observabilityTraceId,
    observabilityWindow,
    replayModelRequest,
    replayPromptContext,
    replayToolExecutions,
    selectedResponseId,
    selectedRun,
    selectObservabilityRun,
    setObservabilityLimit,
    setObservabilityRefreshNonce,
    setObservabilitySources,
    setObservabilityStatuses,
    setObservabilityToolFilter,
    setObservabilityTraceId,
    setObservabilityWindow,
    setSelectedResponseId,
  };
}
