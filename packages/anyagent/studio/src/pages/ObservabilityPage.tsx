import { Button, Card, Chip, Input, Separator } from "@heroui/react";
import { BarChart3, MessageSquareText, RefreshCw, Timer } from "lucide-react";
import {
  McpServerDraft,
  ObservabilityErrorItem,
  ObservabilityMetrics,
  ObservabilityRunItem,
  ObservabilitySource,
  ObservabilitySummary,
  ObservabilityTimelineEvent,
  ObservabilityToolStats,
  ObservabilityTrace,
  StudioSettings,
} from "../anyagentClient";
import { StudioTab } from "../navigation";
import { compactJson, formatCount, formatMs, timelineMeta } from "../studioUtils";

type DisplayObservability = {
  runCount: number;
  turnCount: number;
  eventCount: number;
  toolCalls: number;
  mcpCalls: number;
  skillViews: number;
  inputChars: number;
  outputChars: number;
  avgInputChars: number;
  avgOutputChars: number;
  inputTokens: number;
  outputTokens: number;
  cachedTokens: number;
  firstTokenLatency: number | null;
  totalLatency: number | null;
};

type IterationSuggestion = {
  title: string;
  detail: string;
  target: StudioTab;
};

type ObservabilityPageProps = {
  settings: StudioSettings;
  selectedResponseId: string;
  selectedRun: ObservabilityRunItem | null;
  summary: ObservabilitySummary | null;
  metrics: ObservabilityMetrics | null;
  runs: ObservabilityRunItem[];
  tools: ObservabilityToolStats[];
  errors: ObservabilityErrorItem[];
  timeline: ObservabilityTimelineEvent[];
  trace: ObservabilityTrace | null;
  traceId: string;
  source: "all" | ObservabilitySource;
  status: "all" | "error" | "warning" | "success" | "denied";
  toolFilter: string;
  window: "all" | "hour" | "day";
  limit: number;
  display: DisplayObservability;
  mcpDrafts: McpServerDraft[];
  selectedSkillCount: number;
  filteredTools: ObservabilityToolStats[];
  filteredErrors: ObservabilityErrorItem[];
  filteredTimeline: ObservabilityTimelineEvent[];
  iterationSuggestions: IterationSuggestion[];
  onWindowChange: (value: "all" | "hour" | "day") => void;
  onLimitChange: (value: number) => void;
  onTraceIdChange: (value: string) => void;
  onSourceChange: (value: "all" | ObservabilitySource) => void;
  onStatusChange: (value: "all" | "error" | "warning" | "success" | "denied") => void;
  onToolFilterChange: (value: string) => void;
  onRefresh: () => void;
  onSelectRun: (responseId: string) => void;
  onInspectTrace: (traceId: string) => void;
  onNavigate: (tab: StudioTab) => void;
};

