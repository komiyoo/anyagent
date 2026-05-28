import { Button, Card } from "@heroui/react";
import { ShieldCheck } from "lucide-react";
import { ObservabilityErrorItem, ObservabilityRunItem, ObservabilityTimelineEvent } from "../anyagentClient";
import { compactJson, formatCount, timelineMeta } from "../studioUtils";

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

  return (
    <>
      <section className="section-block">
        <div className="section-title">
          <ShieldCheck size={17} />
          <h2>Audit trail</h2>
          <span>{formatCount(auditEvents.length + deniedErrors.length)} security records</span>
        </div>
        <div className="overview-grid">
          <Card className="overview-card">
            <Card.Content className="overview-content">
              <div className="empty-icon">
                <ShieldCheck size={27} />
              </div>
              <h3>{formatCount(auditEvents.length)} audit events</h3>
              <p>Workspace, policy, and tool audit records from observability.</p>
            </Card.Content>
          </Card>
          <Card className="overview-card">
            <Card.Content className="overview-content">
              <div className="empty-icon">
                <ShieldCheck size={27} />
              </div>
              <h3>{formatCount(deniedErrors.length)} denied actions</h3>
              <p>Policy denials and normalized security errors.</p>
            </Card.Content>
          </Card>
          <Card className="overview-card">
            <Card.Content className="overview-content">
              <div className="empty-icon">
                <ShieldCheck size={27} />
              </div>
              <h3>{formatCount(runs.length)} runs</h3>
              <p>Recent responses available for audit correlation.</p>
            </Card.Content>
          </Card>
        </div>
      </section>

      <div className="main-grid">
        <Card className="panel">
          <Card.Header className="panel-header">
            <div className="panel-title">
              <ShieldCheck size={18} />
              <span>Audit events</span>
            </div>
            <Button size="sm" variant="secondary" onPress={onRefresh}>
              Refresh
            </Button>
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
                <p className="empty">No audit events have been recorded for the current filters.</p>
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
              {runs.slice(0, 12).map((run) => (
                <button className="history-row" key={run.response_id} type="button" onClick={() => onInspectRun(run.response_id)}>
                  <div>
                    <strong>{run.response_id}</strong>
                    <span>{run.status} · {run.session_key}</span>
                  </div>
                  <p>{run.agent_id}</p>
                  <em>{run.effective_status}</em>
                </button>
              ))}
            </div>
          </Card.Content>
        </Card>
      </div>
    </>
  );
}
