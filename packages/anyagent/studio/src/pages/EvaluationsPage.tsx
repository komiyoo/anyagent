import { Button, Card, Chip, Input, TextArea } from "@heroui/react";
import { BarChart3, Bug, Database, Download, GitCompareArrows, Play, Plus, Timer, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { AgentSummary, ChatMessage, ObservabilityRunItem, StudioSettings, runChat } from "../anyagentClient";
import { StudioTab } from "../navigation";
import { EvaluationCaseResult, EvaluationDataset, EvaluationReport, PlaygroundResult, useEvalStore } from "../stores/evalStore";
import { compactJson, downloadFile, exportFilename, formatCount, formatMs, toCsv } from "../studioUtils";
import { CompactTable, EmptyState, StatStrip, StatusBadge, normalizeStatus } from "../components/design-system";
import type { StatItem } from "../components/design-system";

type EvaluationsPageProps = {
  agents: AgentSummary[];
  runs: ObservabilityRunItem[];
  settings: StudioSettings;
  totalLatency: number | null;
  errorCount: number;
  onInspectRun: (responseId: string) => void;
  onNavigate: (tab: StudioTab) => void;
};

function runSignal(run: ObservabilityRunItem) {
  return [
    run.effective_status,
    run.status,
    run.agent_id,
    run.session_key,
    run.response_id,
    run.stream ? "stream" : "non-stream",
  ]
    .filter(Boolean)
    .join(" ");
}

function expectedMatches(expected: string, actual: string) {
  const actualLower = actual.toLowerCase();
  return expected
    .split(/\n|,/)
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean)
    .every((item) => actualLower.includes(item));
}

function makeReport(dataset: EvaluationDataset, runs: ObservabilityRunItem[]): EvaluationReport {
  const runIds = runs.map((run) => run.response_id);
  const results: EvaluationCaseResult[] = dataset.cases.map((item, index) => {
    const run = runs[index % Math.max(runs.length, 1)];
    const actual = run ? runSignal(run) : "No run selected";
    const passed = run ? expectedMatches(item.expected, actual) : false;
    return {
      id: crypto.randomUUID(),
      caseId: item.id,
      input: item.input,
      expected: item.expected,
      actual,
      runId: run?.response_id ?? "",
      passed,
    };
  });
  const passedCount = results.filter((result) => result.passed).length;
  return {
    id: crypto.randomUUID(),
    datasetId: dataset.id,
    datasetName: dataset.name,
    createdAt: Date.now(),
    runIds,
    passRate: results.length ? Math.round((passedCount / results.length) * 100) : 0,
    results,
  };
}

