import { useEffect, useMemo, useState } from "react";
import {
  AgentFileKind,
  AgentWorkspaceFile,
  McpServerDraft,
  StudioSettings,
  buildMcpJson,
  parseMcpDrafts,
  updateAgentFile,
} from "../anyagentClient";
import { sampleMcpDrafts } from "../sampleData";
import { fileByKind } from "../studioUtils";

type UseMcpDraftsOptions = {
  activeFileKind: AgentFileKind;
  agentFiles: AgentWorkspaceFile[];
  onFilesChange: (updater: (files: AgentWorkspaceFile[]) => AgentWorkspaceFile[]) => void;
  onEditorTextChange: (value: string) => void;
  onSaved?: () => Promise<void> | void;
};

export function useMcpDrafts(settings: StudioSettings, options: UseMcpDraftsOptions) {
  const [mcpStatus, setMcpStatus] = useState("Draft ready");
  const [mcpDrafts, setMcpDrafts] = useState<McpServerDraft[]>(sampleMcpDrafts);
  const [mcpDraftsEditable, setMcpDraftsEditable] = useState(true);
  const mcpJson = useMemo(() => buildMcpJson(mcpDrafts), [mcpDrafts]);

  useEffect(() => {
    const mcpFile = fileByKind(options.agentFiles, "mcp_json");
    if (mcpFile?.text) {
      try {
        const drafts = parseMcpDrafts(mcpFile.text);
        if (drafts.length > 0) {
          setMcpDrafts(drafts);
          setMcpStatus(`Loaded ${drafts.length} server${drafts.length === 1 ? "" : "s"}`);
        } else {
          setMcpDrafts([]);
          setMcpStatus("Loaded empty mcp.json");
        }
        setMcpDraftsEditable(true);
      } catch (error) {
        setMcpStatus(error instanceof Error ? `mcp.json parse failed: ${error.message}` : "mcp.json parse failed");
        setMcpDraftsEditable(false);
      }
    } else if (mcpFile?.exists === false) {
      setMcpDrafts([]);
      setMcpStatus("No mcp.json");
      setMcpDraftsEditable(true);
    }
  }, [options.agentFiles]);

  function updateMcpDraft(index: number, patch: Partial<McpServerDraft>) {
    setMcpDrafts((current) => current.map((item, itemIndex) => (itemIndex === index ? { ...item, ...patch } : item)));
  }

  function addMcpDraft() {
    setMcpDrafts((current) => [
      ...current,
      {
        name: `server-${current.length + 1}`,
        enabled: true,
        transport: "streamable_http",
        url: "",
        command: "",
        credentialId: "",
      },
    ]);
  }

  function removeMcpDraft(index: number) {
    setMcpDrafts((current) => current.filter((_, itemIndex) => itemIndex !== index));
  }

  async function saveMcpDrafts() {
    if (!mcpDraftsEditable) {
      setMcpStatus("Fix mcp.json in source editor before form save");
      return;
    }
    const current = fileByKind(options.agentFiles, "mcp_json");
    setMcpStatus("Saving");
    try {
      const updated = await updateAgentFile(settings, settings.agentId, "mcp_json", `${mcpJson}\n`, current?.sha256);
      options.onFilesChange((files) => {
        const without = files.filter((file) => file.kind !== "mcp_json");
        return [...without, updated].sort((left, right) => left.kind.localeCompare(right.kind));
      });
      if (options.activeFileKind === "mcp_json") {
        options.onEditorTextChange(updated.text ?? "");
      }
      setMcpStatus("Saved mcp.json");
      await options.onSaved?.();
    } catch (error) {
      setMcpStatus(error instanceof Error ? error.message : "Save failed");
    }
  }

  return {
    mcpStatus,
    mcpDrafts,
    mcpDraftsEditable,
    mcpJson,
    addMcpDraft,
    removeMcpDraft,
    saveMcpDrafts,
    updateMcpDraft,
  };
}
