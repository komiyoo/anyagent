import { Button, Card } from "@heroui/react";
import { MessageSquareText, RefreshCw } from "lucide-react";
import { ObservabilityRunItem, StudioSettings } from "../anyagentClient";
import { StudioTab } from "../navigation";
import { formatCount } from "../studioUtils";

type SessionsPageProps = {
  settings: StudioSettings;
  runs: ObservabilityRunItem[];
  selectedRun: ObservabilityRunItem | null;
  turnCount: number;
  avgInputChars: number;
  onRefresh: () => void;
  onSelectRun: (responseId: string) => void;
  onNavigate: (tab: StudioTab) => void;
};

export function SessionsPage({ settings, runs, selectedRun, turnCount, avgInputChars, onRefresh, onSelectRun, onNavigate }: SessionsPageProps) {
  return (
    <>
      <section className="section-block">
        <div className="section-title">
          <MessageSquareText size={17} />
          <h2>Session runs</h2>
          <span>{settings.sessionKey || "current session"}</span>
        </div>
        <div className="metric-grid compact-metrics">
          <Card className="metric-card">
            <Card.Content>
              <span>Runs</span>
              <strong>{formatCount(runs.length)}</strong>
              <small>{settings.agentId || "main"}</small>
            </Card.Content>
          </Card>
          <Card className="metric-card">
            <Card.Content>
              <span>Turns</span>
              <strong>{formatCount(turnCount)}</strong>
              <small>{formatCount(avgInputChars)} avg input chars</small>
            </Card.Content>
          </Card>
          <Card className="metric-card">
            <Card.Content>
              <span>Latest</span>
              <strong>{selectedRun?.status ?? "-"}</strong>
              <small>{selectedRun?.response_id ?? "No response"}</small>
            </Card.Content>
          </Card>
        </div>
      </section>

      <Card className="panel">
        <Card.Header className="panel-header">
          <div className="panel-title">
            <MessageSquareText size={18} />
            <span>Run history</span>
          </div>
          <Button size="sm" variant="secondary" onPress={onRefresh}>
            <RefreshCw size={15} />
            Refresh
          </Button>
        </Card.Header>
        <Card.Content className="panel-content">
          <div className="history-list session-history">
            {runs.length === 0 ? (
              <div className="empty-state">
                <MessageSquareText size={24} />
                <strong>Run your first session</strong>
                <p>No response runs yet for this agent/session.</p>
                <Button size="sm" variant="primary" onPress={() => onNavigate("home")}>
                  Start session
                </Button>
              </div>
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
                    <span>{run.agent_id} · {run.session_key}</span>
                  </div>
                  <p>{run.status} · {run.stream ? "stream" : "non-stream"}</p>
                  <em>{formatCount(Math.max(run.updated_at_ms - run.created_at_ms, 0))} ms</em>
                </button>
              ))
            )}
          </div>
        </Card.Content>
      </Card>
    </>
  );
}
