import { useEffect, useState } from "react";
import { AgentDetail, AgentSummary, SkillSummary, StudioSettings, getAdminAgent, getAgent, listAgents, listSkills } from "../anyagentClient";

export function useWorkspaceCatalog(settings: StudioSettings) {
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [agentDetail, setAgentDetail] = useState<AgentDetail | null>(null);
  const [skills, setSkills] = useState<SkillSummary[]>([]);
  const [status, setStatus] = useState("idle");

  async function refresh() {
    setStatus("loading");
    try {
      const nextAgents = await listAgents(settings, true);
      setAgents(nextAgents);
      const nextAgentId = settings.agentId || nextAgents[0]?.agent_id || "";
      let detail: AgentDetail | null = null;
      try {
        detail = await getAgent(settings, nextAgentId);
      } catch {
        detail = await getAdminAgent(settings, nextAgentId);
      }
      const nextSkills = await listSkills(settings, nextAgentId);
      setAgentDetail(detail);
      setSkills(nextSkills);
      setStatus("ready");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "catalog failed");
      setAgents([]);
      setAgentDetail(null);
      setSkills([]);
    }
  }

  useEffect(() => {
    void refresh();
  }, [settings.baseUrl, settings.apiKey, settings.adminKey, settings.agentId]);

  return { agents, agentDetail, skills, status, refresh };
}
