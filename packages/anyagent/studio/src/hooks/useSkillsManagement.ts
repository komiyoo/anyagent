import { FormEvent, useEffect, useState } from "react";
import {
  SkillChannel,
  SkillSummary,
  StudioSettings,
  applyAgentSkillUpdate,
  checkAgentSkillUpdate,
  importAgentSkill,
  installAgentSkill,
  updateAgentSkills,
} from "../anyagentClient";
import { sampleSkillMarkdown } from "../sampleData";
import { displayText } from "../studioUtils";

type UseSkillsManagementOptions = {
  onFilesRefresh: () => Promise<void> | void;
  onWorkspaceRefresh: () => Promise<void> | void;
};

export function useSkillsManagement(
  settings: StudioSettings,
  skills: SkillSummary[],
  options: UseSkillsManagementOptions,
) {
  const [skillDirectoryName, setSkillDirectoryName] = useState("sales-discovery");
  const [skillMarkdown, setSkillMarkdown] = useState(sampleSkillMarkdown);
  const [skillImportStatus, setSkillImportStatus] = useState("Ready");
  const [skillChannel, setSkillChannel] = useState<SkillChannel>("skills.sh");
  const [skillPackage, setSkillPackage] = useState("vercel-labs/agent-skills");
  const [skillName, setSkillName] = useState("web-design-guidelines");
  const [skillGithubRef, setSkillGithubRef] = useState("main");
  const [skillGithubPath, setSkillGithubPath] = useState("");
  const [skillSelection, setSkillSelection] = useState<string[]>([]);
  const [disabledSkillPaths, setDisabledSkillPaths] = useState<string[]>([]);
  const [skillUpdateStatus, setSkillUpdateStatus] = useState<Record<string, string>>({});
  const [skillSelectionStatus, setSkillSelectionStatus] = useState("Ready");

  useEffect(() => {
    setSkillSelection(
      skills
        .filter((skill) => skill.selected)
        .map((skill) => displayText(skill.name, skill.stable_id ?? ""))
        .filter(Boolean),
    );
    setDisabledSkillPaths(
      skills
        .filter((skill) => skill.enabled === false)
        .map((skill) => (typeof skill.path === "string" ? skill.path : skill.stable_id ?? ""))
        .filter(Boolean),
    );
  }, [skills]);

  async function submitSkillInstall(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSkillImportStatus(skillChannel === "local_upload" ? "Importing" : "Installing");
    try {
      const installed =
        skillChannel === "local_upload"
          ? await importAgentSkill(settings, settings.agentId, skillDirectoryName, skillMarkdown)
          : await installAgentSkill(settings, settings.agentId, skillChannel, skillPackage, skillName, undefined, false, {
              repo: skillPackage,
              ref: skillGithubRef,
              path: skillGithubPath || skillName,
            });
      setSkillImportStatus(`${skillChannel === "local_upload" ? "Imported" : "Installed"} ${installed.name}`);
      await options.onWorkspaceRefresh();
    } catch (error) {
      setSkillImportStatus(error instanceof Error ? error.message : "Skill channel failed");
    }
  }

  function toggleSkillSelection(skill: SkillSummary, checked: boolean) {
    const name = displayText(skill.name, skill.stable_id ?? "");
    if (!name) {
      return;
    }
    setSkillSelection((current) =>
      checked ? Array.from(new Set([...current, name])) : current.filter((item) => item !== name),
    );
  }

  function skillDisableRef(skill: SkillSummary): string {
    return typeof skill.path === "string" && skill.path.trim() ? skill.path : skill.stable_id ?? "";
  }

  function skillDirectoryRef(skill: SkillSummary): string {
    const path = typeof skill.path === "string" ? skill.path : "";
    const segments = path.split("/").filter(Boolean);
    const skillMdIndex = segments.lastIndexOf("SKILL.md");
    if (skillMdIndex > 0) {
      return segments[skillMdIndex - 1];
    }
    return displayText(skill.name, skill.stable_id ?? "");
  }

  function toggleSkillEnabled(skill: SkillSummary, enabled: boolean) {
    const ref = skillDisableRef(skill);
    if (!ref) {
      return;
    }
    setDisabledSkillPaths((current) => (enabled ? current.filter((item) => item !== ref) : Array.from(new Set([...current, ref]))));
    if (!enabled) {
      const name = displayText(skill.name, skill.stable_id ?? "");
      setSkillSelection((current) => current.filter((item) => item !== name && item !== skill.stable_id));
    }
  }

  async function saveSkillSelection() {
    setSkillSelectionStatus("Saving");
    try {
      const updated = await updateAgentSkills(settings, settings.agentId, skillSelection);
      setSkillSelectionStatus(`Saved ${updated.agent.skills?.default_selected?.length ?? 0} selected`);
      await options.onWorkspaceRefresh();
      await options.onFilesRefresh();
    } catch (error) {
      setSkillSelectionStatus(error instanceof Error ? error.message : "Save failed");
    }
  }

  async function checkSkillUpdate(skill: SkillSummary) {
    const directoryName = skillDirectoryRef(skill);
    if (!directoryName) {
      return;
    }
    setSkillUpdateStatus((current) => ({ ...current, [directoryName]: "Checking" }));
    try {
      const check = await checkAgentSkillUpdate(settings, settings.agentId, directoryName);
      const status = check.updatable
        ? check.update_available
          ? `Update available (${check.channel})`
          : `Up to date (${check.channel})`
        : check.reason || "Not updatable";
      setSkillUpdateStatus((current) => ({ ...current, [directoryName]: status }));
    } catch (error) {
      setSkillUpdateStatus((current) => ({ ...current, [directoryName]: error instanceof Error ? error.message : "Check failed" }));
    }
  }

  async function applySkillUpdate(skill: SkillSummary) {
    const directoryName = skillDirectoryRef(skill);
    if (!directoryName) {
      return;
    }
    setSkillUpdateStatus((current) => ({ ...current, [directoryName]: "Updating" }));
    try {
      const updated = await applyAgentSkillUpdate(settings, settings.agentId, directoryName);
      setSkillUpdateStatus((current) => ({ ...current, [directoryName]: `Updated ${updated.name}` }));
      await options.onWorkspaceRefresh();
    } catch (error) {
      setSkillUpdateStatus((current) => ({ ...current, [directoryName]: error instanceof Error ? error.message : "Update failed" }));
    }
  }

  return {
    disabledSkillPaths,
    setDisabledSkillPaths,
    skillChannel,
    skillDirectoryName,
    skillGithubPath,
    skillGithubRef,
    skillImportStatus,
    skillMarkdown,
    skillName,
    skillPackage,
    skillSelection,
    skillSelectionStatus,
    skillUpdateStatus,
    applySkillUpdate,
    checkSkillUpdate,
    saveSkillSelection,
    setSkillChannel,
    setSkillDirectoryName,
    setSkillGithubPath,
    setSkillGithubRef,
    setSkillMarkdown,
    setSkillName,
    setSkillPackage,
    skillDirectoryRef,
    skillDisableRef,
    submitSkillInstall,
    toggleSkillEnabled,
    toggleSkillSelection,
  };
}
