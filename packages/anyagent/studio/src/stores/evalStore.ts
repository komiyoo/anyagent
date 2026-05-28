import { create } from "zustand";
import { persist } from "zustand/middleware";

export type EvaluationCase = {
  id: string;
  input: string;
  expected: string;
};

export type EvaluationDataset = {
  id: string;
  name: string;
  cases: EvaluationCase[];
  createdAt: number;
  updatedAt: number;
};

export type EvaluationCaseResult = {
  id: string;
  caseId: string;
  input: string;
  expected: string;
  actual: string;
  runId: string;
  passed: boolean;
};

export type EvaluationReport = {
  id: string;
  datasetId: string;
  datasetName: string;
  createdAt: number;
  runIds: string[];
  passRate: number;
  results: EvaluationCaseResult[];
};

export type PlaygroundResult = {
  id: string;
  kind: "agent_compare" | "prompt_variant";
  prompt: string;
  agentId: string;
  label: string;
  output: string;
  status: "running" | "passed" | "failed";
  createdAt: number;
};

type EvalStore = {
  caseInputDraft: string;
  caseExpectedDraft: string;
  datasetNameDraft: string;
  datasets: EvaluationDataset[];
  importDraft: string;
  playgroundAgents: string[];
  playgroundPrompt: string;
  promptVariants: string;
  reports: EvaluationReport[];
  selectedDatasetId: string;
  selectedRunIds: string[];
  addCase: () => void;
  createDataset: () => void;
  importDataset: () => void;
  removeCase: (datasetId: string, caseId: string) => void;
  removeDataset: (datasetId: string) => void;
  removeRunSelection: (responseId: string) => void;
  renameDataset: (datasetId: string, name: string) => void;
  saveReport: (report: EvaluationReport) => void;
  setCaseExpectedDraft: (value: string) => void;
  setCaseInputDraft: (value: string) => void;
  setDatasetNameDraft: (value: string) => void;
  setImportDraft: (value: string) => void;
  setPlaygroundAgents: (agentIds: string[]) => void;
  setPlaygroundPrompt: (value: string) => void;
  setPromptVariants: (value: string) => void;
  setSelectedDatasetId: (value: string) => void;
  toggleRunSelection: (responseId: string) => void;
  updateCase: (datasetId: string, caseId: string, patch: Partial<Pick<EvaluationCase, "input" | "expected">>) => void;
};

function newId(prefix: string) {
  return `${prefix}-${crypto.randomUUID()}`;
}

function normalizeImportedCases(raw: string): EvaluationCase[] {
  const trimmed = raw.trim();
  if (!trimmed) {
    return [];
  }
  try {
    const parsed = JSON.parse(trimmed) as unknown;
    const rows = Array.isArray(parsed) ? parsed : typeof parsed === "object" && parsed && "cases" in parsed ? (parsed as { cases?: unknown }).cases : [];
    if (Array.isArray(rows)) {
      return rows
        .map((row) => {
          if (!row || typeof row !== "object") {
            return null;
          }
          const candidate = row as Record<string, unknown>;
          const input = String(candidate.input ?? candidate.prompt ?? "").trim();
          const expected = String(candidate.expected ?? candidate.expected_output ?? candidate.output ?? "").trim();
          return input && expected ? { id: newId("case"), input, expected } : null;
        })
        .filter((row): row is EvaluationCase => Boolean(row));
    }
  } catch {
    // Fall back to line-based import below.
  }
  return trimmed
    .split(/\n+/)
    .map((line) => {
      const [input, expected] = line.split(/\s*,\s*|\s*\|\s*/);
      return input?.trim() && expected?.trim() ? { id: newId("case"), input: input.trim(), expected: expected.trim() } : null;
    })
    .filter((row): row is EvaluationCase => Boolean(row));
}

