import { Button, Card } from "@heroui/react";
import { Activity, MessageSquareText, Play, RefreshCw } from "lucide-react";
import { ObservabilityRunItem, StudioSettings } from "../anyagentClient";
import { StudioTab } from "../navigation";
import { formatCount, formatMs, relativeTime } from "../studioUtils";
import { CompactTable, EmptyState, StatStrip, StatusBadge, normalizeStatus } from "../components/design-system";
import type { StatItem } from "../components/design-system";

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
  const stats: StatItem[] = [
    { label: "Runs", value: formatCount(runs.length), hint: settings.agentId || "main" },
    { label: "Turns", value: formatCount(turnCount), hint: `${formatCount(avgInputChars)} avg in chars` },
    { label: "Latest", value: selectedRun?.status ?? "-", hint: selectedRun?.response_id ?? "No response" },
  ];

  const columns = [
    {
      key: "id",
      header: "Response ID",
      render: (run: ObservabilityRunItem) => (
        <div className="ds-cell-stack">
          <strong className="ds-cell-strong">{run.response_id}</strong>
          <span className="ds-cell-sub">{run.agent_id} · {run.session_key}</span>
        </div>
      ),
    },
    {
      key: "status",
      header: "Status",
      width: "110px",
      render: (run: ObservabilityRunItem) => (
        <StatusBadge status={normalizeStatus(run.effective_status || run.status)}>
          {run.status}
        </StatusBadge>
      ),
    },
    {
      key: "stream",
      header: "Mode",
      width: "90px",
      render: (run: ObservabilityRunItem) => (
        <span className="ds-cell-mono">{run.stream ? "stream" : "sync"}</span>
      ),
    },
    {
      key: "time",
      header: "Started",
      align: "right" as const,
      width: "100px",
      render: (run: ObservabilityRunItem) => (
        <span className="ds-cell-mono">{relativeTime(run.created_at_ms)}</span>
      ),
    },
    {
      key: "duration",
      header: "Duration",
      align: "right" as const,
      width: "90px",
      render: (run: ObservabilityRunItem) => (
        <span className="ds-cell-mono">{formatMs(Math.max(run.updated_at_ms - run.created_at_ms, 0))}</span>
      ),
    },
  ];

  return (
    <>
      <section className="section-block ds-obs-header">
        <div className="section-title">
          <MessageSquareText size={17} />
          <h2>Session runs</h2>
          <span>{settings.sessionKey || "current session"}</span>
        </div>
        <StatStrip stats={stats} />
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
          {runs.length === 0 ? (
            <EmptyState
              icon={<MessageSquareText size={22} />}
              title="Run your first session"
              description="No response runs yet for this agent/session."
              action={
                <Button size="sm" variant="primary" onPress={() => onNavigate("home")}>
                  <Play size={13} />
                  Start session
                </Button>
              }
            />
          ) : (
            <CompactTable
              columns={columns}
              rows={runs}
              rowKey={(run) => run.response_id}
              activeRowKey={selectedRun?.response_id ?? null}
              onRowClick={(run) => onSelectRun(run.response_id)}
            />
          )}
        </Card.Content>
      </Card>
    </>
  );
}
