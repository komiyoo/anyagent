import { Button, Chip } from "@heroui/react";
import { ToolCatalog } from "../../anyagentClient";
import { csvToList } from "../../studioUtils";

type ToolCatalogSectionProps = {
  toolCatalog: ToolCatalog | null;
  toolCatalogStatus?: string;
  availableTools: ToolCatalog | null;
  availableToolsStatus?: string;
  requestedToolsText: string;
  onLoadToolCatalog: () => void;
  onLoadAvailableTools: () => void;
  onToggleRequestedTool: (name: string) => void;
  showEffectiveTools?: boolean;
  showAvailableTools?: boolean;
};

export function ToolCatalogSection({
  toolCatalog,
  toolCatalogStatus,
  availableTools,
  availableToolsStatus,
  requestedToolsText,
  onLoadToolCatalog,
  onLoadAvailableTools,
  onToggleRequestedTool,
  showEffectiveTools = true,
  showAvailableTools = true,
}: ToolCatalogSectionProps) {
  const requestedTools = csvToList(requestedToolsText);

  return (
    <div className="tool-catalog">
      {showEffectiveTools ? (
        <>
          <div className="subsection-heading">
            <span>Effective tools</span>
            <Button size="sm" variant="secondary" onPress={onLoadToolCatalog}>
              Refresh
            </Button>
            {toolCatalogStatus ? <em>{toolCatalogStatus}</em> : null}
          </div>
          <div className="tool-list">
            {!toolCatalog || toolCatalog.tools.length === 0 ? (
              <p className="empty">No tools are currently visible to this agent.</p>
            ) : (
              toolCatalog.tools.map((tool) => (
                <article className="tool-row" key={`effective-${tool.name}`}>
                  <div>
                    <strong>{tool.name}</strong>
                    <span>{tool.description || "No description"}</span>
                  </div>
                  <Chip size="sm" variant="soft" color={tool.kind === "command" ? "accent" : "default"}>
                    {tool.kind || tool.reason || "tool"}
                  </Chip>
                </article>
              ))
            )}
          </div>
        </>
      ) : null}
      {showAvailableTools ? (
        <>
          <div className="subsection-heading">
            <span>Available tools</span>
            <Button size="sm" variant="secondary" onPress={onLoadAvailableTools}>
              Refresh
            </Button>
            {availableToolsStatus ? <em>{availableToolsStatus}</em> : null}
          </div>
          <div className="tool-list">
            {!availableTools || availableTools.tools.length === 0 ? (
              <p className="empty">No registered tools found.</p>
            ) : (
              availableTools.tools.map((tool) => (
                <article className="tool-row" key={`available-${tool.name}`}>
                  <div>
                    <strong>{tool.name}</strong>
                    <span>{tool.description || "No description"}</span>
                  </div>
                  <button
                    className={`capsule-toggle ${requestedTools.includes(tool.name) ? "enabled" : ""}`}
                    type="button"
                    onClick={() => onToggleRequestedTool(tool.name)}
                  >
                    {requestedTools.includes(tool.name) ? "Enabled" : "Disabled"}
                  </button>
                </article>
              ))
            )}
          </div>
        </>
      ) : null}
    </div>
  );
}
