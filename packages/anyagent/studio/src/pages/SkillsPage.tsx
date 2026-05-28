import { Button, Card, Input, TextArea } from "@heroui/react";
import { Sparkles } from "lucide-react";
import { FormEvent, useMemo, useState } from "react";
import { SkillChannel, SkillSummary } from "../anyagentClient";
import { displayText } from "../studioUtils";

type SkillsPageProps = {
  skills: SkillSummary[];
  skillChannel: SkillChannel;
  skillDirectoryName: string;
  skillPackage: string;
  skillGithubRef: string;
  skillGithubPath: string;
  skillName: string;
  skillMarkdown: string;
  skillImportStatus: string;
  skillSelection: string[];
  disabledSkillPaths: string[];
  skillSelectionStatus: string;
  skillUpdateStatus: Record<string, string>;
  onSubmitSkillInstall: (event: FormEvent<HTMLFormElement>) => void;
  onSaveSkillSelection: () => void;
  onSkillChannelChange: (value: SkillChannel) => void;
  onSkillDirectoryNameChange: (value: string) => void;
  onSkillPackageChange: (value: string) => void;
  onSkillGithubRefChange: (value: string) => void;
  onSkillGithubPathChange: (value: string) => void;
  onSkillNameChange: (value: string) => void;
  onSkillMarkdownChange: (value: string) => void;
  onToggleSkillSelection: (skill: SkillSummary, checked: boolean) => void;
  onToggleSkillEnabled: (skill: SkillSummary, enabled: boolean) => void;
  onCheckSkillUpdate: (skill: SkillSummary) => void;
  onApplySkillUpdate: (skill: SkillSummary) => void;
  skillDisableRef: (skill: SkillSummary) => string;
  skillDirectoryRef: (skill: SkillSummary) => string;
};

