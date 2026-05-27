import { Button, Card, TextArea } from "@heroui/react";
import { Braces, FlaskConical, Play } from "lucide-react";
import { AgentDetail, McpServerDraft, ToolCatalog } from "../anyagentClient";
import { compactJson, formatCount, shortHash } from "../studioUtils";

type PromptsPageProps = {
  input: string;
  promptBundle: Record<string, unknown> | null;
  agentDetail: AgentDetail | null;
  selectedSkillCount: number;
  mcpDrafts: McpServerDraft[];
  toolCatalog: ToolCatalog | null;
  onInputChange: (value: string) => void;
  onPreview: () => void;
};

export function PromptsPage({
  input,
  promptBundle,
  agentDetail,
  selectedSkillCount,
  mcpDrafts,
  toolCatalog,
  onInputChange,
  onPreview,
}: PromptsPageProps) {
  return (
    <div className="main-grid">
      <Card className="panel">
        <Card.Header className="panel-header">
          <div className="panel-title">
            <FlaskConical size={18} />
            <span>Prompt preview</span>
          </div>
          <Button size="sm" variant="secondary" onPress={onPreview}>
            <Play size={16} />
            Preview
          </Button>
        </Card.Header>
        <Card.Content className="panel-content">
          <TextArea rows={4} value={input} onChange={(event) => onInputChange(event.target.value)} aria-label="Prompt preview input" />
          <pre className="json-preview prompt-preview">
            {promptBundle ? compactJson(promptBundle) : "Preview prompt assembly for the selected agent and current user input."}
          </pre>
        </Card.Content>
      </Card>

      <Card className="panel">
        <Card.Header className="panel-header">
          <div className="panel-title">
            <Braces size={18} />
            <span>Context signals</span>
          </div>
        </Card.Header>
        <Card.Content className="panel-content">
          <div className="breakdown-list">
            <div className="breakdown-row">
              <span>AGENTS.md</span>
              <strong>{shortHash(agentDetail?.agents_md?.sha256)}</strong>
            </div>
            <div className="breakdown-row">
              <span>Selected skills</span>
              <strong>{formatCount(selectedSkillCount)}</strong>
            </div>
            <div className="breakdown-row">
              <span>MCP drafts</span>
              <strong>{formatCount(mcpDrafts.length)}</strong>
            </div>
            <div className="breakdown-row">
              <span>Visible tools</span>
              <strong>{formatCount(toolCatalog?.tools.length ?? 0)}</strong>
            </div>
          </div>
        </Card.Content>
      </Card>
    </div>
  );
}
