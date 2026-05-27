import { Button, Card } from "@heroui/react";
import { Bug, Database, Timer } from "lucide-react";
import { ObservabilityRunItem } from "../anyagentClient";
import { formatCount, formatMs } from "../studioUtils";

type EvaluationsPageProps = {
  runs: ObservabilityRunItem[];
  totalLatency: number | null;
  errorCount: number;
  onInspectRun: (responseId: string) => void;
};

export function EvaluationsPage({ runs, totalLatency, errorCount, onInspectRun }: EvaluationsPageProps) {
  return (
    <>
      <section className="section-block">
        <div className="section-title">
          <Database size={17} />
          <h2>Evaluation seeds</h2>
          <span>{runs.length} candidate runs</span>
        </div>
        <div className="overview-grid">
          <Card className="overview-card">
            <Card.Content className="overview-content">
              <div className="empty-icon">
                <Database size={27} />
              </div>
              <h3>Candidate runs</h3>
              <p>{runs.length} recent runs can be promoted into an evaluation dataset.</p>
            </Card.Content>
          </Card>
          <Card className="overview-card">
            <Card.Content className="overview-content">
              <div className="empty-icon">
                <Timer size={27} />
              </div>
              <h3>Latency focus</h3>
              <p>{formatMs(totalLatency)} latest max response latency.</p>
            </Card.Content>
          </Card>
          <Card className="overview-card">
            <Card.Content className="overview-content">
              <div className="empty-icon">
                <Bug size={27} />
              </div>
              <h3>Error focus</h3>
              <p>{formatCount(errorCount)} normalized errors available.</p>
            </Card.Content>
          </Card>
        </div>
      </section>

      <Card className="panel">
        <Card.Header className="panel-header">
          <div className="panel-title">
            <Database size={18} />
            <span>Seed queue</span>
          </div>
        </Card.Header>
        <Card.Content className="panel-content">
          <div className="history-list">
            {runs.length === 0 ? (
              <p className="empty">Run a session first, then select useful responses here.</p>
            ) : (
              runs.map((run) => (
                <article className="evaluation-row" key={run.response_id}>
                  <div>
                    <strong>{run.response_id}</strong>
                    <span>{run.status} · {run.agent_id} · {run.session_key}</span>
                  </div>
                  <Button size="sm" variant="secondary" onPress={() => onInspectRun(run.response_id)}>
                    Inspect
                  </Button>
                </article>
              ))
            )}
          </div>
        </Card.Content>
      </Card>
    </>
  );
}
