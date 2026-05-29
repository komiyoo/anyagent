import { useEffect, useState } from "react";
import { StudioSettings, ToolCatalog, listAvailableTools, listTools } from "../anyagentClient";
import { csvToList } from "../studioUtils";
import { useDebouncedValue } from "./useDebouncedValue";

export function useToolCatalog(settings: StudioSettings, requestedToolsText: string) {
  const [toolCatalog, setToolCatalog] = useState<ToolCatalog | null>(null);
  const [availableTools, setAvailableTools] = useState<ToolCatalog | null>(null);
  const [toolCatalogStatus, setToolCatalogStatus] = useState("Not loaded");
  const [availableToolsStatus, setAvailableToolsStatus] = useState("Not loaded");
  const debouncedRequestedTools = useDebouncedValue(requestedToolsText, 300);

  async function loadToolCatalog() {
    if (!settings.agentId) {
      return;
    }
    setToolCatalogStatus("Loading");
    try {
      const catalog = await listTools(settings, settings.agentId, csvToList(requestedToolsText));
      setToolCatalog(catalog);
      setToolCatalogStatus(`v${catalog.toolset_version}`);
    } catch (error) {
      setToolCatalog(null);
      setToolCatalogStatus(error instanceof Error ? error.message : "Load failed");
    }
  }

  async function loadAvailableTools() {
    setAvailableToolsStatus("Loading");
    try {
      const catalog = await listAvailableTools(settings);
      setAvailableTools(catalog);
      setAvailableToolsStatus(`v${catalog.toolset_version}`);
    } catch (error) {
      setAvailableTools(null);
      setAvailableToolsStatus(error instanceof Error ? error.message : "Load failed");
    }
  }

  useEffect(() => {
    void loadToolCatalog();
  }, [settings.baseUrl, settings.apiKey, settings.agentId, settings.sessionKey, debouncedRequestedTools]);

  useEffect(() => {
    void loadAvailableTools();
  }, [settings.baseUrl, settings.adminKey]);

  return {
    toolCatalog,
    availableTools,
    toolCatalogStatus,
    availableToolsStatus,
    loadToolCatalog,
    loadAvailableTools,
  };
}
