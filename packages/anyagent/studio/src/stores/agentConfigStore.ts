import { create } from "zustand";
import { AgentDetail } from "../anyagentClient";

type AgentConfigStore = {
  agentConfigStatus: string;
  agentCreateStatus: string;
  agentExposed: boolean;
  agentModelApiKeyEnv: string;
  agentModelBaseUrlEnv: string;
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
  setAgentModelApiKeyEnv: (value: string) => void;
  setAgentModelBaseUrlEnv: (value: string) => void;
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
  agentModelApiKeyEnv: "OPENAI_API_KEY",
  agentModelBaseUrlEnv: "OPENAI_BASE_URL",
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
  setAgentModelApiKeyEnv: (value) => set({ agentModelApiKeyEnv: value }),
  setAgentModelBaseUrlEnv: (value) => set({ agentModelBaseUrlEnv: value }),
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
      agentModelBaseUrlEnv: agentDetail?.model?.base_url_env ?? agentDetail?.model_base_url_env ?? "OPENAI_BASE_URL",
      agentModelApiKeyEnv: agentDetail?.model?.api_key_env ?? agentDetail?.model_api_key_env ?? "OPENAI_API_KEY",
      agentSandboxMode: agentDetail?.sandbox?.mode ?? agentDetail?.sandbox_mode ?? "disabled",
      agentToolsText: (agentDetail?.tools?.requested_tool_names ?? agentDetail?.requested_tool_names ?? []).join(", "),
      agentSpawnText: (agentDetail?.multiagent?.spawn_allow_agent_ids ?? []).join(", "),
    }),
}));