export function EvaluationsPage({ agents, runs, settings, totalLatency, errorCount, onInspectRun, onNavigate }: EvaluationsPageProps) {
  const [activeReport, setActiveReport] = useState<EvaluationReport | null>(null);
  const [playgroundResults, setPlaygroundResults] = useState<PlaygroundResult[]>([]);
  const [playgroundRunning, setPlaygroundRunning] = useState(false);
  const [variantRunning, setVariantRunning] = useState(false);
  const {
    addCase,
    caseExpectedDraft,
    caseInputDraft,
    createDataset,
    datasetNameDraft,
    datasets,
    importDataset,
    importDraft,
    playgroundAgents,
    playgroundPrompt,
    promptVariants,
    removeCase,
    removeDataset,
    renameDataset,
    saveReport,
    selectedDatasetId,
    selectedRunIds,
    setCaseExpectedDraft,
    setCaseInputDraft,
    setDatasetNameDraft,
    setImportDraft,
    setPlaygroundAgents,
    setPlaygroundPrompt,
    setPromptVariants,
    setSelectedDatasetId,
    toggleRunSelection,
    updateCase,
    reports,
  } = useEvalStore();

  const selectedDataset = useMemo(
    () => datasets.find((dataset) => dataset.id === selectedDatasetId) ?? datasets[0] ?? null,
    [datasets, selectedDatasetId],
  );
  const selectedRuns = useMemo(
    () => runs.filter((run) => selectedRunIds.includes(run.response_id)),
    [runs, selectedRunIds],
  );
  const latestReport = activeReport ?? reports[0] ?? null;
  const evalStats: StatItem[] = [
    { label: "Datasets", value: formatCount(datasets.length) },
    { label: "Cases", value: formatCount(datasets.reduce((total, dataset) => total + dataset.cases.length, 0)) },
    { label: "Runs", value: formatCount(runs.length) },
    { label: "Reports", value: formatCount(reports.length) },
    { label: "Latency", value: formatMs(totalLatency) },
    { label: "Errors", value: formatCount(errorCount), tone: errorCount > 0 ? "error" : "default" },
  ];
  const agentOptions = agents.length ? agents : [{ agent_id: settings.agentId || "default-agent" }];

  const exportReportCsv = () => {
    if (!latestReport) return;
    const rows = latestReport.results.map((result) => ({
      case_id: result.caseId,
      passed: result.passed,
      run_id: result.runId,
      input: result.input,
      expected: result.expected,
      actual: result.actual,
    }));
    downloadFile(exportFilename(`eval-${latestReport.datasetName}`, "csv"), toCsv(rows), "text/csv;charset=utf-8");
  };

  const exportReportJson = () => {
    if (!latestReport) return;
    downloadFile(exportFilename(`eval-${latestReport.datasetName}`, "json"), compactJson(latestReport), "application/json");
  };
  const activePlaygroundAgents = playgroundAgents.length ? playgroundAgents : [settings.agentId || agentOptions[0]?.agent_id || "default-agent"];

  function executeEvaluation() {
    if (!selectedDataset || !selectedDataset.cases.length || !selectedRuns.length) {
      return;
    }
    const report = makeReport(selectedDataset, selectedRuns);
    saveReport(report);
    setActiveReport(report);
  }

  async function runPromptForAgent(agentId: string, prompt: string, label: string, kind: PlaygroundResult["kind"]) {
    const result: PlaygroundResult = {
      id: crypto.randomUUID(),
      kind,
      prompt,
      agentId,
      label,
      output: "",
      status: "running",
      createdAt: Date.now(),
    };
    setPlaygroundResults((current) => [result, ...current].slice(0, 12));
    try {
      const messages: ChatMessage[] = [{ id: crypto.randomUUID(), role: "user", content: prompt }];
      const response = await runChat(
        { ...settings, agentId, sessionKey: `${settings.sessionKey || "studio"}-playground` },
        messages,
        (delta) => {
          setPlaygroundResults((current) =>
            current.map((item) => (item.id === result.id ? { ...item, output: item.output + delta } : item)),
          );
        },
        () => undefined,
      );
      setPlaygroundResults((current) =>
        current.map((item) =>
          item.id === result.id
            ? { ...item, output: item.output || response.assistantText || "No text output returned.", status: "passed" }
            : item,
        ),
      );
    } catch (error) {
      setPlaygroundResults((current) =>
        current.map((item) =>
          item.id === result.id
            ? { ...item, output: error instanceof Error ? error.message : "Playground request failed.", status: "failed" }
            : item,
        ),
      );
    }
  }

  async function runPlaygroundCompare() {
    const prompt = playgroundPrompt.trim();
    if (!prompt || playgroundRunning) {
      return;
    }
    setPlaygroundRunning(true);
    try {
      for (const agentId of activePlaygroundAgents) {
        await runPromptForAgent(agentId, prompt, agentId, "agent_compare");
      }
    } finally {
      setPlaygroundRunning(false);
    }
  }

  async function runVariantBatch() {
    const variants = promptVariants
      .split(/\n+/)
      .map((item) => item.trim())
      .filter(Boolean);
    if (!variants.length || variantRunning) {
      return;
    }
    setVariantRunning(true);
    try {
      for (const variant of variants) {
        await runPromptForAgent(settings.agentId || activePlaygroundAgents[0], variant, variant.slice(0, 42), "prompt_variant");
      }
    } finally {
      setVariantRunning(false);
    }
  }

  return (
    <>
      <section className="section-block ds-obs-header">
        <div className="section-title">
          <Database size={17} />
          <h2>Evaluation workspace</h2>
          <span>{runs.length} candidate runs</span>
        </div>
        <StatStrip stats={evalStats} />
      </section>

      <div className="main-grid evaluation-workspace">
        <Card className="panel">
          <Card.Header className="panel-header">
            <div className="panel-title">
              <Database size={18} />
              <span>Datasets</span>
            </div>
            <Button size="sm" variant="secondary" onPress={createDataset}>
              <Plus size={15} />
              Create
            </Button>
          </Card.Header>
          <Card.Content className="panel-content">
            <div className="dataset-create-bar">
              <label className="control-label">
                <span>Dataset name</span>
                <Input aria-label="Dataset name" value={datasetNameDraft} onChange={(event) => setDatasetNameDraft(event.target.value)} />
              </label>
              <label className="control-label">
                <span>Import JSON/CSV</span>
                <TextArea
                  aria-label="Dataset import"
                  rows={3}
                  value={importDraft}
                  onChange={(event) => setImportDraft(event.target.value)}
                  placeholder='[{"input":"...", "expected":"success"}] or input,expected'
                />
              </label>
              <Button size="sm" variant="secondary" onPress={importDataset} isDisabled={!importDraft.trim()}>
                Import dataset
              </Button>
            </div>

            <div className="dataset-list">
              {datasets.length === 0 ? (
                <EmptyState
                  icon={<Database size={22} />}
                  title="No evaluation dataset"
                  description="Create a browser-local dataset or import cases with input and expected output."
                />
              ) : (
                <CompactTable
                  columns={[
                    { key: "name", header: "Dataset", render: (d: EvaluationDataset) => <strong className="ds-cell-strong">{d.name}</strong> },
                    { key: "cases", header: "Cases", align: "right", width: "80px", render: (d: EvaluationDataset) => formatCount(d.cases.length) },
                  ]}
                  rows={datasets}
                  rowKey={(d) => d.id}
                  activeRowKey={selectedDataset?.id ?? null}
                  onRowClick={(d) => setSelectedDatasetId(d.id)}
                />
              )}
            </div>
          </Card.Content>
        </Card>

        <Card className="panel">
          <Card.Header className="panel-header">
            <div className="panel-title">
              <GitCompareArrows size={18} />
              <span>Cases</span>
            </div>
            {selectedDataset ? (
              <Button size="sm" variant="secondary" onPress={() => removeDataset(selectedDataset.id)}>
                <Trash2 size={15} />
                Delete dataset
              </Button>
            ) : null}
          </Card.Header>
          <Card.Content className="panel-content">
            {selectedDataset ? (
              <>
                <label className="control-label">
                  <span>Selected dataset</span>
                  <Input
                    aria-label="Selected dataset name"
                    value={selectedDataset.name}
                    onChange={(event) => renameDataset(selectedDataset.id, event.target.value)}
                  />
                </label>
                <div className="case-editor">
                  <label className="control-label">
                    <span>Input</span>
                    <TextArea rows={2} value={caseInputDraft} onChange={(event) => setCaseInputDraft(event.target.value)} aria-label="Case input" />
                  </label>
                  <label className="control-label">
                    <span>Expected output signal</span>
                    <TextArea
                      rows={2}
                      value={caseExpectedDraft}
                      onChange={(event) => setCaseExpectedDraft(event.target.value)}
                      aria-label="Expected output"
                    />
                  </label>
                  <Button size="sm" variant="primary" onPress={addCase} isDisabled={!caseInputDraft.trim() || !caseExpectedDraft.trim()}>
                    Add case
                  </Button>
                </div>
                <div className="case-list">
                  {selectedDataset.cases.map((item) => (
                    <article className="case-row" key={item.id}>
                      <TextArea
                        rows={2}
                        value={item.input}
                        onChange={(event) => updateCase(selectedDataset.id, item.id, { input: event.target.value })}
                        aria-label="Edit case input"
                      />
                      <TextArea
                        rows={2}
                        value={item.expected}
                        onChange={(event) => updateCase(selectedDataset.id, item.id, { expected: event.target.value })}
                        aria-label="Edit expected output"
                      />
                      <Button size="sm" variant="ghost" isIconOnly aria-label="Remove case" onPress={() => removeCase(selectedDataset.id, item.id)}>
                        <Trash2 size={15} />
                      </Button>
                    </article>
                  ))}
                </div>
              </>
            ) : (
              <div className="empty-state">
                <GitCompareArrows size={24} />
                <strong>Select or create a dataset</strong>
                <p>Cases stay in localStorage until a backend evaluation API is available.</p>
              </div>
            )}
          </Card.Content>
        </Card>
      </div>

      <div className="main-grid evaluation-workspace">
        <Card className="panel">
          <Card.Header className="panel-header">
            <div className="panel-title">
              <Play size={18} />
              <span>Run evaluation</span>
            </div>
            <Button size="sm" variant="primary" onPress={executeEvaluation} isDisabled={!selectedDataset?.cases.length || !selectedRuns.length}>
              Execute
            </Button>
          </Card.Header>
          <Card.Content className="panel-content">
            <div className="history-list">
              {runs.length === 0 ? (
                <EmptyState
                  icon={<Database size={22} />}
                  title="No runs to evaluate"
                  description="Run a session first, then select useful responses here."
                  action={
                    <Button size="sm" variant="primary" onPress={() => onNavigate("sessions")}>
                      View sessions
                    </Button>
                  }
                />
              ) : (
                <CompactTable
                  columns={[
                    {
                      key: "select",
                      header: "",
                      width: "40px",
                      render: (run: ObservabilityRunItem) => (
                        <input
                          aria-label={`Select run ${run.response_id}`}
                          checked={selectedRunIds.includes(run.response_id)}
                          type="checkbox"
                          onChange={() => toggleRunSelection(run.response_id)}
                          onClick={(e) => e.stopPropagation()}
                        />
                      ),
                    },
                    {
                      key: "id",
                      header: "Response ID",
                      render: (run: ObservabilityRunItem) => (
                        <div className="ds-cell-stack">
                          <strong className="ds-cell-strong">{run.response_id}</strong>
                          <span className="ds-cell-sub">{run.agent_id} · {run.session_key}</span>
                        </div>
                      ),
                    },
                    {
                      key: "status",
                      header: "Status",
                      width: "100px",
                      render: (run: ObservabilityRunItem) => (
                        <StatusBadge status={normalizeStatus(run.effective_status || run.status)}>{run.status}</StatusBadge>
                      ),
                    },
                    {
                      key: "inspect",
                      header: "",
                      align: "right",
                      width: "90px",
                      render: (run: ObservabilityRunItem) => (
                        <Button size="sm" variant="secondary" onPress={() => onInspectRun(run.response_id)}>
                          Inspect
                        </Button>
                      ),
                    },
                  ]}
                  rows={runs}
                  rowKey={(run) => run.response_id}
                />
              )}
            </div>
          </Card.Content>
        </Card>

        <Card className="panel">
          <Card.Header className="panel-header">
            <div className="panel-title">
              <BarChart3 size={18} />
              <span>Report</span>
            </div>
            <div className="editor-actions">
              {latestReport ? (
                <Chip size="sm" variant="soft" color={latestReport.passRate >= 80 ? "success" : "warning"}>
                  {latestReport.passRate}% pass
                </Chip>
              ) : null}
              <Button size="sm" variant="secondary" isDisabled={!latestReport} onPress={exportReportCsv} aria-label="Export report as CSV">
                <Download size={14} />
                CSV
              </Button>
              <Button size="sm" variant="secondary" isDisabled={!latestReport} onPress={exportReportJson} aria-label="Export report as JSON">
                <Download size={14} />
                JSON
              </Button>
            </div>
          </Card.Header>
          <Card.Content className="panel-content">
            {latestReport ? (
              <div className="report-stack">
                <div className="pass-rate-bar" aria-label={`Pass rate ${latestReport.passRate}%`}>
                  <span style={{ width: `${latestReport.passRate}%` }} />
                </div>
                {latestReport.results.map((result) => (
                  <article className={`report-row ${result.passed ? "passed" : "failed"}`} key={result.id}>
                    <strong>{result.passed ? "Pass" : "Fail"} · {result.runId || "unmatched run"}</strong>
                    <span>Expected: {result.expected}</span>
                    <small>Actual: {result.actual}</small>
                  </article>
                ))}
              </div>
            ) : (
              <div className="empty-state">
                <BarChart3 size={24} />
                <strong>No report yet</strong>
                <p>Select a dataset and one or more runs to generate pass/fail results.</p>
              </div>
            )}
          </Card.Content>
        </Card>
      </div>

      <Card className="panel wide-panel">
        <Card.Header className="panel-header">
          <div className="panel-title">
            <GitCompareArrows size={18} />
            <span>Playground compare</span>
          </div>
          <Button size="sm" variant="primary" onPress={() => void runPlaygroundCompare()} isDisabled={playgroundRunning || !playgroundPrompt.trim()}>
            {playgroundRunning ? <span className="button-spinner" aria-hidden="true" /> : null}
            Compare agents
          </Button>
        </Card.Header>
        <Card.Content className="panel-content">
          <div className="playground-grid">
            <label className="control-label">
              <span>Prompt</span>
              <TextArea rows={4} value={playgroundPrompt} onChange={(event) => setPlaygroundPrompt(event.target.value)} aria-label="Playground prompt" />
            </label>
            <div className="agent-checkboxes" aria-label="Agent comparison targets">
              {agentOptions.map((agent) => (
                <label key={agent.agent_id}>
                  <input
                    checked={activePlaygroundAgents.includes(agent.agent_id)}
                    type="checkbox"
                    onChange={() => {
                      const next = activePlaygroundAgents.includes(agent.agent_id)
                        ? activePlaygroundAgents.filter((id) => id !== agent.agent_id)
                        : [...activePlaygroundAgents, agent.agent_id];
                      setPlaygroundAgents(next);
                    }}
                  />
                  <span>{agent.agent_id}</span>
                </label>
              ))}
            </div>
            <label className="control-label">
              <span>Prompt variants</span>
              <TextArea rows={4} value={promptVariants} onChange={(event) => setPromptVariants(event.target.value)} aria-label="Prompt variants" />
            </label>
            <Button size="sm" variant="secondary" onPress={() => void runVariantBatch()} isDisabled={variantRunning || !promptVariants.trim()}>
              {variantRunning ? <span className="button-spinner" aria-hidden="true" /> : null}
              Test variants
            </Button>
          </div>
          <div className="playground-results">
            {playgroundResults.length ? (
              playgroundResults.map((result) => (
                <article className="playground-result" key={result.id}>
                  <div>
                    <Chip size="sm" variant="soft" color={result.status === "failed" ? "danger" : result.status === "running" ? "warning" : "success"}>
                      {result.status}
                    </Chip>
                    <strong>{result.label}</strong>
                    <span>{result.kind === "agent_compare" ? result.agentId : "variant"} · {result.prompt}</span>
                  </div>
                  <pre>{result.output || "Waiting for output..."}</pre>
                </article>
              ))
            ) : (
              <div className="empty-state">
                <GitCompareArrows size={24} />
                <strong>No playground results</strong>
                <p>Run an agent comparison or prompt variant batch to capture outputs here.</p>
              </div>
            )}
          </div>
        </Card.Content>
      </Card>
    </>
  );
}
