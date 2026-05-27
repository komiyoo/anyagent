import { Button, Card, Input } from "@heroui/react";
import { Cable } from "lucide-react";
import { McpServerDraft } from "../anyagentClient";

type McpPageProps = {
  drafts: McpServerDraft[];
  status: string;
  editable: boolean;
  onAddDraft: () => void;
  onRemoveDraft: (index: number) => void;
  onSaveDrafts: () => void;
  onUpdateDraft: (index: number, patch: Partial<McpServerDraft>) => void;
};

export function McpPage({ drafts, status, editable, onAddDraft, onRemoveDraft, onSaveDrafts, onUpdateDraft }: McpPageProps) {
  return (
    <Card className="panel wide-panel">
      <Card.Header className="panel-header">
        <div className="panel-title">
          <Cable size={18} />
          <span>MCP configuration</span>
        </div>
        <div className="editor-actions">
          <span>{status}</span>
          <Button size="sm" variant="secondary" onPress={onAddDraft}>
            Add
          </Button>
          <Button size="sm" variant="primary" isDisabled={!editable} onPress={onSaveDrafts}>
            Save mcp.json
          </Button>
        </div>
      </Card.Header>
      <Card.Content className="panel-content">
        <div className="mcp-editor">
          {drafts.map((draft, index) => (
            <div className="mcp-row" key={`mcp-tab-${draft.name}-${index}`}>
              <button
                className={`capsule-toggle ${draft.enabled ? "enabled" : ""}`}
                type="button"
                onClick={() => onUpdateDraft(index, { enabled: !draft.enabled })}
              >
                {draft.enabled ? "Enabled" : "Disabled"}
              </button>
              <Input aria-label="Name" value={draft.name} onChange={(event) => onUpdateDraft(index, { name: event.target.value })} />
              <select
                className="native-select"
                aria-label="Transport"
                value={draft.transport}
                onChange={(event) => onUpdateDraft(index, { transport: event.target.value as McpServerDraft["transport"] })}
              >
                <option value="streamable_http">streamable_http</option>
                <option value="sse">sse</option>
                <option value="stdio">stdio</option>
              </select>
              <Input aria-label="URL" value={draft.url} onChange={(event) => onUpdateDraft(index, { url: event.target.value })} />
              <Input aria-label="Credential" value={draft.credentialId} onChange={(event) => onUpdateDraft(index, { credentialId: event.target.value })} />
              <Input aria-label="Command" value={draft.command} onChange={(event) => onUpdateDraft(index, { command: event.target.value })} />
              <Button size="sm" variant="secondary" onPress={() => onRemoveDraft(index)}>
                Remove
              </Button>
            </div>
          ))}
        </div>
      </Card.Content>
    </Card>
  );
}
