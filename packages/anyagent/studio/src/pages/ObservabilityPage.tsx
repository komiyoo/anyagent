import { Button, Card, Chip, Input, Tabs } from "@heroui/react";
import { BarChart3, CheckCircle2, Clock, Copy, MessageSquareText, Play, RefreshCw, Timer, Wrench, X } from "lucide-react";
import { useState } from "react";
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
import { compactJson, formatCount, formatMs, relativeTime, shortHash, statusColor, timelineMeta } from "../studioUtils";

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
  sources: ObservabilitySource[];
  statuses: Array<"error" | "warning" | "success" | "denied">;
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
  onSourcesChange: (value: ObservabilitySource[]) => void;
  onStatusesChange: (value: Array<"error" | "warning" | "success" | "denied">) => void;
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
  sources,
  statuses,
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
  onSourcesChange,
  onStatusesChange,
  onToolFilterChange,
  onRefresh,
  onSelectRun,
  onInspectTrace,
  onNavigate,
}: ObservabilityPageProps) {
  const sourceOptions: ObservabilitySource[] = ["run", "event", "stage", "observability", "workspace", "audit"];
  const statusOptions: Array<"error" | "warning" | "success" | "denied"> = ["error", "warning", "success", "denied"];

  return (
    <>
      <section className="section-block">
        <div className="section-title">
          <BarChart3 size={17} />
          <h2>Observability</h2>
          <span>
            {settings.agentId || "main"} · {selectedRun
              ? `${relativeTime(selectedRun.created_at_ms)} · ${selectedRun.status}`
              : "current session"}
          </span>
        </div>
        <div className="stats-tier stats-tier--primary">
          <Stat label="Runs" value={formatCount(display.runCount)} />
          <Stat label="Errors" value={formatCount(metrics?.error_count ?? errors.length)} className={errors.length > 0 ? "stat--alert" : ""} />
          <Stat label="Latency" value={formatMs(display.totalLatency)} />
          <Stat label="First token" value={formatMs(display.firstTokenLatency)} />
        </div>
        <div className="stats-tier stats-tier--secondary">
          <Stat label="Tokens" value={formatCount(display.inputTokens + display.outputTokens)} hint={`in ${formatCount(display.inputTokens)} / out ${formatCount(display.outputTokens)}`} />
          <Stat label="Cached" value={formatCount(display.cachedTokens)} />
          <Stat label="Tools" value={formatCount(display.toolCalls)} hint={`${formatCount(tools.length)} unique`} />
          <Stat label="MCP" value={formatCount(display.mcpCalls)} />
          <Stat label="Turns" value={formatCount(display.turnCount)} />
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
              <Button size="sm" variant="ghost" isIconOnly className="filter-action" aria-label="Refresh observability" onPress={onRefresh}>
                <RefreshCw size={16} />
              </Button>
            </div>
            <div className="filter-row input-group">
              <Input aria-label="Trace id" placeholder="trace_id" value={traceId} onChange={(event) => onTraceIdChange(event.target.value)} />
              <Button size="sm" variant="ghost" className="input-group-action" onPress={() => onInspectTrace(traceId)}>
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
                <div className="empty-state">
                  <BarChart3 size={24} />
                  <strong>No telemetry yet</strong>
                  <p>No run history available for the current agent/session.</p>
                  <Button size="sm" variant="primary" onPress={() => onNavigate("home")}>
                    <Play size={13} />
                    Start a request
                  </Button>
                </div>
              ) : (
              runs.map((run) => {
                const duration = Math.max((run.ended_at_ms ?? run.updated_at_ms) - run.created_at_ms, run.updated_at_ms - run.created_at_ms, 0);
                return (
                  <button
                    className={`history-row ${run.response_id === selectedRun?.response_id ? "active" : ""}`}
                    key={run.response_id}
                    type="button"
                    onClick={() => onSelectRun(run.response_id)}
                  >
                    <div className="run-row-left">
                      <span className={`status-dot status-dot--${statusColor(run.status)}`} />
                      <span className="run-row-time">{relativeTime(run.created_at_ms)}</span>
                    </div>
                    <div className="run-row-center">
                      <strong>{run.agent_id}</strong>
                      <span className="run-row-meta">{run.stream ? "stream" : "sync"} · {formatMs(duration)}</span>
                    </div>
                    <div className="run-row-right">
                      <code className="run-row-hash" title={run.response_id}>{shortHash(run.response_id)}</code>
                      <CopyButton text={run.response_id} />
                    </div>
                  </button>
                );
              })
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
              <Input aria-label="Telemetry filter" placeholder="Filter tools, traces, audit..." value={toolFilter} onChange={(event) => onToolFilterChange(event.target.value)} />
            </div>
            <div className="filter-header">
              <strong>Filters</strong>
              {(sources.length > 0 || statuses.length > 0) && (
                <>
                  <Chip size="sm" variant="soft" color="accent">{sources.length + statuses.length} active</Chip>
                  <button className="filter-clear" type="button" onClick={() => { onSourcesChange([]); onStatusesChange([]); }}>
                    <X size={12} /> Clear
                  </button>
                </>
              )}
            </div>
            <div className="advanced-filter-grid">
              <div>
                <strong>Sources</strong>
                <div className="filter-chip-row">
                  {sourceOptions.map((option) => (
                    <button
                      className={`filter-chip ${sources.includes(option) ? "active" : ""}`}
                      key={option}
                      type="button"
                      onClick={() =>
                        onSourcesChange(sources.includes(option) ? sources.filter((item) => item !== option) : [...sources, option])
                      }
                    >
                      {option}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <strong>Status</strong>
                <div className="filter-chip-row">
                  {statusOptions.map((option) => (
                    <button
                      className={`filter-chip ${statuses.includes(option) ? "active" : ""}`}
                      key={option}
                      type="button"
                      onClick={() =>
                        onStatusesChange(statuses.includes(option) ? statuses.filter((item) => item !== option) : [...statuses, option])
                      }
                    >
                      {option}
                    </button>
                  ))}
                </div>
              </div>
            </div>
            <Tabs defaultSelectedKey="tools" className="obs-tabs">
              <Tabs.List>
                <Tabs.Tab id="tools">Tools ({filteredTools.length})</Tabs.Tab>
                <Tabs.Tab id="errors">Errors ({filteredErrors.length})</Tabs.Tab>
                <Tabs.Tab id="timeline">Timeline ({filteredTimeline.length})</Tabs.Tab>
                <Tabs.Tab id="insights">Insights ({iterationSuggestions.length})</Tabs.Tab>
              </Tabs.List>
              <Tabs.Panel id="tools">
                {summary?.turns?.length ? (
                  <div className="breakdown-list turn-breakdown">
                    {summary.turns.slice(0, 6).map((turn) => (
                      <div className="breakdown-row" key={turn.index}>
                        <span>Turn {turn.index}</span>
                        <strong>in {formatCount(turn.input_chars ?? 0)} · out {formatCount(turn.output_chars ?? 0)}</strong>
                      </div>
                    ))}
                  </div>
                ) : null}
                <div className="breakdown-list turn-breakdown">
                  {filteredTools.length === 0 ? (
                    <div className="empty-state compact-empty">
                      <Wrench size={20} />
                      <strong>No tool calls recorded</strong>
                      <p>Tool usage statistics appear after the agent executes tool calls.</p>
                    </div>
                  ) : (
                    filteredTools.slice(0, 12).map((tool) => (
                      <div className="breakdown-row" key={tool.tool_name}>
                        <span>{tool.tool_name}</span>
                        <strong>{formatCount(tool.result_count)} runs · {formatCount(tool.error_count)} errors · {formatMs(tool.avg_duration_ms ?? null)}</strong>
                      </div>
                    ))
                  )}
                </div>
              </Tabs.Panel>
              <Tabs.Panel id="errors">
                <div className="event-list compact-events">
                  {filteredErrors.length === 0 ? (
                    <div className="empty-state compact-empty">
                      <CheckCircle2 size={20} />
                      <strong>No errors</strong>
                      <p>All runs completed without normalized errors.</p>
                    </div>
                  ) : (
                    filteredErrors.slice(0, 12).map((error, index) => (
                      <article className="timeline-event" key={`err-${error.response_id}-${error.type}-${index}`}>
                        <div>
                          <strong>{error.type}</strong>
                          <span>
                            {[error.source, error.tool_name].filter(Boolean).join(" · ")}
                            {error.trace_id ? (
                              <button className="inline-link" type="button" onClick={() => onInspectTrace(error.trace_id || "")}>trace</button>
                            ) : null}
                          </span>
                        </div>
                        <pre>{error.message || compactJson(error.payload ?? {})}</pre>
                      </article>
                    ))
                  )}
                </div>
              </Tabs.Panel>
              <Tabs.Panel id="timeline">
                <div className="event-list compact-events">
                  {filteredTimeline.length === 0 ? (
                    <div className="empty-state compact-empty">
                      <Clock size={20} />
                      <strong>No timeline events</strong>
                      <p>Timeline populates after the agent records run, tool, audit, or stage events.</p>
                    </div>
                  ) : (
                    filteredTimeline.slice(0, 20).map((event, index) => (
                      <article className="timeline-event" key={`tel-${event.response_id}-${event.seq}-${event.type}-${index}`}>
                        <div>
                          <strong>{event.type}</strong>
                          <span>
                            {timelineMeta(event)}
                            {event.trace_id ? (
                              <button className="inline-link" type="button" onClick={() => onInspectTrace(event.trace_id || "")}>trace</button>
                            ) : null}
                          </span>
                        </div>
                        {event.message ? <pre>{event.message}</pre> : null}
                      </article>
                    ))
                  )}
                </div>
              </Tabs.Panel>
              <Tabs.Panel id="insights">
                <div className="suggestion-list">
                  {iterationSuggestions.map((suggestion) => (
                    <button className="suggestion-row" key={suggestion.title} type="button" onClick={() => onNavigate(suggestion.target)}>
                      <strong>{suggestion.title}</strong>
                      <span>{suggestion.detail}</span>
                    </button>
                  ))}
                </div>
              </Tabs.Panel>
            </Tabs>
          </Card.Content>
        </Card>
      </div>
    </>
  );
}

function Stat({ label, value, hint, className }: { label: string; value: string; hint?: string; className?: string }) {
  return (
    <span className={`stat ${className || ""}`} title={hint ? `${label}: ${value} (${hint})` : `${label}: ${value}`}>
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value}</span>
      {hint ? <span className="stat-label">{hint}</span> : null}
    </span>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      className="copy-btn"
      type="button"
      title="Copy response ID"
      onClick={(e) => {
        e.stopPropagation();
        navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
    >
      {copied ? <CheckCircle2 size={12} /> : <Copy size={12} />}
    </button>
  );
}