export const useEvalStore = create<EvalStore>()(
  persist(
    (set, get) => ({
      caseInputDraft: "Summarize the selected run in one sentence.",
      caseExpectedDraft: "success",
      datasetNameDraft: "Regression seeds",
      datasets: [],
      importDraft: "",
      playgroundAgents: [],
      playgroundPrompt: "Compare the tradeoffs of this agent configuration in three bullets.",
      promptVariants: "Explain the answer briefly.\nList risks before recommendations.\nReturn a JSON checklist.",
      reports: [],
      selectedDatasetId: "",
      selectedRunIds: [],
      addCase: () => {
        const input = get().caseInputDraft.trim();
        const expected = get().caseExpectedDraft.trim();
        const selectedDatasetId = get().selectedDatasetId;
        if (!input || !expected || !selectedDatasetId) {
          return;
        }
        set((state) => ({
          datasets: state.datasets.map((dataset) =>
            dataset.id === selectedDatasetId
              ? {
                  ...dataset,
                  cases: [{ id: newId("case"), input, expected }, ...dataset.cases],
                  updatedAt: Date.now(),
                }
              : dataset,
          ),
          caseInputDraft: "",
          caseExpectedDraft: "",
        }));
      },
      createDataset: () => {
        const name = get().datasetNameDraft.trim() || "Evaluation dataset";
        const dataset: EvaluationDataset = {
          id: newId("dataset"),
          name,
          cases: [],
          createdAt: Date.now(),
          updatedAt: Date.now(),
        };
        set((state) => ({ datasets: [dataset, ...state.datasets], selectedDatasetId: dataset.id }));
      },
      importDataset: () => {
        const cases = normalizeImportedCases(get().importDraft);
        if (!cases.length) {
          return;
        }
        const name = get().datasetNameDraft.trim() || "Imported dataset";
        const dataset: EvaluationDataset = {
          id: newId("dataset"),
          name,
          cases,
          createdAt: Date.now(),
          updatedAt: Date.now(),
        };
        set((state) => ({
          datasets: [dataset, ...state.datasets],
          importDraft: "",
          selectedDatasetId: dataset.id,
        }));
      },
      removeCase: (datasetId, caseId) =>
        set((state) => ({
          datasets: state.datasets.map((dataset) =>
            dataset.id === datasetId ? { ...dataset, cases: dataset.cases.filter((item) => item.id !== caseId), updatedAt: Date.now() } : dataset,
          ),
        })),
      removeDataset: (datasetId) =>
        set((state) => ({
          datasets: state.datasets.filter((dataset) => dataset.id !== datasetId),
          selectedDatasetId: state.selectedDatasetId === datasetId ? "" : state.selectedDatasetId,
        })),
      removeRunSelection: (responseId) => set((state) => ({ selectedRunIds: state.selectedRunIds.filter((id) => id !== responseId) })),
      renameDataset: (datasetId, name) =>
        set((state) => ({
          datasets: state.datasets.map((dataset) =>
            dataset.id === datasetId ? { ...dataset, name: name.trim() || "Evaluation dataset", updatedAt: Date.now() } : dataset,
          ),
        })),
      saveReport: (report) => set((state) => ({ reports: [report, ...state.reports].slice(0, 12) })),
      setCaseExpectedDraft: (value) => set({ caseExpectedDraft: value }),
      setCaseInputDraft: (value) => set({ caseInputDraft: value }),
      setDatasetNameDraft: (value) => set({ datasetNameDraft: value }),
      setImportDraft: (value) => set({ importDraft: value }),
      setPlaygroundAgents: (agentIds) => set({ playgroundAgents: agentIds }),
      setPlaygroundPrompt: (value) => set({ playgroundPrompt: value }),
      setPromptVariants: (value) => set({ promptVariants: value }),
      setSelectedDatasetId: (value) => set({ selectedDatasetId: value }),
      toggleRunSelection: (responseId) =>
        set((state) => ({
          selectedRunIds: state.selectedRunIds.includes(responseId)
            ? state.selectedRunIds.filter((id) => id !== responseId)
            : [...state.selectedRunIds, responseId],
        })),
      updateCase: (datasetId, caseId, patch) =>
        set((state) => ({
          datasets: state.datasets.map((dataset) =>
            dataset.id === datasetId
              ? {
                  ...dataset,
                  cases: dataset.cases.map((item) => (item.id === caseId ? { ...item, ...patch } : item)),
                  updatedAt: Date.now(),
                }
              : dataset,
          ),
        })),
    }),
    {
      name: "anyagent.studio.evaluations.v1",
      partialize: (state) => ({
        datasets: state.datasets,
        playgroundAgents: state.playgroundAgents,
        playgroundPrompt: state.playgroundPrompt,
        promptVariants: state.promptVariants,
        reports: state.reports,
        selectedDatasetId: state.selectedDatasetId,
        selectedRunIds: state.selectedRunIds,
      }),
    },
  ),
);
