import { Button, Card, Chip } from "@heroui/react";
import { Braces, Bug, Play, Radio } from "lucide-react";
import { StudioDebugEvent } from "../anyagentClient";
import { compactJson, eventSummary } from "../studioUtils";

type DebugPageProps = {
  stageEvents: StudioDebugEvent[];
  promptBundle: Record<string, unknown> | null;
  activeResponseId: string;
  liveEvents: StudioDebugEvent[];
  tailing: boolean;
  streamStatus: string;
  onToggleTail: () => void;
  onPreviewPrompt: () => void;
};

export function DebugPage({
  stageEvents,
  promptBundle,
  activeResponseId,
  liveEvents,
  tailing,
  streamStatus,
  onToggleTail,
  onPreviewPrompt,
}: DebugPageProps) {
  const displayedEvents = tailing && liveEvents.length ? liveEvents : stageEvents;
  return (
    <div className="main-grid">
      <Card className="panel">
        <Card.Header className="panel-header">
          <div className="panel-title">
            <Bug size={18} />
            <span>{tailing ? "Live events" : "Stage events"}</span>
          </div>
          <div className="editor-actions">
            {tailing ? (
              <Chip size="sm" variant="soft" color={streamStatus === "live" ? "success" : "warning"}>
                {streamStatus}
              </Chip>
            ) : null}
            <Button size="sm" variant={tailing ? "primary" : "secondary"} isDisabled={!activeResponseId} onPress={onToggleTail}>
              <Radio size={14} />
              {tailing ? "Stop tail" : "Live tail"}
            </Button>
          </div>
        </Card.Header>
        <Card.Content className="panel-content">
          <div className="event-list">
            {displayedEvents.length === 0 ? (
              <p className="empty">
                {tailing
                  ? "Waiting for streamed events from the selected response."
                  : "Run a request, then replay tool and prompt events."}
              </p>
            ) : (
              displayedEvents.map((event, index) => {
                const summary = eventSummary(event);
                return (
                  <article className="timeline-event" key={`${event.seq}-${index}`}>
                    <div>
                      <strong>{summary.title}</strong>
                      <span>{summary.meta}</span>
                    </div>
                    <pre>{summary.detail}</pre>
                  </article>
                );
              })
            )}
          </div>
        </Card.Content>
      </Card>

      <Card className="panel">
        <Card.Header className="panel-header">
          <div className="panel-title">
            <Braces size={18} />
            <span>Prompt bundle</span>
          </div>
          <Button size="sm" variant="secondary" onPress={onPreviewPrompt}>
            <Play size={16} />
            Preview
          </Button>
        </Card.Header>
        <Card.Content className="panel-content">
          <pre className="json-preview">
            {promptBundle ? compactJson(promptBundle) : "Preview the rendered AGENTS.md, skill, MCP and tool context bundle."}
          </pre>
        </Card.Content>
      </Card>
    </div>
  );
}
