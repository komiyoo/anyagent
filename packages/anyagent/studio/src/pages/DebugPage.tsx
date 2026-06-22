import { Button, Card, Chip, Input } from "@heroui/react";
import { Braces, Bug, Play, Radio } from "lucide-react";
import { useState } from "react";
import { StudioDebugEvent } from "../anyagentClient";
import { compactJson, eventSummary, eventType } from "../studioUtils";
import { CollapsibleSection, EmptyState, StatStrip } from "../components/design-system";
import type { StatItem } from "../components/design-system";

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
  const [eventFilter, setEventFilter] = useState("");
  const filterNeedle = eventFilter.trim().toLowerCase();
  const filteredEvents = filterNeedle
    ? displayedEvents.filter((event) => {
        const summary = eventSummary(event);
        const type = eventType(event);
        return [summary.title, summary.detail, summary.meta, type].some((value) =>
          String(value ?? "").toLowerCase().includes(filterNeedle),
        );
      })
    : displayedEvents;
  const toolEvents = filteredEvents.filter((event) => {
    const type = eventType(event);
    return type === "anyagent.tool.planned" || type === "anyagent.tool.result";
  }).length;
  const stats: StatItem[] = [
    { label: "Events", value: filteredEvents.length, hint: filterNeedle ? `of ${displayedEvents.length}` : undefined },
    { label: "Tool calls", value: toolEvents },
    { label: "Stream", value: tailing ? "live" : "stage", tone: tailing ? "accent" : "default" },
    { label: "Response", value: activeResponseId ? activeResponseId.slice(0, 8) : "-" },
  ];

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
          {displayedEvents.length > 0 ? <StatStrip stats={stats} className="ds-debug-stats" /> : null}
          {displayedEvents.length > 0 ? (
            <div className="filter-row">
              <Input
                aria-label="Search debug events"
                placeholder="Search events by type, title, or payload"
                value={eventFilter}
                onChange={(event) => setEventFilter(event.target.value)}
              />
            </div>
          ) : null}
          <div className="event-list">
            {displayedEvents.length === 0 ? (
              <EmptyState
                compact
                icon={<Bug size={18} />}
                title={tailing ? "Waiting for streamed events" : "No stage events"}
                description={tailing
                  ? "Waiting for streamed events from the selected response."
                  : "Run a request, then replay tool and prompt events."}
              />
            ) : filteredEvents.length === 0 ? (
              <EmptyState
                compact
                icon={<Bug size={18} />}
                title="No matching events"
                description={`No events match "${eventFilter}". Try a different search term.`}
              />
            ) : (
              filteredEvents.map((event, index) => {
                const summary = eventSummary(event);
                return (
                  <CollapsibleSection
                    key={`${event.seq}-${index}`}
                    title={summary.title}
                    count={summary.meta}
                    defaultOpen={index < 3}
                  >
                    <pre className="ds-event-json">{summary.detail}</pre>
                  </CollapsibleSection>
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
