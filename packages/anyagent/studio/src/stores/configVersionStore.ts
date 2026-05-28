import { create } from "zustand";
import { persist } from "zustand/middleware";

export type AgentConfigDraftSnapshot = {
  agentId: string;
  disabledSkillPaths: string[];
  exposed: boolean;
  mcpJson: string;
  modelApiKeyEnv: string;
  modelBaseUrlEnv: string;
  modelDefault: string;
  modelProvider: string;
  sandboxMode: string;
  spawnText: string;
  toolsText: string;
};

export type AgentConfigSnapshot = {
  id: string;
  agentId: string;
  config: AgentConfigDraftSnapshot;
  createdAt: number;
  name: string;
};

type ConfigVersionStore = {
  snapshots: AgentConfigSnapshot[];
  addSnapshot: (agentId: string, config: AgentConfigDraftSnapshot) => void;
  removeSnapshot: (id: string) => void;
};

export const useConfigVersionStore = create<ConfigVersionStore>()(
  persist(
    (set) => ({
      snapshots: [],
      addSnapshot: (agentId, config) => {
        const snapshot: AgentConfigSnapshot = {
          id: crypto.randomUUID(),
          agentId,
          config,
          createdAt: Date.now(),
          name: `${agentId || "agent"} snapshot`,
        };
        set((state) => ({ snapshots: [snapshot, ...state.snapshots].slice(0, 20) }));
      },
      removeSnapshot: (id) => set((state) => ({ snapshots: state.snapshots.filter((snapshot) => snapshot.id !== id) })),
    }),
    {
      name: "anyagent.studio.config-versions.v1",
    },
  ),
);
