import { Button, Card } from "@heroui/react";
import { Braces, Bug, Play } from "lucide-react";
import { StudioDebugEvent } from "../anyagentClient";
import { compactJson, eventSummary } from "../studioUtils";

type DebugPageProps = {
  stageEvents: StudioDebugEvent[];
  promptBundle: Record<string, unknown> | null;
  onPreviewPrompt: () => void;
};

export function DebugPage({ stageEvents, promptBundle, onPreviewPrompt }: DebugPageProps) {
  return (
    <div className="main-grid">
      <Card className="panel">
        <Card.Header className="panel-header">
          <div className="panel-title">
            <Bug size={18} />
            <span>Stage events</span>
          </div>
        </Card.Header>
        <Card.Content className="panel-content">
          <div className="event-list">
            {stageEvents.length === 0 ? (
              <p className="empty">Run a request, then replay tool and prompt events.</p>
            ) : (
              stageEvents.map((event, index) => {
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
