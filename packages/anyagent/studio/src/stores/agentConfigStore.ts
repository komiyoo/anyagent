import { create } from "zustand";
import { AgentDetail } from "../anyagentClient";

type AgentConfigStore = {
  agentConfigStatus: string;
  agentCreateStatus: string;
  agentExposed: boolean;
  agentModelDefault: string;
  agentModelProvider: string;
  agentSandboxMode: string;
  agentSpawnText: string;
  agentToolsText: string;
  newAgentId: string;
  newAgentInstructions: string;
  newAgentTools: string;
  setAgentConfigStatus: (value: string) => void;
  setAgentCreateStatus: (value: string) => void;
  setAgentExposed: (value: boolean) => void;
  setAgentModelDefault: (value: string) => void;
  setAgentModelProvider: (value: string) => void;
  setAgentSandboxMode: (value: string) => void;
  setAgentSpawnText: (value: string) => void;
  setAgentToolsText: (value: string) => void;
  setNewAgentId: (value: string) => void;
  setNewAgentInstructions: (value: string) => void;
  setNewAgentTools: (value: string) => void;
  syncFromAgentDetail: (agentDetail: AgentDetail | null, fallbackModel: string) => void;
};

export const useAgentConfigStore = create<AgentConfigStore>((set) => ({
  agentConfigStatus: "Ready",
  agentCreateStatus: "Ready",
  agentExposed: true,
  agentModelDefault: "",
  agentModelProvider: "openai",
  agentSandboxMode: "disabled",
  agentSpawnText: "",
  agentToolsText: "",
  newAgentId: "sales-agent",
  newAgentInstructions: "你是一个面向业务团队的 AnyAgent agent。",
  newAgentTools: "",
  setAgentConfigStatus: (value) => set({ agentConfigStatus: value }),
  setAgentCreateStatus: (value) => set({ agentCreateStatus: value }),
  setAgentExposed: (value) => set({ agentExposed: value }),
  setAgentModelDefault: (value) => set({ agentModelDefault: value }),
  setAgentModelProvider: (value) => set({ agentModelProvider: value }),
  setAgentSandboxMode: (value) => set({ agentSandboxMode: value }),
  setAgentSpawnText: (value) => set({ agentSpawnText: value }),
  setAgentToolsText: (value) => set({ agentToolsText: value }),
  setNewAgentId: (value) => set({ newAgentId: value }),
  setNewAgentInstructions: (value) => set({ newAgentInstructions: value }),
  setNewAgentTools: (value) => set({ newAgentTools: value }),
  syncFromAgentDetail: (agentDetail, fallbackModel) =>
    set({
      agentExposed: agentDetail?.exposed ?? true,
      agentModelDefault: agentDetail?.model?.default ?? agentDetail?.model_default ?? fallbackModel,
      agentModelProvider: agentDetail?.model?.provider ?? agentDetail?.model_provider ?? "openai",
      agentSandboxMode: agentDetail?.sandbox?.mode ?? agentDetail?.sandbox_mode ?? "disabled",
      agentToolsText: (agentDetail?.tools?.requested_tool_names ?? agentDetail?.requested_tool_names ?? []).join(", "),
      agentSpawnText: (agentDetail?.multiagent?.spawn_allow_agent_ids ?? []).join(", "),
    }),
}));
