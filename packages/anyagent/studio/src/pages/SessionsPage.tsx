import { Button, Card } from "@heroui/react";
import { Activity, MessageSquareText, Play, RefreshCw } from "lucide-react";
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
  onCheckStatus: (responseId: string) => void;
  onNavigate: (tab: StudioTab) => void;
};

export function SessionsPage({ settings, runs, selectedRun, turnCount, avgInputChars, onRefresh, onSelectRun, onCheckStatus, onNavigate }: SessionsPageProps) {
  return (
    <>
      <section className="section-block">
        <div className="section-title">
          <MessageSquareText size={17} />
          <h2>Session runs</h2>
          <span>{settings.sessionKey || "current session"}</span>
        </div>
        <div className="stat-strip">
          <span className="stat">
            <span className="stat-label">Runs</span>
            <span className="stat-value">{formatCount(runs.length)}</span>
            <span className="stat-label">{settings.agentId || "main"}</span>
          </span>
          <span className="stat">
            <span className="stat-label">Turns</span>
            <span className="stat-value">{formatCount(turnCount)}</span>
            <span className="stat-label">{formatCount(avgInputChars)} avg in chars</span>
          </span>
          <span className="stat">
            <span className="stat-label">Latest</span>
            <span className="stat-value">{selectedRun?.status ?? "-"}</span>
            <span className="stat-label">{selectedRun?.response_id ?? "No response"}</span>
          </span>
        </div>
      </section>

      <Card className="panel">
        <Card.Header className="panel-header">
          <div className="panel-title">
            <MessageSquareText size={18} />
            <span>Run history</span>
          </div>
          <div className="editor-actions">
            <Button
              size="sm"
              variant="secondary"
              isDisabled={!selectedRun}
              onPress={() => selectedRun && onCheckStatus(selectedRun.response_id)}
            >
              <Activity size={15} />
              Sync status
            </Button>
            <Button size="sm" variant="secondary" onPress={onRefresh}>
              <RefreshCw size={15} />
              Refresh
            </Button>
          </div>
        </Card.Header>
        <Card.Content className="panel-content">
          <div className="history-list session-history">
            {runs.length === 0 ? (
              <div className="empty-state">
                <MessageSquareText size={24} />
                <strong>Run your first session</strong>
                <p>No response runs yet for this agent/session.</p>
                <Button size="sm" variant="primary" onPress={() => onNavigate("home")}>
                  <Play size={13} />
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
