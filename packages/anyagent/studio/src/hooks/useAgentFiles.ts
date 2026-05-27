import { useEffect, useState } from "react";
import {
  AgentFileKind,
  AgentWorkspaceFile,
  StudioSettings,
  listAgentFiles,
  updateAgentFile,
} from "../anyagentClient";
import { fileByKind, fileLabels } from "../studioUtils";

const DEFAULT_FILE_KINDS: AgentFileKind[] = ["agents_md", "agent_yaml", "mcp_json"];

type UseAgentFilesOptions = {
  onSaved?: () => Promise<void> | void;
};

export function useAgentFiles(settings: StudioSettings, options: UseAgentFilesOptions = {}) {
  const [agentFiles, setAgentFiles] = useState<AgentWorkspaceFile[]>([]);
  const [activeFileKind, setActiveFileKind] = useState<AgentFileKind>("agents_md");
  const [editorText, setEditorText] = useState("");
  const [enabledFileKinds, setEnabledFileKinds] = useState<AgentFileKind[]>(DEFAULT_FILE_KINDS);
  const [saveStatus, setSaveStatus] = useState("Not loaded");

  async function loadAgentFiles() {
    if (!settings.agentId) {
      return;
    }
    setSaveStatus("Loading files");
    try {
      const files = await listAgentFiles(settings, settings.agentId);
      setAgentFiles(files);
      const active = fileByKind(files, activeFileKind) ?? files[0];
      setEditorText(active?.text ?? "");
      setSaveStatus("Ready");
    } catch (error) {
      setAgentFiles([]);
      setEditorText("");
      setSaveStatus(error instanceof Error ? error.message : "Load failed");
    }
  }

  async function saveActiveFile() {
    if (!enabledFileKinds.includes(activeFileKind)) {
      setSaveStatus(`${fileLabels[activeFileKind]} is disabled in Studio`);
      return;
    }
    const current = fileByKind(agentFiles, activeFileKind);
    setSaveStatus("Saving");
    try {
      const updated = await updateAgentFile(settings, settings.agentId, activeFileKind, editorText, current?.sha256);
      setAgentFiles((files) => {
        const without = files.filter((file) => file.kind !== activeFileKind);
        return [...without, updated].sort((left, right) => left.kind.localeCompare(right.kind));
      });
      setEditorText(updated.text ?? "");
      setSaveStatus(`Saved ${fileLabels[activeFileKind]}`);
      await options.onSaved?.();
    } catch (error) {
      setSaveStatus(error instanceof Error ? error.message : "Save failed");
    }
  }

  function switchActiveFile(kind: AgentFileKind) {
    setActiveFileKind(kind);
    setEditorText(fileByKind(agentFiles, kind)?.text ?? "");
  }

  function toggleFileKind(kind: AgentFileKind) {
    setEnabledFileKinds((current) =>
      current.includes(kind) ? current.filter((item) => item !== kind) : Array.from(new Set([...current, kind])),
    );
  }

  useEffect(() => {
    void loadAgentFiles();
  }, [settings.baseUrl, settings.adminKey, settings.agentId]);

  return {
    agentFiles,
    activeFileKind,
    editorText,
    enabledFileKinds,
    saveStatus,
    loadAgentFiles,
    saveActiveFile,
    setAgentFiles,
    setEditorText,
    switchActiveFile,
    toggleFileKind,
  };
}
