import { useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { FlaskConical, Plus, X, Wand2 } from 'lucide-react';
import {
  useAgent,
  useApplyCurriculum,
  useCurriculumBatches,
  useEvalRuns,
  useGenerateCurriculum,
  useGeneratedSuites,
  useStartEval,
  useAgents,
} from '../lib/api';
import { AgentSelector } from '../components/AgentSelector';
import { StatusBadge } from '../components/StatusBadge';
import { EmptyState } from '../components/EmptyState';
import { PageHeader } from '../components/PageHeader';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { ScoreDisplay } from '../components/ScoreDisplay';
import { EvalGenerator } from '../components/EvalGenerator';
import { GeneratedEvalReview } from '../components/GeneratedEvalReview';
import { OperatorNextStepCard } from '../components/OperatorNextStepCard';
import { wsClient } from '../lib/websocket';
import { useActiveAgent } from '../lib/active-agent';
import { createJourneyStatusSummary } from '../lib/operator-journey';
import { toastError, toastInfo, toastSuccess } from '../lib/toast';
import { classNames, formatTimestamp, statusVariant } from '../lib/utils';
import type { AgentLibraryItem, ContinuityState, EvalRun } from '../lib/types';

interface EvalJourneyState {
  agent?: AgentLibraryItem;
  open?: 'run' | 'generate';
  source?: string;
  draftEvalCount?: number;
  latestUserRequest?: string;
  evalCasesPath?: string;
}

/** Use selected eval evidence to point operators forward without inventing a hidden eval state. */
function getEvalJourneySummary(input: {
  activeAgent: AgentLibraryItem | null;
  completedAgent: AgentLibraryItem | null;
  completedRunId: string | null;
}) {
  if (input.completedAgent && input.completedRunId) {
    const optimizeParams = new URLSearchParams({
      agent: input.completedAgent.id,
      evalRunId: input.completedRunId,
    });
    if (input.completedAgent.config_path) {
      optimizeParams.set('configPath', input.completedAgent.config_path);
    }
    return createJourneyStatusSummary({
      currentStep: 'eval',
      status: 'ready',
      statusLabel: 'Eval complete',
      summary: `${input.completedAgent.name} has a completed eval run. Use that same run context for Optimize.`,
      nextLabel: 'Optimize candidate',
      nextDescription: 'Open Optimize with the completed eval run and selected agent carried forward.',
      href: `/optimize?${optimizeParams.toString()}`,
    });
  }

  return createJourneyStatusSummary({
    currentStep: 'eval',
    status: input.activeAgent ? 'ready' : 'blocked',
    statusLabel: input.activeAgent ? 'Agent selected' : 'Agent needed',
    summary: input.activeAgent
      ? `${input.activeAgent.name} is selected. Run Eval before Optimize so the next step has evidence.`
      : 'Choose a saved Build or Workbench candidate before starting Eval.',
    nextLabel: 'Run eval',
    nextDescription: 'Launch an evaluation against the selected saved config.',
    href: input.activeAgent ? `/evals?agent=${encodeURIComponent(input.activeAgent.id)}&new=1` : '/build',
  });
}

export function EvalRuns() {
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const { activeAgent, setActiveAgent } = useActiveAgent();
  const { data: agents } = useAgents();
  const { data: selectedAgentDetail } = useAgent(activeAgent?.id);
  const { data: runs, isLoading, isError, refetch } = useEvalRuns();
  const {
    data: generatedSuites = [],
    isLoading: generatedSuitesLoading,
  } = useGeneratedSuites();
  const { data: curriculumData } = useCurriculumBatches();
  const startEval = useStartEval();
  const generateCurriculum = useGenerateCurriculum();
  const applyCurriculum = useApplyCurriculum();

  const [showForm, setShowForm] = useState(false);
  const [showGenerator, setShowGenerator] = useState(false);
  const [generatedSuiteId, setGeneratedSuiteId] = useState<string | null>(null);
  const [expandedSuiteId, setExpandedSuiteId] = useState<string | null>(null);
  const [category, setCategory] = useState('');
  const [selectedRuns, setSelectedRuns] = useState<string[]>([]);
  const [runAgents, setRunAgents] = useState<Record<string, AgentLibraryItem>>({});
  const [completedAgent, setCompletedAgent] = useState<AgentLibraryItem | null>(null);
  const [completedRunId, setCompletedRunId] = useState<string | null>(null);
  const selectionHydratedRef = useRef(false);

  const navigationState = (location.state as EvalJourneyState | null) ?? null;
  const buildEvalCasesPath = navigationState?.evalCasesPath ?? searchParams.get('evalCasesPath') ?? undefined;
  const showCreateForm = showForm || searchParams.get('new') === '1' || navigationState?.open === 'run';
  const showGeneratorPanel =
    showGenerator || searchParams.get('generator') === '1' || navigationState?.open === 'generate';
  const isAgentImproverHandoff =
    navigationState?.source === 'agent-improver' || searchParams.get('from') === 'agent-improver';
  const isFirstRunJourney = showCreateForm && (runs?.length ?? 0) === 0 && Boolean(activeAgent);
  const latestCompletedRunIdForActiveAgent = useMemo(() => {
    if (!activeAgent) {
      return null;
    }
    const completedRun = (runs || []).find(
      (run) => run.status === 'completed' && runAgents[run.run_id]?.id === activeAgent.id
    );
    return completedRun?.run_id ?? null;
  }, [activeAgent, runAgents, runs]);
  const journeySummary = getEvalJourneySummary({
    activeAgent,
    completedAgent: completedAgent ?? (activeAgent && latestCompletedRunIdForActiveAgent ? activeAgent : null),
    completedRunId: completedRunId ?? latestCompletedRunIdForActiveAgent,
  });

  useEffect(() => {
    if (selectionHydratedRef.current) {
      return;
    }
    if (navigationState?.agent) {
      setActiveAgent(navigationState.agent);
      selectionHydratedRef.current = true;
      return;
    }

    const agentId = searchParams.get('agent');
    if (!agentId) {
      selectionHydratedRef.current = true;
      return;
    }
    if (!agents?.length) {
      return;
    }
    const matched = agents.find((agent) => agent.id === agentId);
    if (matched) {
      setActiveAgent(matched);
    }
    selectionHydratedRef.current = true;
  }, [agents, navigationState?.agent, searchParams, setActiveAgent]);

  useEffect(() => {
    const unsubscribe = wsClient.onMessage('eval_complete', (payload) => {
      const data = payload as { task_id: string; composite: number; passed: number; total: number };
      const evalAgent = runAgents[data.task_id] ?? activeAgent ?? null;

      toastSuccess(
        `Eval ${data.task_id.slice(0, 8)} completed`,
        `Composite ${(data.composite * 100).toFixed(1)} · ${data.passed}/${data.total} passed`
      );

      if (evalAgent) {
        setCompletedAgent(evalAgent);
        setCompletedRunId(data.task_id);
      }

      setRunAgents((current) => {
        const next = { ...current };
        delete next[data.task_id];
        return next;
      });
      refetch();
    });

    return () => unsubscribe();
  }, [activeAgent, refetch, runAgents]);

  const comparisonRuns = useMemo(() => {
    if (!runs || selectedRuns.length !== 2) return [];
    return runs.filter((run) => selectedRuns.includes(run.run_id));
  }, [runs, selectedRuns]);
  const continuitySummary = useMemo(() => summarizeEvalRunContinuity(runs ?? []), [runs]);
  const shouldShowStandaloneNoAgentEmptyState =
    !activeAgent &&
    !showCreateForm &&
    generatedSuites.length === 0 &&
    (curriculumData?.batches?.length ?? 0) === 0 &&
    (runs?.length ?? 0) === 0;

  function syncAgentSearchParam(agent: AgentLibraryItem | null) {
    const next = new URLSearchParams(searchParams);
    if (agent) {
      next.set('agent', agent.id);
    } else {
      next.delete('agent');
    }
    setSearchParams(next, { replace: true });
  }

  function openCreateForm() {
    setShowForm(true);
    const next = new URLSearchParams(searchParams);
    next.set('new', '1');
    setSearchParams(next, { replace: true });
  }

  function handleStartEval(options?: { generatedSuiteId?: string }) {
    if (!activeAgent) {
      toastError('Select an agent', 'Pick an agent from the library before starting an eval.');
      return;
    }

    const request: {
      config_path?: string;
      category?: string;
      generated_suite_id?: string;
      dataset_path?: string;
      require_live?: boolean;
      split?: 'train' | 'test' | 'all';
    } = {
      config_path: activeAgent.config_path,
      category: options?.generatedSuiteId ? undefined : category.trim() || undefined,
      generated_suite_id: options?.generatedSuiteId,
      require_live: shouldRequireLiveEval(activeAgent),
    };
    if (!options?.generatedSuiteId && buildEvalCasesPath) {
      request.dataset_path = buildEvalCasesPath;
      request.split = 'all';
    }

    startEval.mutate(
      request,
      {
        onSuccess: (response) => {
          setRunAgents((current) => ({
            ...current,
            [response.task_id]: activeAgent,
          }));
          toastInfo(
            `Eval ${response.task_id.slice(0, 8)} started`,
            options?.generatedSuiteId
              ? `Running eval set against ${activeAgent.name}.`
              : `Running against ${activeAgent.name}.`
          );
          setShowForm(false);
          setCategory('');
          const next = new URLSearchParams(searchParams);
          next.delete('new');
          setSearchParams(next, { replace: true });
        },
        onError: (error) => {
          toastError('Failed to start eval', error.message);
        },
      }
    );
  }

  function toggleSelectedRun(runId: string) {
    setSelectedRuns((current) => {
      if (current.includes(runId)) {
        return current.filter((entry) => entry !== runId);
      }
      if (current.length >= 2) {
        toastInfo('Comparison limit reached', 'Select at most two runs at a time.');
        return current;
      }
      return [...current, runId];
    });
  }

  function closeForm() {
    setShowForm(false);
    const next = new URLSearchParams(searchParams);
    next.delete('new');
    setSearchParams(next, { replace: true });
  }

  function closeGenerator() {
    setShowGenerator(false);
    const next = new URLSearchParams(searchParams);
    next.delete('generator');
    setSearchParams(next, { replace: true });
  }

  function handleGenerateCurriculum() {
    generateCurriculum.mutate(
      {},
      {
        onSuccess: (payload) => {
          toastSuccess(
            'Curriculum generated',
            `Created batch ${payload.batch.batch_id.slice(0, 8)} with ${payload.batch.prompt_count} prompts.`
          );
        },
        onError: (err) => toastError('Curriculum generation failed', err.message),
      }
    );
  }

  function handleApplyCurriculum(batchId: string) {
    applyCurriculum.mutate(
      { batch_id: batchId },
      {
        onSuccess: (payload) => {
          toastSuccess('Curriculum applied', `${payload.applied_count} prompts added to active eval set.`);
        },
        onError: (err) => toastError('Apply failed', err.message),
      }
    );
  }

  function suiteStatusLabel(status: string) {
    if (status === 'accepted') {
      return 'accepted';
    }
    if (status === 'rejected') {
      return 'rejected';
    }
    return 'draft';
  }

  function suiteStatusClass(status: string) {
    if (status === 'accepted') {
      return 'bg-green-100 text-green-700';
    }
    if (status === 'rejected') {
      return 'bg-red-100 text-red-700';
    }
    return 'bg-amber-100 text-amber-700';
  }

  if (isLoading) {
    return (
      <div className="space-y-4">
        <PageHeader
          title="Eval Runs"
          description="Launch evaluations, inspect progress, and compare the quality impact of different runs."
        />

        <section className="rounded-2xl border border-sky-100 bg-[linear-gradient(180deg,rgba(248,250,252,0.96),rgba(255,255,255,1))] p-5 shadow-sm shadow-sky-100/60">
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex rounded-full border border-sky-200 bg-sky-50 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-sky-800">
              Eval Workspace
            </span>
            <span className="text-xs font-medium text-gray-500">Preparing the eval workspace</span>
          </div>
          <p className="mt-3 max-w-2xl text-sm text-gray-600">
            AgentLab is loading the selected draft, recent runs, and generated suites so the next eval is ready to launch.
          </p>
        </section>

        <section className="rounded-2xl border border-gray-200 bg-white p-5">
          <p className="text-sm font-semibold text-gray-900">Loading recent eval context</p>
          <div className="mt-4">
            <LoadingSkeleton rows={4} />
          </div>
        </section>

        <section className="rounded-2xl border border-gray-200 bg-white p-5">
          <p className="text-sm font-semibold text-gray-900">Loading runs and eval sets</p>
          <div className="mt-4">
            <LoadingSkeleton rows={7} />
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Eval Runs"
        description="Launch evaluations, inspect progress, and compare the quality impact of different runs."
        actions={
          <div className="flex items-center gap-2">
            <button
              onClick={() => {
                setShowGenerator(true);
                setGeneratedSuiteId(null);
              }}
              className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3.5 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
            >
              <Wand2 className="h-4 w-4" />
              Generate Evals
            </button>
            <button
              onClick={openCreateForm}
              className="inline-flex items-center gap-2 rounded-lg bg-gray-900 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-gray-800"
            >
              <Plus className="h-4 w-4" />
              Set Up Eval Run
            </button>
          </div>
        }
      />

      <AgentSelector onChange={syncAgentSearchParam} />

      <OperatorNextStepCard summary={journeySummary} />

      {(runs?.length ?? 0) > 0 && (
        <section className="rounded-lg border border-gray-200 bg-white p-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <p className="text-sm font-semibold text-gray-900">Durable history</p>
              <p className="mt-1 text-xs leading-5 text-gray-600">
                Live evals can still update. Interrupted and completed runs are retained as historical records after restart.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <ContinuityPill label="Live" count={continuitySummary.live} tone="live" />
              <ContinuityPill label="Interrupted" count={continuitySummary.interrupted} tone="interrupted" />
              <ContinuityPill label="Historical" count={continuitySummary.historical} tone="historical" />
            </div>
          </div>
        </section>
      )}

      {completedAgent && completedRunId && (
        <section className="rounded-lg border border-sky-200 bg-sky-50 px-4 py-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-sm font-semibold text-sky-900">{completedAgent.name} is ready for optimization</p>
              <p className="mt-1 text-sm text-sky-800">
                Carry the same agent straight into Optimize without picking a config again.
              </p>
            </div>
            <button
              type="button"
              onClick={() =>
                navigate(
                  `/optimize?${new URLSearchParams({
                    agent: completedAgent.id,
                    evalRunId: completedRunId,
                    ...(completedAgent.config_path ? { configPath: completedAgent.config_path } : {}),
                  }).toString()}`,
                  {
                  state: {
                    agent: completedAgent,
                    evalRunId: completedRunId,
                  },
                  }
                )
              }
              className="inline-flex items-center justify-center rounded-lg bg-gray-900 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-gray-800"
            >
              Optimize
            </button>
          </div>
        </section>
      )}

      {showGeneratorPanel && !generatedSuiteId && (
        <section className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-gray-900">AI Eval Generation</h3>
            <button
              onClick={closeGenerator}
              className="rounded p-1 text-gray-500 hover:bg-gray-100 hover:text-gray-700"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          {isAgentImproverHandoff && (
            <div className="mb-4 rounded-lg border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-900">
              <p className="font-semibold">Agent Improver handoff</p>
              <p className="mt-1 leading-6">
                {navigationState?.draftEvalCount
                  ? `Agent Improver drafted ${navigationState.draftEvalCount} validation ideas. Generate a formal eval suite from the saved config, review the cases, then run it.`
                  : 'Generate a formal eval suite from the saved Agent Improver config, review the cases, then run it.'}
              </p>
              {navigationState?.latestUserRequest ? (
                <p className="mt-2 text-xs leading-5 text-sky-800">
                  Latest improvement: {navigationState.latestUserRequest}
                </p>
              ) : null}
            </div>
          )}
          {activeAgent ? (
            <EvalGenerator
              defaultAgentName={activeAgent.name}
              defaultAgentConfig={selectedAgentDetail?.config ?? null}
              onSuiteGenerated={(suiteId) => setGeneratedSuiteId(suiteId)}
            />
          ) : (
            <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50 px-4 py-6 text-sm text-gray-600">
              Choose an agent above to generate a tailored eval suite from its saved config.
            </div>
          )}
        </section>
      )}

      {generatedSuiteId && (
        <section className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-gray-900">Review Generated Evals</h3>
            <button
              onClick={() => {
                setGeneratedSuiteId(null);
                closeGenerator();
              }}
              className="rounded p-1 text-gray-500 hover:bg-gray-100 hover:text-gray-700"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          <GeneratedEvalReview
            suiteId={generatedSuiteId}
            onAccepted={() => {
              toastSuccess('Eval suite accepted', 'Generated cases are now available for eval runs.');
              setGeneratedSuiteId(null);
              closeGenerator();
            }}
          />
        </section>
      )}

      {isError && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Unable to load eval runs. Try refreshing the page.
        </div>
      )}

      <section className="rounded-lg border border-gray-200 bg-white p-5">
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-gray-900">Eval Sets</h3>
            <p className="mt-1 text-xs text-gray-600">
              Browse generated eval suites, accept drafts, and launch accepted eval sets with the active agent.
            </p>
          </div>
          {!activeAgent && (
            <p className="max-w-xs text-right text-xs text-gray-500">
              Select an agent above to run an eval set from this page.
            </p>
          )}
        </div>

        {generatedSuitesLoading ? (
          <LoadingSkeleton rows={3} />
        ) : generatedSuites.length === 0 ? (
          <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50 px-4 py-6 text-sm text-gray-600">
            No eval sets yet — generate one from your agent config
          </div>
        ) : (
          <div className="space-y-4">
            {generatedSuites.map((suite) => {
              const expanded = expandedSuiteId === suite.suite_id;
              const createdAt = suite.created_at ?? suite.updated_at ?? new Date().toISOString();
              return (
                <div key={suite.suite_id} className="rounded-lg border border-gray-200 bg-gray-50 p-4">
                  <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="text-sm font-semibold text-gray-900">{suite.agent_name}</p>
                        <span
                          className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${suiteStatusClass(suite.status)}`}
                        >
                          {suiteStatusLabel(suite.status)}
                        </span>
                        <span className="font-mono text-[11px] text-gray-400">{suite.suite_id}</span>
                      </div>
                      <p className="mt-1 text-xs text-gray-500">
                        {suite.case_count} cases · {formatTimestamp(createdAt)}
                      </p>
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {Object.entries(suite.category_counts).map(([label, count]) => (
                          <span
                            key={label}
                            className="rounded-full border border-gray-200 bg-white px-2 py-0.5 text-[11px] text-gray-600"
                          >
                            {label.replaceAll('_', ' ')} · {count}
                          </span>
                        ))}
                      </div>
                    </div>

                    <div className="flex flex-wrap items-center gap-2">
                      {suite.status === 'accepted' && (
                        <button
                          onClick={() => handleStartEval({ generatedSuiteId: suite.suite_id })}
                          disabled={startEval.isPending || !activeAgent}
                          className="rounded-lg bg-gray-900 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-gray-800 disabled:opacity-60"
                        >
                          Run Eval
                        </button>
                      )}
                      <button
                        onClick={() => setExpandedSuiteId(expanded ? null : suite.suite_id)}
                        className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-semibold text-gray-700 transition hover:bg-gray-50"
                      >
                        {expanded ? 'Hide Cases' : 'View Cases'}
                      </button>
                    </div>
                  </div>

                  {expanded && (
                    <div className="mt-4 border-t border-gray-200 pt-4">
                      <GeneratedEvalReview suiteId={suite.suite_id} />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </section>

      <section className="rounded-lg border border-gray-200 bg-white p-5">
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-gray-900">Curriculum</h3>
            <p className="mt-1 text-xs text-gray-600">
              Self-play prompts synthesized from recent failures to continuously harden evaluations.
            </p>
          </div>
          <button
            onClick={handleGenerateCurriculum}
            disabled={generateCurriculum.isPending}
            className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-semibold text-gray-700 hover:bg-gray-50 disabled:opacity-60"
          >
            {generateCurriculum.isPending ? 'Generating…' : 'Generate Harder Tests'}
          </button>
        </div>

        <div className="grid gap-4 lg:grid-cols-[1.4fr,1fr]">
          <div className="space-y-2">
            {(curriculumData?.batches || []).length === 0 && (
              <p className="rounded-md border border-dashed border-gray-200 bg-gray-50 px-3 py-2 text-xs text-gray-500">
                No curriculum batches yet. Generate one from recent failure clusters.
              </p>
            )}
            {(curriculumData?.batches || []).slice(0, 5).map((batch) => (
              <div key={batch.batch_id} className="rounded-md border border-gray-200 bg-gray-50 px-3 py-2">
                <div className="flex items-center justify-between gap-2">
                  <p className="font-mono text-xs text-gray-700">{batch.batch_id}</p>
                  <button
                    onClick={() => handleApplyCurriculum(batch.batch_id)}
                    disabled={applyCurriculum.isPending}
                    className="rounded-md border border-gray-300 bg-white px-2 py-0.5 text-[11px] font-medium text-gray-700 hover:bg-gray-100"
                  >
                    Apply
                  </button>
                </div>
                <p className="mt-1 text-[11px] text-gray-600">
                  prompts={batch.prompt_count}
                  {batch.applied_count > 0 ? ` · active=${batch.applied_count}` : ''}
                </p>
                <div className="mt-1 flex flex-wrap gap-1">
                  {Object.entries(batch.difficulty_distribution).map(([tier, count]) => (
                    <span key={tier} className="rounded bg-white px-1.5 py-0.5 text-[10px] text-gray-600">
                      {tier}: {count}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>

          <div className="rounded-md border border-gray-200 bg-gray-50 p-3">
            <p className="text-xs font-semibold text-gray-700">Difficulty progression</p>
            <div className="mt-2 space-y-2">
              {(curriculumData?.progression || []).slice(0, 6).map((point) => (
                <div key={point.batch_id} className="space-y-1">
                  <div className="flex items-center justify-between text-[11px] text-gray-500">
                    <span className="font-mono">{point.batch_id.slice(0, 8)}</span>
                    <span>{(point.average_difficulty * 100).toFixed(0)}%</span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-gray-200">
                    <div
                      className="h-full rounded-full bg-gray-700"
                      style={{ width: `${Math.min(point.average_difficulty * 100, 100)}%` }}
                    />
                  </div>
                </div>
              ))}
              {(curriculumData?.progression || []).length === 0 && (
                <p className="text-[11px] text-gray-500">Difficulty progression appears after the first generated batch.</p>
              )}
            </div>
          </div>
        </div>
      </section>

      {showCreateForm && (
        <section className="rounded-[28px] border border-sky-100 bg-[linear-gradient(180deg,rgba(248,250,252,0.96),rgba(255,255,255,1))] p-5 shadow-sm shadow-sky-100/60">
          {isFirstRunJourney && activeAgent ? (
            <div className="mb-4 rounded-2xl border border-sky-200 bg-sky-50 px-4 py-4">
              <div className="flex flex-wrap items-center gap-2">
                <span className="inline-flex rounded-full border border-sky-200 bg-white px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-sky-800">
                  Saved draft from Build
                </span>
                <span className="text-xs font-medium text-sky-700">Ready to evaluate</span>
              </div>
              <p className="mt-3 text-sm font-semibold text-sky-950">Run the first eval for {activeAgent.name}</p>
              <p className="mt-1 text-sm leading-relaxed text-sky-900">
                The saved config is already selected, so you can add an optional label and launch the first run without jumping back to Build.
              </p>
              {buildEvalCasesPath ? (
                <p className="mt-2 font-mono text-xs text-sky-800">{buildEvalCasesPath}</p>
              ) : null}
            </div>
          ) : null}

          <div className="mb-4 flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold text-gray-900">
                {isFirstRunJourney ? 'Start First Evaluation' : 'Start New Evaluation'}
              </h3>
              <p className="mt-1 text-sm text-gray-600">
                {isFirstRunJourney
                  ? 'We carried this saved draft over from Build so you can run the first eval without reselecting the config.'
                  : 'Launch an eval against the selected agent and optionally tag it with a category.'}
              </p>
            </div>
            <button
              type="button"
              aria-label="Close new evaluation form"
              onClick={closeForm}
              className="rounded p-1 text-gray-500 hover:bg-gray-100 hover:text-gray-700"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          <div className="grid gap-3 lg:grid-cols-[1.2fr_1fr_auto]">
            <div className="rounded-2xl border border-gray-200 bg-white px-4 py-3 shadow-sm">
              <label className="mb-1 block text-xs font-semibold uppercase tracking-[0.18em] text-gray-400">
                Selected agent
              </label>
              {activeAgent ? (
                <div>
                  <p className="text-sm font-semibold text-gray-900">{activeAgent.name}</p>
                  <p className="text-xs text-gray-500">
                    {activeAgent.model} · {activeAgent.status}
                  </p>
                  <p className="mt-2 truncate text-xs text-gray-500">{activeAgent.config_path}</p>
                </div>
              ) : (
                <p className="text-sm text-gray-500">Choose an agent from the library above to run this eval.</p>
              )}
            </div>

            <div>
              <label className="mb-1 block text-xs font-semibold uppercase tracking-[0.18em] text-gray-400">
                Category
              </label>
              <input
                type="text"
                value={category}
                onChange={(event) => setCategory(event.target.value)}
                placeholder="Optional, e.g. safety"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
              <p className="mt-2 text-xs text-gray-600">Optional label for grouping runs later in Compare and Results Explorer.</p>
            </div>

            <div className="flex flex-col items-stretch gap-2">
              <button
                onClick={() => handleStartEval()}
                disabled={startEval.isPending || !activeAgent}
                className="w-full rounded-lg bg-gray-900 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-gray-800 disabled:opacity-60"
                title={!activeAgent ? 'Select an agent from the library above to enable this button' : undefined}
              >
                {startEval.isPending ? 'Starting...' : isFirstRunJourney ? 'Run First Eval' : 'Start Eval'}
              </button>
              {!activeAgent && !startEval.isPending && (
                <p className="text-center text-xs text-amber-600">
                  Select an agent from the Agent Library above to start an eval.
                </p>
              )}
            </div>
          </div>
        </section>
      )}

      {comparisonRuns.length === 2 && (
        <section className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-gray-900">Comparison Mode</h3>
            <button
              onClick={() => setSelectedRuns([])}
              className="rounded border border-gray-300 px-2.5 py-1 text-xs text-gray-600 hover:bg-gray-50"
            >
              Clear
            </button>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            {comparisonRuns.map((run) => (
              <div key={run.run_id} className="rounded-lg border border-gray-200 p-4">
                <div className="flex items-center justify-between">
                  <p className="font-mono text-xs text-gray-600">{run.run_id.slice(0, 12)}</p>
                  <div className="flex items-center gap-3">
                    {run.mode && <StatusBadge variant={statusVariant(run.mode)} label={run.mode} />}
                    <StatusBadge variant={statusVariant(run.status)} label={run.status} />
                  </div>
                </div>
                <div className="mt-2">
                  <ScoreDisplay score={run.composite_score} size="lg" />
                  <p className="mt-1 text-xs text-gray-500">
                    {run.passed_cases}/{run.total_cases} passed · {formatTimestamp(run.timestamp)}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {runs && runs.length > 0 ? (
        <section className="overflow-hidden rounded-lg border border-gray-200 bg-white">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 bg-gray-50">
                  <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Compare</th>
                  <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Run ID</th>
                  <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Started</th>
                  <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Status</th>
                  <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Score</th>
                  <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Cases</th>
                  <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Action</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run, index) => {
                  const continuity = getEvalRunContinuity(run);
                  return (
                  <tr key={run.run_id} className={index % 2 ? 'bg-gray-50/60' : ''}>
                    <td className="px-3 py-2">
                      <input
                        type="checkbox"
                        checked={selectedRuns.includes(run.run_id)}
                        onChange={() => toggleSelectedRun(run.run_id)}
                        className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                      />
                    </td>
                    <td className="px-3 py-2 font-mono text-xs text-gray-700">{run.run_id.slice(0, 8)}</td>
                    <td className="px-3 py-2 text-gray-600">{formatTimestamp(run.timestamp)}</td>
                    <td className="px-3 py-2">
                      <div className="space-y-1">
                        <StatusBadge variant={statusVariant(run.status)} label={run.status} />
                        {run.mode && <StatusBadge variant={statusVariant(run.mode)} label={run.mode} />}
                        {run.status === 'running' && (
                          <p className="text-xs text-gray-500">Progress: {run.progress}%</p>
                        )}
                        <div className="max-w-xs space-y-1">
                          {run.status === 'failed' && run.error ? (
                            <p className="text-xs leading-5 text-red-700">{firstErrorLine(run.error)}</p>
                          ) : null}
                          <p className={classNames('text-xs font-semibold', continuityToneClass(continuity.state))}>
                            {continuity.label}
                          </p>
                          <p className={classNames('text-xs leading-5', continuityToneClass(continuity.state))}>
                            {continuity.detail}
                          </p>
                        </div>
                      </div>
                    </td>
                    <td className="px-3 py-2 font-medium text-gray-900">{run.composite_score.toFixed(1)}</td>
                    <td className="px-3 py-2 text-gray-600">
                      {run.total_cases > 0 ? `${run.passed_cases}/${run.total_cases}` : '—'}
                    </td>
                    <td className="px-3 py-2">
                      <button
                        onClick={() => navigate(`/evals/${run.run_id}`)}
                        className="rounded border border-gray-300 px-2.5 py-1 text-xs text-gray-700 hover:bg-gray-50"
                      >
                        View
                      </button>
                    </td>
                  </tr>
                );
                })}
              </tbody>
            </table>
          </div>
        </section>
      ) : activeAgent ? (
        showCreateForm ? null : (
          <EmptyState
            icon={FlaskConical}
            title="No eval runs yet"
            description="Set up the first run for the selected saved draft, then inspect results and compare follow-up runs here."
            cliHint="agentlab eval run"
            actionLabel="Set Up First Eval"
            onAction={openCreateForm}
          />
        )
      ) : shouldShowStandaloneNoAgentEmptyState ? (
        <EmptyState
          icon={FlaskConical}
          title="Pick an agent to start evaluating"
          description="Build or connect an agent first, then run your first eval from the same saved config."
          actionLabel="Open Build"
          onAction={() => navigate('/build')}
        />
      ) : null}
    </div>
  );
}

function shouldRequireLiveEval(agent: AgentLibraryItem): boolean {
  const model = agent.model.trim().toLowerCase();
  return Boolean(model) && !model.includes('mock');
}

function firstErrorLine(error: string): string {
  return error.split('\n').find((line) => line.trim())?.trim() || error;
}

function summarizeEvalRunContinuity(runs: EvalRun[]) {
  return runs.reduce(
    (summary, run) => {
      const state = run.continuity?.state ?? inferEvalContinuityState(run.status);
      if (state === 'live') {
        summary.live += 1;
      } else if (state === 'interrupted') {
        summary.interrupted += 1;
      } else {
        summary.historical += 1;
      }
      return summary;
    },
    { live: 0, interrupted: 0, historical: 0 }
  );
}

function getEvalRunContinuity(run: EvalRun): ContinuityState {
  if (run.continuity) {
    return run.continuity;
  }
  const state = inferEvalContinuityState(run.status);
  if (state === 'live') {
    return {
      state,
      label: 'Live run',
      detail: 'This eval is active in the current server process.',
      is_live: true,
      is_historical: false,
      can_rerun: false,
    };
  }
  if (state === 'interrupted') {
    return {
      state,
      label: 'Interrupted by restart',
      detail: 'This eval stopped before completion when the server restarted. Rerun it to continue.',
      is_live: false,
      is_historical: true,
      can_rerun: true,
    };
  }
  return {
    state,
    label: 'Historical run',
    detail: 'This eval is saved history and remains visible after restart.',
    is_live: false,
    is_historical: true,
    can_rerun: false,
  };
}

function inferEvalContinuityState(status: string): 'live' | 'interrupted' | 'historical' {
  if (status === 'pending' || status === 'running') return 'live';
  if (status === 'interrupted') return 'interrupted';
  return 'historical';
}

function continuityToneClass(state: string) {
  if (state === 'live') return 'text-sky-700';
  if (state === 'interrupted') return 'text-amber-700';
  return 'text-gray-500';
}

function ContinuityPill({
  label,
  count,
  tone,
}: {
  label: string;
  count: number;
  tone: 'live' | 'interrupted' | 'historical';
}) {
  const className =
    tone === 'live'
      ? 'border-sky-200 bg-sky-50 text-sky-700'
      : tone === 'interrupted'
        ? 'border-amber-200 bg-amber-50 text-amber-700'
        : 'border-gray-200 bg-gray-50 text-gray-700';
  return (
    <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${className}`}>
      {label}: {count}
    </span>
  );
}