export function SkillsPage({
  skills,
  skillChannel,
  skillDirectoryName,
  skillPackage,
  skillGithubRef,
  skillGithubPath,
  skillName,
  skillMarkdown,
  skillImportStatus,
  skillSelection,
  disabledSkillPaths,
  skillSelectionStatus,
  skillUpdateStatus,
  onSubmitSkillInstall,
  onSaveSkillSelection,
  onSkillChannelChange,
  onSkillDirectoryNameChange,
  onSkillPackageChange,
  onSkillGithubRefChange,
  onSkillGithubPathChange,
  onSkillNameChange,
  onSkillMarkdownChange,
  onToggleSkillSelection,
  onToggleSkillEnabled,
  onCheckSkillUpdate,
  onApplySkillUpdate,
  skillDisableRef,
  skillDirectoryRef,
}: SkillsPageProps) {
  const [skillFilter, setSkillFilter] = useState("");
  const [tagFilter, setTagFilter] = useState<"all" | "selected" | "enabled" | "disabled" | "updates">("all");
  const filteredSkills = useMemo(() => {
    const needle = skillFilter.trim().toLowerCase();
    return skills.filter((skill) => {
      const directoryName = skillDirectoryRef(skill);
      const disableRef = skillDisableRef(skill);
      const skillLabel = displayText(skill.name, skill.stable_id ?? "skill");
      const isSelected = skillSelection.includes(displayText(skill.name, skill.stable_id ?? ""));
      const isDisabled = disabledSkillPaths.includes(disableRef);
      const hasUpdateStatus = Boolean(skillUpdateStatus[directoryName]);
      if (tagFilter === "selected" && !isSelected) return false;
      if (tagFilter === "enabled" && isDisabled) return false;
      if (tagFilter === "disabled" && !isDisabled) return false;
      if (tagFilter === "updates" && !hasUpdateStatus) return false;
      if (!needle) return true;
      return [skillLabel, skill.stable_id, displayText(skill.path, ""), directoryName, skillUpdateStatus[directoryName]].some((value) =>
        String(value ?? "").toLowerCase().includes(needle),
      );
    });
  }, [disabledSkillPaths, skillDirectoryRef, skillDisableRef, skillFilter, skillSelection, skillUpdateStatus, skills, tagFilter]);

  return (
    <div className="main-grid configure-grid">
      <Card className="panel wide-panel">
        <Card.Header className="panel-header">
          <div className="panel-title">
            <Sparkles size={18} />
            <span>Skills</span>
          </div>
          <div className="editor-actions">
            <span>{skillSelectionStatus}</span>
            <Button size="sm" variant="secondary" onPress={onSaveSkillSelection}>
              Save selection
            </Button>
          </div>
        </Card.Header>
        <Card.Content className="panel-content">
          <form className="skill-import" onSubmit={onSubmitSkillInstall}>
            <div className="inline-actions channel-inputs">
              <select className="native-select" aria-label="Skill channel" value={skillChannel} onChange={(event) => onSkillChannelChange(event.target.value as SkillChannel)}>
                <option value="skills.sh">skills.sh</option>
                <option value="registry">registry</option>
                <option value="github">github</option>
                <option value="local_upload">local_upload</option>
              </select>
              {skillChannel === "local_upload" ? (
                <Input aria-label="Skill directory" value={skillDirectoryName} onChange={(event) => onSkillDirectoryNameChange(event.target.value)} />
              ) : skillChannel === "github" ? (
                <>
                  <Input aria-label="GitHub repo" value={skillPackage} onChange={(event) => onSkillPackageChange(event.target.value)} />
                  <Input aria-label="GitHub ref" value={skillGithubRef} onChange={(event) => onSkillGithubRefChange(event.target.value)} />
                  <Input aria-label="GitHub skill path" value={skillGithubPath} onChange={(event) => onSkillGithubPathChange(event.target.value)} />
                  <Input aria-label="Skill name" value={skillName} onChange={(event) => onSkillNameChange(event.target.value)} />
                </>
              ) : (
                <>
                  <Input aria-label="Skill package" value={skillPackage} onChange={(event) => onSkillPackageChange(event.target.value)} />
                  <Input aria-label="Skill name" value={skillName} onChange={(event) => onSkillNameChange(event.target.value)} />
                </>
              )}
              <Button size="sm" variant="primary" type="submit">
                {skillChannel === "local_upload" ? "Import" : "Install"}
              </Button>
            </div>
            {skillChannel === "local_upload" ? (
              <TextArea aria-label="SKILL.md" rows={8} value={skillMarkdown} onChange={(event) => onSkillMarkdownChange(event.target.value)} />
            ) : null}
            <span className="status-line">{skillImportStatus}</span>
          </form>

          <div className="filter-row">
            <Input aria-label="Search skills" placeholder="Search skills by name, path, status" value={skillFilter} onChange={(event) => setSkillFilter(event.target.value)} />
            <select className="native-select" aria-label="Skill tag filter" value={tagFilter} onChange={(event) => setTagFilter(event.target.value as typeof tagFilter)}>
              <option value="all">All tags</option>
              <option value="selected">Selected</option>
              <option value="enabled">Enabled</option>
              <option value="disabled">Disabled</option>
              <option value="updates">Update checked</option>
            </select>
          </div>

          <div className="skill-list">
            {filteredSkills.length === 0 ? (
              <p className="empty">Installed skills from the selected workspace appear here.</p>
            ) : (
              filteredSkills.map((skill) => {
                const directoryName = skillDirectoryRef(skill);
                const disableRef = skillDisableRef(skill);
                const skillLabel = displayText(skill.name, skill.stable_id ?? "skill");
                return (
                  <div className="skill-row" key={`skills-tab-${skill.stable_id ?? displayText(skill.path, displayText(skill.name))}`}>
                    <input
                      aria-label={`Select ${skillLabel}`}
                      checked={skillSelection.includes(displayText(skill.name, skill.stable_id ?? ""))}
                      disabled={disabledSkillPaths.includes(disableRef)}
                      type="checkbox"
                      onChange={(event) => onToggleSkillSelection(skill, event.target.checked)}
                    />
                    <div>
                      <strong>{skillLabel}</strong>
                      <span>{displayText(skill.path, skill.stable_id ?? "")}</span>
                      {skillUpdateStatus[directoryName] ? <small>{skillUpdateStatus[directoryName]}</small> : null}
                    </div>
                    <button
                      className={`capsule-toggle ${disabledSkillPaths.includes(disableRef) ? "" : "enabled"}`}
                      type="button"
                      onClick={() => onToggleSkillEnabled(skill, disabledSkillPaths.includes(disableRef))}
                    >
                      {disabledSkillPaths.includes(disableRef) ? "Disabled" : "Enabled"}
                    </button>
                    <button className="capsule-toggle" type="button" onClick={() => onCheckSkillUpdate(skill)}>
                      Check
                    </button>
                    <button className="capsule-toggle enabled" type="button" onClick={() => onApplySkillUpdate(skill)}>
                      Update
                    </button>
                  </div>
                );
              })
            )}
          </div>
        </Card.Content>
      </Card>
    </div>
  );
}
