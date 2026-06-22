import { Button, Card, Chip, Input } from "@heroui/react";
import { BarChart3, CheckCircle2, ChevronDown, ChevronRight, Clock, Copy, Download, Eye, FileCode, MessageSquareText, Play, RefreshCw, Timer, Wrench, X } from "lucide-react";
import { useState } from "react";
import {
  McpServerDraft,
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
  StudioSettings,
  ToolExecutionDetail,
} from "../anyagentClient";
import { StudioTab } from "../navigation";
import { compactJson, downloadFile, exportFilename, formatCount, formatMs, relativeTime, shortHash, timelineMeta, toCsv } from "../studioUtils";
import {
  CollapsibleSection,
  CompactTable,
  EmptyState,
  normalizeStatus,
  StatStrip,
  StatusBadge,
} from "../components/design-system";
import type { StatItem } from "../components/design-system";

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
  replayToolExecutions: ToolExecutionDetail[];
  replayModelRequest: ModelRequestResponse | null;
  replayPromptContext: PromptContextResponse | null;
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
  replayToolExecutions,
  replayModelRequest,
  replayPromptContext,
}: ObservabilityPageProps) {
  void selectedResponseId;
  void mcpDrafts;
  void selectedSkillCount;
  void summary;
  const sourceOptions: ObservabilitySource[] = ["run", "event", "stage", "observability", "workspace", "audit"];
  const statusOptions: Array<"error" | "warning" | "success" | "denied"> = ["error", "warning", "success", "denied"];
  const [replayTab, setReplayTab] = useState<"context" | "model" | "tools">("context");
  const [replayExpanded, setReplayExpanded] = useState(false);
  const [openSection, setOpenSection] = useState<string>("history");

  const errorCount = metrics?.error_count ?? errors.length;
  const errorTone = errorCount > 0 ? "error" : "default";

  const primaryStats: StatItem[] = [
    { label: "Runs", value: formatCount(display.runCount) },
    { label: "Errors", value: formatCount(errorCount), tone: errorTone },
    { label: "Latency", value: formatMs(display.totalLatency) },
    { label: "First token", value: formatMs(display.firstTokenLatency) },
  ];

  const secondaryStats: StatItem[] = [
    {
      label: "Tokens",
      value: formatCount(display.inputTokens + display.outputTokens),
      hint: `in ${formatCount(display.inputTokens)} / out ${formatCount(display.outputTokens)}`,
    },
    { label: "Cached", value: formatCount(display.cachedTokens) },
    { label: "Tools", value: formatCount(display.toolCalls), hint: `${formatCount(tools.length)} unique` },
    { label: "MCP", value: formatCount(display.mcpCalls) },
    { label: "Turns", value: formatCount(display.turnCount) },
  ];

  const runColumns = [
    {
      key: "time",
      header: "Time",
      width: "90px",
      render: (run: ObservabilityRunItem) => (
        <span className="ds-cell-mono">{relativeTime(run.created_at_ms)}</span>
      ),
    },
    {
      key: "status",
      header: "Status",
      width: "96px",
      render: (run: ObservabilityRunItem) => (
        <StatusBadge status={normalizeStatus(run.effective_status || run.status)}>
          {run.effective_status || run.status}
        </StatusBadge>
      ),
    },
    {
      key: "agent",
      header: "Agent",
      render: (run: ObservabilityRunItem) => (
        <div className="ds-cell-stack">
          <strong className="ds-cell-strong">{run.agent_id}</strong>
          <span className="ds-cell-sub">{run.stream ? "stream" : "sync"}</span>
        </div>
      ),
    },
    {
      key: "duration",
      header: "Duration",
      align: "right" as const,
      width: "84px",
      render: (run: ObservabilityRunItem) => {
        const duration = Math.max(
          (run.ended_at_ms ?? run.updated_at_ms) - run.created_at_ms,
          run.updated_at_ms - run.created_at_ms,
          0,
        );
        return <span className="ds-cell-mono">{formatMs(duration)}</span>;
      },
    },
    {
      key: "id",
      header: "ID",
      align: "right" as const,
      width: "120px",
      render: (run: ObservabilityRunItem) => (
        <span className="ds-cell-id">
          <code className="ds-cell-mono" title={run.response_id}>{shortHash(run.response_id)}</code>
          <CopyButton text={run.response_id} />
        </span>
      ),
    },
  ];

  const toggleSection = (key: string) => setOpenSection((current) => (current === key ? "" : key));

  const exportRunsCsv = () => {
    const rows = runs.map((run) => {
      const duration = Math.max((run.ended_at_ms ?? run.updated_at_ms) - run.created_at_ms, 0);
      return {
        response_id: run.response_id,
        agent_id: run.agent_id,
        session_key: run.session_key,
        status: run.status,
        effective_status: run.effective_status,
        stream: run.stream,
        created_at_ms: run.created_at_ms,
        updated_at_ms: run.updated_at_ms,
        ended_at_ms: run.ended_at_ms ?? "",
        duration_ms: duration,
      };
    });
    downloadFile(exportFilename("observability-runs", "csv"), toCsv(rows), "text/csv;charset=utf-8");
  };

  const exportRunsJson = () => {
    downloadFile(exportFilename("observability-runs", "json"), compactJson(runs), "application/json");
  };

  return (
    <>
      <section className="section-block ds-obs-header">
        <div className="section-title">
          <BarChart3 size={17} />
          <h2>Observability</h2>
          <span>
            {settings.agentId || "main"} · {selectedRun
              ? `${relativeTime(selectedRun.created_at_ms)} · ${selectedRun.status}`
              : "current session"}
          </span>
        </div>
        <StatStrip stats={primaryStats} />
        <StatStrip stats={secondaryStats} className="ds-stat-strip--secondary" />
      </section>

      <div className="main-grid observability-grid">
        <Card className="panel">
          <Card.Header className="panel-header">
            <div className="panel-title">
              <MessageSquareText size={18} />
              <span>History</span>
            </div>
            <div className="editor-actions">
              <Chip size="sm" variant="soft" color={runs.length ? "success" : "default"}>
                {runs.length ? `${runs.length} runs` : "empty"}
              </Chip>
              <Button size="sm" variant="secondary" isDisabled={runs.length === 0} onPress={exportRunsCsv} aria-label="Export runs as CSV">
                <Download size={14} />
                CSV
              </Button>
              <Button size="sm" variant="secondary" isDisabled={runs.length === 0} onPress={exportRunsJson} aria-label="Export runs as JSON">
                <Download size={14} />
                JSON
              </Button>
            </div>
          </Card.Header>
          <Card.Content className="panel-content">
            <div className="filter-row">
              <select
                className="native-select"
                aria-label="Observability time window"
                value={window}
                onChange={(event) => onWindowChange(event.target.value as "all" | "hour" | "day")}
              >
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
            {runs.length === 0 ? (
              <EmptyState
                icon={<BarChart3 size={20} />}
                title="No telemetry yet"
                description="No run history available for the current agent/session."
                action={
                  <Button size="sm" variant="primary" onPress={() => onNavigate("home")}>
                    <Play size={13} />
                    Start a request
                  </Button>
                }
              />
            ) : (
              <CompactTable
                columns={runColumns}
                rows={runs.slice(0, Math.max(limit, 8))}
                rowKey={(run) => run.response_id}
                activeRowKey={selectedRun?.response_id ?? null}
                onRowClick={(run) => onSelectRun(run.response_id)}
                className="ds-obs-runs"
              />
            )}
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
              <Input
                aria-label="Telemetry filter"
                placeholder="Filter tools, traces, audit..."
                value={toolFilter}
                onChange={(event) => onToolFilterChange(event.target.value)}
              />
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

            <div className="ds-collapsible-stack">
              <CollapsibleSection
                title="Tools"
                count={filteredTools.length}
                open={openSection === "tools"}
                onToggle={() => toggleSection("tools")}
              >
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
                {filteredTools.length === 0 ? (
                  <EmptyState
                    compact
                    icon={<Wrench size={18} />}
                    title="No tool calls recorded"
                    description="Tool usage statistics appear after the agent executes tool calls."
                  />
                ) : (
                  <>
                    <div className="ds-bar-chart" aria-label="Tool usage by result count">
                      {filteredTools.slice(0, 6).map((tool) => {
                        const max = Math.max(...filteredTools.map((t) => t.result_count), 1);
                        const ratio = Math.max(0, Math.min(100, (tool.result_count / max) * 100));
                        return (
                          <div className="ds-bar-row" key={`bar-${tool.tool_name}`} title={`${tool.tool_name}: ${formatCount(tool.result_count)} runs`}>
                            <span className="ds-bar-label">{tool.tool_name}</span>
                            <span className="ds-bar-track" aria-hidden="true">
                              <span className={`ds-bar-fill${tool.error_count > 0 ? " ds-bar-fill--error" : ""}`} style={{ width: `${ratio}%` }} />
                            </span>
                            <span className="ds-bar-value">{formatCount(tool.result_count)}</span>
                          </div>
                        );
                      })}
                    </div>
                    <CompactTable
                    columns={[
                      { key: "name", header: "Tool", render: (t: ObservabilityToolStats) => <strong className="ds-cell-strong">{t.tool_name}</strong> },
                      { key: "runs", header: "Runs", align: "right", width: "70px", render: (t: ObservabilityToolStats) => formatCount(t.result_count) },
                      { key: "errors", header: "Errors", align: "right", width: "70px", render: (t: ObservabilityToolStats) => formatCount(t.error_count) },
                      { key: "avg", header: "Avg", align: "right", width: "80px", render: (t: ObservabilityToolStats) => formatMs(t.avg_duration_ms ?? null) },
                    ]}
                    rows={filteredTools.slice(0, 12)}
                    rowKey={(t) => t.tool_name}
                  />
                  </>
                )}
              </CollapsibleSection>

              <CollapsibleSection
                title="Errors"
                count={filteredErrors.length}
                open={openSection === "errors"}
                onToggle={() => toggleSection("errors")}
              >
                {filteredErrors.length === 0 ? (
                  <EmptyState
                    compact
                    icon={<CheckCircle2 size={18} />}
                    title="No errors"
                    description="All runs completed without normalized errors."
                  />
                ) : (
                  <div className="event-list compact-events">
                    {filteredErrors.slice(0, 12).map((error, index) => (
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
                    ))}
                  </div>
                )}
              </CollapsibleSection>

              <CollapsibleSection
                title="Timeline"
                count={filteredTimeline.length}
                open={openSection === "timeline"}
                onToggle={() => toggleSection("timeline")}
              >
                {filteredTimeline.length === 0 ? (
                  <EmptyState
                    compact
                    icon={<Clock size={18} />}
                    title="No timeline events"
                    description="Timeline populates after the agent records run, tool, audit, or stage events."
                  />
                ) : (
                  <div className="event-list compact-events">
                    {filteredTimeline.slice(0, 20).map((event, index) => (
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
                    ))}
                  </div>
                )}
              </CollapsibleSection>

              <CollapsibleSection
                title="Insights"
                count={iterationSuggestions.length}
                open={openSection === "insights"}
                onToggle={() => toggleSection("insights")}
              >
                <div className="suggestion-list">
                  {iterationSuggestions.map((suggestion) => (
                    <button className="suggestion-row" key={suggestion.title} type="button" onClick={() => onNavigate(suggestion.target)}>
                      <strong>{suggestion.title}</strong>
                      <span>{suggestion.detail}</span>
                    </button>
                  ))}
                </div>
              </CollapsibleSection>
            </div>
          </Card.Content>
        </Card>
      </div>

      {selectedRun && (
        <Card className="panel replay-panel">
          <Card.Header className="panel-header">
            <button
              className="replay-toggle"
              type="button"
              onClick={() => setReplayExpanded((v) => !v)}
            >
              {replayExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
              <Eye size={16} />
              <span>Run Replay · {selectedRun.response_id.slice(0, 16)}…</span>
            </button>
            {replayExpanded && (
              <div className="replay-tabs">
                <button
                  className={`replay-tab ${replayTab === "context" ? "active" : ""}`}
                  type="button"
                  onClick={() => setReplayTab("context")}
                >
                  <FileCode size={13} /> Prompt Context
                </button>
                <button
                  className={`replay-tab ${replayTab === "model" ? "active" : ""}`}
                  type="button"
                  onClick={() => setReplayTab("model")}
                >
                  <MessageSquareText size={13} /> Model Request
                </button>
                <button
                  className={`replay-tab ${replayTab === "tools" ? "active" : ""}`}
                  type="button"
                  onClick={() => setReplayTab("tools")}
                >
                  <Wrench size={13} /> Tool Executions ({replayToolExecutions.length})
                </button>
              </div>
            )}
          </Card.Header>
          {replayExpanded && (
            <Card.Content className="panel-content replay-content">
              {replayTab === "context" && (
                <div className="replay-section">
                  {replayPromptContext?.fragments && replayPromptContext.fragments.length > 0 ? (
                    <div className="replay-fragments">
                      <div className="replay-meta">
                        <span>
                          {replayPromptContext.fragments.length} fragment{replayPromptContext.fragments.length !== 1 ? "s" : ""}
                          {replayPromptContext.total_chars ? ` · ${formatCount(replayPromptContext.total_chars)} chars` : ""}
                          {replayPromptContext.prompt_cache_key ? ` · cache: ${shortHash(replayPromptContext.prompt_cache_key)}` : ""}
                        </span>
                      </div>
                      {replayPromptContext.fragments.map((frag, idx) => (
                        <details className="replay-tool-detail" key={`frag-${frag.stable_id ?? idx}`}>
                          <summary>
                            <strong>{frag.label ?? frag.kind}</strong>
                            <span> · {frag.role} · {frag.cache_class}</span>
                            {frag.source_path ? <span> · {frag.source_path}</span> : null}
                          </summary>
                          <pre className="replay-json">{frag.rendered_text}</pre>
                        </details>
                      ))}
                    </div>
                  ) : (
                    <EmptyState
                      compact
                      icon={<FileCode size={18} />}
                      title="No rendered context"
                      description="Prompt context fragments are not available for this run."
                    />
                  )}
                </div>
              )}
              {replayTab === "model" && (
                <div className="replay-section">
                  {replayModelRequest?.applied_body ? (
                    <pre className="replay-json">
                      {JSON.stringify(replayModelRequest.applied_body, null, 2)}
                    </pre>
                  ) : (
                    <EmptyState
                      compact
                      icon={<MessageSquareText size={18} />}
                      title="No model request"
                      description="The first model request body was not persisted for this run."
                    />
                  )}
                </div>
              )}
              {replayTab === "tools" && (
                <div className="replay-section">
                  {replayToolExecutions.length > 0 ? (
                    replayToolExecutions.map((exec, index) => (
                      <article className="timeline-event replay-tool-event" key={`tool-${exec.tool_call_id}-${index}`}>
                        <div>
                          <strong>{exec.tool_name}</strong>
                          <span>
                            {exec.status} · {exec.duration_ms != null ? `${exec.duration_ms}ms` : "—"}
                            {exec.audit_ref ? ` · ${exec.audit_ref}` : ""}
                          </span>
                        </div>
                        <details className="replay-tool-detail">
                          <summary>Arguments</summary>
                          <pre className="replay-json">{exec.arguments_json}</pre>
                        </details>
                        {exec.output && (
                          <details className="replay-tool-detail">
                            <summary>Output</summary>
                            <pre className="replay-json">{exec.output}</pre>
                          </details>
                        )}
                        {exec.error && (
                          <details className="replay-tool-detail replay-tool-error">
                            <summary>Error</summary>
                            <pre className="replay-json">{JSON.stringify(exec.error, null, 2)}</pre>
                          </details>
                        )}
                      </article>
                    ))
                  ) : (
                    <EmptyState
                      compact
                      icon={<Wrench size={18} />}
                      title="No tool executions"
                      description="Tool execution details are not available for this run."
                    />
                  )}
                </div>
              )}
            </Card.Content>
          )}
        </Card>
      )}
    </>
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