export function ObservabilityPage({
  settings,
  selectedResponseId,
  selectedRun,
  summary,
  metrics,
  runs,
  tools,
  errors,
  timeline,
  trace,
  traceId,
  source,
  status,
  toolFilter,
  window,
  limit,
  display,
  mcpDrafts,
  selectedSkillCount,
  filteredTools,
  filteredErrors,
  filteredTimeline,
  iterationSuggestions,
  onWindowChange,
  onLimitChange,
  onTraceIdChange,
  onSourceChange,
  onStatusChange,
  onToolFilterChange,
  onRefresh,
  onSelectRun,
  onInspectTrace,
  onNavigate,
}: ObservabilityPageProps) {
  return (
    <>
      <section className="section-block">
        <div className="section-title">
          <BarChart3 size={17} />
          <h2>Observability</h2>
          <span>{settings.agentId || "main"} · current session</span>
        </div>
        <div className="metric-grid">
          <MetricCard label="Runs" value={formatCount(display.runCount)} detail={selectedResponseId || "No response yet"} />
          <MetricCard label="Turns" value={formatCount(display.turnCount)} detail={`${formatCount(display.avgInputChars)} avg input chars`} />
          <MetricCard
            label="Tool Calls"
            value={formatCount(display.toolCalls)}
            detail={`${formatCount(tools.length)} unique tools · ${formatCount(display.eventCount)} events`}
          />
          <MetricCard label="MCP Calls" value={formatCount(display.mcpCalls)} detail={`${mcpDrafts.length} configured draft servers`} />
          <MetricCard label="Skill Views" value={formatCount(display.skillViews)} detail={`${selectedSkillCount} default selected`} />
          <MetricCard
            label="LLM Tokens"
            value={formatCount(display.inputTokens + display.outputTokens)}
            detail={`in ${formatCount(display.inputTokens)} · out ${formatCount(display.outputTokens)} · cache ${formatCount(display.cachedTokens)}`}
          />
          <MetricCard label="First Token" value={formatMs(display.firstTokenLatency)} detail="from streamed/model events when available" />
          <MetricCard
            label="Errors"
            value={formatCount(metrics?.error_count ?? errors.length)}
            detail={`${formatMs(display.totalLatency)} max response`}
          />
          <MetricCard
            label="Avg Response"
            value={formatMs(metrics?.avg_response_latency_ms ?? null)}
            detail={`${formatMs(display.totalLatency)} max response`}
          />
          <MetricCard label="Timeline" value={formatCount(timeline.length)} detail={selectedResponseId || "workspace scope"} />
          <MetricCard label="Total Response" value={formatMs(display.totalLatency)} detail="from streamed/model events when available" />
        </div>
      </section>

      <div className="main-grid observability-grid">
        <Card className="panel">
          <Card.Header className="panel-header">
            <div className="panel-title">
              <MessageSquareText size={18} />
              <span>History</span>
            </div>
            <Chip size="sm" variant="soft" color={runs.length ? "success" : "default"}>
              {runs.length ? `${runs.length} runs` : "empty"}
            </Chip>
          </Card.Header>
          <Card.Content className="panel-content">
            <div className="filter-row">
              <select className="native-select" aria-label="Observability time window" value={window} onChange={(event) => onWindowChange(event.target.value as "all" | "hour" | "day")}>
                <option value="all">All time</option>
                <option value="hour">Last hour</option>
                <option value="day">Last 24 hours</option>
              </select>
              <Input
                aria-label="Run limit"
                type="number"
                min={1}
                max={100}
                value={String(limit)}
                onChange={(event) => onLimitChange(Math.max(1, Math.min(100, Number(event.target.value) || 20)))}
              />
              <Button size="sm" variant="ghost" isIconOnly aria-label="Refresh observability" onPress={onRefresh}>
                <RefreshCw size={16} />
              </Button>
            </div>
            <div className="filter-row">
              <Input aria-label="Trace id" placeholder="trace_id" value={traceId} onChange={(event) => onTraceIdChange(event.target.value)} />
              <Button size="sm" variant="ghost" onPress={() => onInspectTrace(traceId)}>
                Trace
              </Button>
            </div>
            {trace ? (
              <div className="breakdown-list turn-breakdown">
                <div className="breakdown-row">
                  <span>Trace responses</span>
                  <strong>{trace.response_ids.slice(0, 3).join(", ") || "-"}</strong>
                </div>
                <div className="breakdown-row">
                  <span>Audit refs</span>
                  <strong>{formatCount(trace.audit_refs.length)}</strong>
                </div>
              </div>
            ) : null}
            <div className="history-list">
              {runs.length === 0 ? (
                <p className="empty">No run history available for the current agent/session.</p>
              ) : (
                runs.map((run) => (
                  <button
                    className={`history-row ${run.response_id === selectedRun?.response_id ? "active" : ""}`}
                    key={run.response_id}
                    type="button"
                    onClick={() => onSelectRun(run.response_id)}
                  >
                    <div>
                      <strong>{run.response_id}</strong>
                      <span>{run.status} · {run.session_key}</span>
                    </div>
                    <p>
                      {run.stream ? "stream" : "non-stream"} · {run.agent_id}
                    </p>
                    <em>{formatCount(Math.max(run.updated_at_ms - run.created_at_ms, 0))} ms</em>
                  </button>
                ))
              )}
            </div>
          </Card.Content>
        </Card>

        <Card className="panel">
          <Card.Header className="panel-header">
            <div className="panel-title">
              <Timer size={18} />
              <span>Aggregation</span>
            </div>
          </Card.Header>
          <Card.Content className="panel-content">
            <div className="filter-row">
              <select className="native-select" aria-label="Telemetry source" value={source} onChange={(event) => onSourceChange(event.target.value as "all" | ObservabilitySource)}>
                <option value="all">All sources</option>
                <option value="run">Run</option>
                <option value="event">Event</option>
                <option value="stage">Stage</option>
                <option value="observability">Log</option>
                <option value="workspace">Workspace</option>
                <option value="audit">Audit</option>
              </select>
              <select className="native-select" aria-label="Telemetry status" value={status} onChange={(event) => onStatusChange(event.target.value as "all" | "error" | "warning" | "success" | "denied")}>
                <option value="all">All status</option>
                <option value="error">Error</option>
                <option value="warning">Warning</option>
                <option value="success">Success</option>
                <option value="denied">Denied</option>
              </select>
              <Input aria-label="Telemetry filter" placeholder="tool, trace, audit" value={toolFilter} onChange={(event) => onToolFilterChange(event.target.value)} />
            </div>
            <div className="breakdown-list">
              {[
                ["Tool calls", display.toolCalls],
                ["MCP calls", display.mcpCalls],
                ["Errors", metrics?.error_count ?? errors.length],
                ["Skill views", display.skillViews],
                ["Input chars", display.inputChars],
                ["Output chars", display.outputChars],
                ["Avg output chars", display.avgOutputChars],
              ].map(([label, value]) => (
                <div className="breakdown-row" key={String(label)}>
                  <span>{label}</span>
                  <strong>{formatCount(Number(value))}</strong>
                </div>
              ))}
            </div>
            {summary?.turns?.length ? (
              <div className="breakdown-list turn-breakdown">
                {summary.turns.slice(0, 6).map((turn) => (
                  <div className="breakdown-row" key={turn.index}>
                    <span>Turn {turn.index}</span>
                    <strong>
                      in {formatCount(turn.input_chars ?? 0)} · out {formatCount(turn.output_chars ?? 0)}
                    </strong>
                  </div>
                ))}
              </div>
            ) : null}
            <Separator />
            <div className="breakdown-list turn-breakdown">
              {filteredTools.length === 0 ? (
                <div className="breakdown-row">
                  <span>No tool stats</span>
                  <strong>-</strong>
                </div>
              ) : (
                filteredTools.slice(0, 8).map((tool) => (
                  <div className="breakdown-row" key={tool.tool_name}>
                    <span>{tool.tool_name}</span>
                    <strong>
                      {formatCount(tool.result_count)} runs · {formatCount(tool.error_count)} errors · {formatMs(tool.avg_duration_ms ?? null)}
                    </strong>
                  </div>
                ))
              )}
            </div>
            <Separator />
            <div className="event-list compact-events">
              {filteredErrors.length === 0 ? (
                <p className="empty">No normalized errors were returned by the telemetry API.</p>
              ) : (
                filteredErrors.slice(0, 8).map((error, index) => (
                  <article className="timeline-event" key={`err-${error.response_id}-${error.type}-${index}`}>
                    <div>
                      <strong>{error.type}</strong>
                      <span>
                        {[error.source, error.tool_name, error.trace_id].filter(Boolean).join(" · ")}
                        {error.trace_id ? (
                          <button className="inline-link" type="button" onClick={() => onInspectTrace(error.trace_id || "")}>
                            trace
                          </button>
                        ) : null}
                      </span>
                    </div>
                    <pre>{error.message || compactJson(error.payload ?? {})}</pre>
                  </article>
                ))
              )}
            </div>
            <Separator />
            <div className="event-list compact-events">
              {filteredTimeline.length === 0 ? (
                <p className="empty">Telemetry timeline will populate after Core records run, tool, audit, or stage events.</p>
              ) : (
                filteredTimeline.slice(0, 14).map((event, index) => (
                  <article className="timeline-event" key={`tel-${event.response_id}-${event.seq}-${event.type}-${index}`}>
                    <div>
                      <strong>{event.type}</strong>
                      <span>
                        {timelineMeta(event)}
                        {event.trace_id ? (
                          <button className="inline-link" type="button" onClick={() => onInspectTrace(event.trace_id || "")}>
                            trace
                          </button>
                        ) : null}
                      </span>
                    </div>
                    {event.message ? <pre>{event.message}</pre> : null}
                  </article>
                ))
              )}
            </div>
            <Separator />
            <div className="suggestion-list">
              {iterationSuggestions.map((suggestion) => (
                <button className="suggestion-row" key={suggestion.title} type="button" onClick={() => onNavigate(suggestion.target)}>
                  <strong>{suggestion.title}</strong>
                  <span>{suggestion.detail}</span>
                </button>
              ))}
            </div>
          </Card.Content>
        </Card>
      </div>
    </>
  );
}

function MetricCard({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <Card className="metric-card">
      <Card.Content>
        <span>{label}</span>
        <strong>{value}</strong>
        <small>{detail}</small>
      </Card.Content>
    </Card>
  );
}
