import { Button, Card } from "@heroui/react";
import { Download, ShieldCheck } from "lucide-react";
import { ObservabilityErrorItem, ObservabilityRunItem, ObservabilityTimelineEvent } from "../anyagentClient";
import { compactJson, downloadFile, exportFilename, formatCount, relativeTime, timelineMeta, toCsv } from "../studioUtils";
import { CompactTable, EmptyState, StatStrip, StatusBadge, normalizeStatus } from "../components/design-system";
import type { StatItem } from "../components/design-system";

type AuditPageProps = {
  errors: ObservabilityErrorItem[];
  runs: ObservabilityRunItem[];
  timeline: ObservabilityTimelineEvent[];
  onInspectRun: (responseId: string) => void;
  onRefresh: () => void;
};

export function AuditPage({ errors, runs, timeline, onInspectRun, onRefresh }: AuditPageProps) {
  const auditEvents = timeline.filter((event) => event.source === "audit" || event.audit_ref || event.category === "audit");
  const deniedErrors = errors.filter((error) => error.status === "denied" || error.payload?.status === "denied");

  const stats: StatItem[] = [
    { label: "Audit events", value: formatCount(auditEvents.length) },
    { label: "Denied actions", value: formatCount(deniedErrors.length), tone: deniedErrors.length > 0 ? "error" : "default" },
    { label: "Runs", value: formatCount(runs.length) },
    { label: "Total records", value: formatCount(auditEvents.length + deniedErrors.length) },
  ];

  const exportAuditCsv = () => {
    const rows = auditEvents.map((event) => ({
      type: event.type,
      source: event.source,
      status: event.status ?? "",
      tool_name: event.tool_name ?? "",
      response_id: event.response_id ?? "",
      trace_id: event.trace_id ?? "",
      audit_ref: event.audit_ref ?? "",
      ts_ms: event.ts_ms ?? "",
      message: event.message ?? "",
    }));
    downloadFile(exportFilename("audit-events", "csv"), toCsv(rows), "text/csv;charset=utf-8");
  };

  return (
    <>
      <section className="section-block ds-obs-header">
        <div className="section-title">
          <ShieldCheck size={17} />
          <h2>Audit trail</h2>
          <span>{formatCount(auditEvents.length + deniedErrors.length)} security records</span>
        </div>
        <StatStrip stats={stats} />
      </section>

      <div className="main-grid">
        <Card className="panel">
          <Card.Header className="panel-header">
            <div className="panel-title">
              <ShieldCheck size={18} />
              <span>Audit events</span>
            </div>
            <div className="editor-actions">
              <Button size="sm" variant="secondary" onPress={onRefresh}>
                Refresh
              </Button>
              <Button size="sm" variant="secondary" isDisabled={auditEvents.length === 0} onPress={exportAuditCsv} aria-label="Export audit events as CSV">
                <Download size={14} />
                CSV
              </Button>
            </div>
          </Card.Header>
          <Card.Content className="panel-content">
            <div className="event-list compact-events">
              {auditEvents.length ? (
                auditEvents.slice(0, 30).map((event, index) => (
                  <article className="timeline-event" key={`audit-${event.audit_ref}-${event.seq}-${index}`}>
                    <div>
                      <strong>{event.type}</strong>
                      <span>{timelineMeta(event)}</span>
                    </div>
                    <pre>{event.message || compactJson(event.payload ?? {})}</pre>
                  </article>
                ))
              ) : (
                <EmptyState compact icon={<ShieldCheck size={18} />} title="No audit events" description="No audit events have been recorded for the current filters." />
              )}
            </div>
          </Card.Content>
        </Card>

        <Card className="panel">
          <Card.Header className="panel-header">
            <div className="panel-title">
              <ShieldCheck size={18} />
              <span>Denied and correlated runs</span>
            </div>
          </Card.Header>
          <Card.Content className="panel-content">
            {deniedErrors.length > 0 ? (
              <div className="event-list compact-events">
                {deniedErrors.map((error, index) => (
                  <article className="timeline-event" key={`denied-${error.response_id}-${index}`}>
                    <div>
                      <strong>{error.type}</strong>
                      <span>{[error.source, error.tool_name, error.trace_id].filter(Boolean).join(" · ")}</span>
                    </div>
                    <pre>{error.message || compactJson(error.payload ?? {})}</pre>
                  </article>
                ))}
              </div>
            ) : null}
            {runs.length > 0 ? (
              <CompactTable
                className="ds-audit-runs"
                columns={[
                  { key: "id", header: "Response ID", render: (r: ObservabilityRunItem) => <strong className="ds-cell-strong">{r.response_id}</strong> },
                  {
                    key: "status",
                    header: "Status",
                    width: "110px",
                    render: (r: ObservabilityRunItem) => (
                      <StatusBadge status={normalizeStatus(r.effective_status || r.status)}>{r.effective_status}</StatusBadge>
                    ),
                  },
                  { key: "agent", header: "Agent", width: "120px", render: (r: ObservabilityRunItem) => <span className="ds-cell-sub">{r.agent_id}</span> },
                  { key: "session", header: "Session", render: (r: ObservabilityRunItem) => <span className="ds-cell-mono">{r.session_key}</span> },
                  { key: "time", header: "Started", align: "right", width: "100px", render: (r: ObservabilityRunItem) => <span className="ds-cell-mono">{relativeTime(r.created_at_ms)}</span> },
                ]}
                rows={runs.slice(0, 12)}
                rowKey={(r) => r.response_id}
                onRowClick={(r) => onInspectRun(r.response_id)}
              />
            ) : null}
            {deniedErrors.length === 0 && runs.length === 0 ? (
              <EmptyState compact icon={<ShieldCheck size={18} />} title="No correlated runs" description="Denied actions and recent runs will appear here for audit correlation." />
            ) : null}
          </Card.Content>
        </Card>
      </div>
    </>
  );
}
