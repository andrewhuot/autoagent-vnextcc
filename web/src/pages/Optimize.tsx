import { useEffect, useMemo, useState } from 'react';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { Play, Sparkles, Zap, Plus, Trash2 } from 'lucide-react';
import { EmptyState } from '../components/EmptyState';
import { DiffViewer } from '../components/DiffViewer';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { LiveOptimize } from './LiveOptimize';
import { PageHeader } from '../components/PageHeader';
import { ScoreChart } from '../components/ScoreChart';
import { StatusBadge } from '../components/StatusBadge';
import { TimelineEntry } from '../components/TimelineEntry';
import { AgentSelector } from '../components/AgentSelector';
import { useActiveAgent } from '../lib/active-agent';
import { useAgents, useOptimizeHistory, useStartOptimize, useTaskStatus } from '../lib/api';
import { wsClient } from '../lib/websocket';
import { toastError, toastInfo, toastSuccess } from '../lib/toast';
import { classNames, formatTimestamp, statusVariant } from '../lib/utils';
import type { AgentLibraryItem, DiffLine } from '../lib/types';

type OptimizeMode = 'standard' | 'advanced' | 'research';
type OptimizeTab = 'run' | 'live';

interface OptimizeJourneyState {
  agent?: AgentLibraryItem;
  evalRunId?: string;
}

const modeDescriptions: Record<OptimizeMode, string> = {
  standard: 'Default optimization with safety gates and regression checks.',
  advanced: 'Advanced mode with adaptive bandit policies and curriculum learning.',
  research: 'Research mode with full algorithm options, custom objectives, and guardrails.',
};

const researchAlgorithms = [
  { key: 'bayesian', label: 'Bayesian Optimization' },
  { key: 'evolutionary', label: 'Evolutionary Search' },
  { key: 'mcts', label: 'Monte Carlo Tree Search' },
  { key: 'gradient_free', label: 'Gradient-Free Methods' },
];

const optimizeTabs: Array<{ key: OptimizeTab; label: string }> = [
  { key: 'run', label: 'Run' },
  { key: 'live', label: 'Live' },
];

function parseDiffLines(diff: string): DiffLine[] {
  if (!diff) return [];
  const lines = diff.split('\n');
  let left = 1;
  let right = 1;

  return lines
    .filter((line) => !line.startsWith('@@') && !line.startsWith('+++') && !line.startsWith('---'))
    .map((line) => {
      if (line.startsWith('+')) {
        const mapped: DiffLine = { type: 'added', content: line.slice(1), line_a: null, line_b: right };
        right += 1;
        return mapped;
      }
      if (line.startsWith('-')) {
        const mapped: DiffLine = { type: 'removed', content: line.slice(1), line_a: left, line_b: null };
        left += 1;
        return mapped;
      }

      const mapped: DiffLine = {
        type: 'unchanged',
        content: line,
        line_a: left,
        line_b: right,
      };
      left += 1;
      right += 1;
      return mapped;
    });
}

function OptimizeTabButton({
  active,
  label,
  onClick,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={classNames(
        'rounded-md px-4 py-2 text-sm font-medium transition-colors',
        active ? 'bg-gray-900 text-white shadow-sm' : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
      )}
    >
      {label}
    </button>
  );
}

export function Optimize() {
  const [searchParams, setSearchParams] = useSearchParams();
  const location = useLocation();
  const { activeAgent, setActiveAgent } = useActiveAgent();
  const { data: agents } = useAgents();
  const [activeTab, setActiveTab] = useState<OptimizeTab>('run');
  const [visitedTabs, setVisitedTabs] = useState<Set<OptimizeTab>>(() => new Set(['run']));
  const [selectionHydrated, setSelectionHydrated] = useState(false);

  const journeyState = (location.state as OptimizeJourneyState | null) ?? null;
  const selectedEvalRunId = journeyState?.evalRunId ?? null;

  useEffect(() => {
    if (selectionHydrated) {
      return;
    }
    if (journeyState?.agent) {
      setActiveAgent(journeyState.agent);
      setSelectionHydrated(true);
      return;
    }
    const agentId = searchParams.get('agent');
    if (!agentId) {
      setSelectionHydrated(true);
      return;
    }
    if (!agents?.length) {
      return;
    }
    const matched = agents.find((agent) => agent.id === agentId);
    if (matched) {
      setActiveAgent(matched);
    }
    setSelectionHydrated(true);
  }, [agents, journeyState?.agent, searchParams, selectionHydrated, setActiveAgent]);

  function selectTab(tab: OptimizeTab) {
    setActiveTab(tab);
    setVisitedTabs((current) => {
      if (current.has(tab)) {
        return current;
      }
      const next = new Set(current);
      next.add(tab);
      return next;
    });
  }

  function syncAgentSearchParam(agent: AgentLibraryItem | null) {
    const next = new URLSearchParams(searchParams);
    if (agent) {
      next.set('agent', agent.id);
    } else {
      next.delete('agent');
    }
    setSearchParams(next, { replace: true });
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Optimize"
        description="Run optimization cycles and live monitoring. Review outputs in Improvements."
        actions={
          <Link
            to="/improvements"
            className="rounded-lg border border-gray-300 bg-white px-3.5 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
          >
            Open Improvements
          </Link>
        }
      />

      <AgentSelector onChange={syncAgentSearchParam} />

      {selectedEvalRunId && activeAgent && (
        <section className="rounded-lg border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-900">
          Optimizing <span className="font-semibold">{activeAgent.name}</span> using context from eval run{' '}
          <span className="font-mono">{selectedEvalRunId.slice(0, 8)}</span>.
        </section>
      )}

      <section className="rounded-lg border border-gray-200 bg-white p-2">
        <div className="flex flex-wrap gap-1">
          {optimizeTabs.map((tab) => (
            <OptimizeTabButton
              key={tab.key}
              active={activeTab === tab.key}
              label={tab.label}
              onClick={() => selectTab(tab.key)}
            />
          ))}
        </div>
      </section>

      {visitedTabs.has('run') && (
        <section hidden={activeTab !== 'run'}>
          <OptimizeRunSection activeAgent={activeAgent} evalRunId={selectedEvalRunId} />
        </section>
      )}
      {visitedTabs.has('live') && (
        <section hidden={activeTab !== 'live'}>
          <LiveOptimize />
        </section>
      )}
    </div>
  );
}

function OptimizeRunSection({
  activeAgent,
  evalRunId,
}: {
  activeAgent: AgentLibraryItem | null;
  evalRunId: string | null;
}) {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { data: history, isLoading, refetch } = useOptimizeHistory();
  const startOptimize = useStartOptimize();

  const [windowSize, setWindowSize] = useState(100);
  const [force, setForce] = useState(() => searchParams.get('new') === '1');
  const [expandedAttempt, setExpandedAttempt] = useState<string | null>(null);
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [activeTaskAgent, setActiveTaskAgent] = useState<AgentLibraryItem | null>(null);
  const [completedAgent, setCompletedAgent] = useState<AgentLibraryItem | null>(null);
  const [optimizeMode, setOptimizeMode] = useState<OptimizeMode>('standard');
  const [objective, setObjective] = useState('');
  const [guardrails, setGuardrails] = useState<string[]>([]);
  const [newGuardrail, setNewGuardrail] = useState('');
  const [researchAlgorithm, setResearchAlgorithm] = useState('bayesian');
  const [budgetCycles, setBudgetCycles] = useState(10);
  const [budgetDollars, setBudgetDollars] = useState(50);

  const taskStatus = useTaskStatus(activeTaskId);

  useEffect(() => {
    const unsubscribe = wsClient.onMessage('optimize_complete', (payload) => {
      const data = payload as { task_id: string; accepted: boolean; status: string };
      const optimizationAgent = activeTaskAgent ?? activeAgent ?? null;
      if (data.accepted) {
        toastSuccess('Optimization accepted', data.status);
      } else {
        toastInfo('Optimization completed', data.status);
      }
      if (optimizationAgent) {
        setCompletedAgent(optimizationAgent);
      }
      refetch();
    });

    return () => unsubscribe();
  }, [activeAgent, activeTaskAgent, refetch]);

  useEffect(() => {
    if (!taskStatus.data) return;

    if (taskStatus.data.status === 'completed') {
      const result = (taskStatus.data.result || {}) as { accepted?: boolean; status_message?: string };
      if (result.accepted) {
        toastSuccess('Optimization cycle finished', result.status_message || 'Change accepted.');
      } else {
        toastInfo('Optimization cycle finished', result.status_message || 'No deployable change this cycle.');
      }
      if (activeTaskAgent) {
        setCompletedAgent(activeTaskAgent);
      }
      refetch();
    }

    if (taskStatus.data.status === 'failed') {
      toastError('Optimization failed', taskStatus.data.error || 'Unknown error');
    }
  }, [activeTaskAgent, refetch, taskStatus.data]);

  const taskIsRunning =
    !!activeTaskId &&
    (!taskStatus.data ||
      taskStatus.data.status === 'running' ||
      taskStatus.data.status === 'pending');

  const trajectoryData = useMemo(() => {
    return (history || []).slice().reverse().map((attempt, index) => ({
      label: `#${index + 1}`,
      score: attempt.score_after,
    }));
  }, [history]);

  const attempts = history || [];
  const selectedAttempt = attempts.find((attempt) => attempt.attempt_id === expandedAttempt) || null;

  function handleStart() {
    if (!activeAgent) {
      toastError('Select an agent', 'Pick an agent from the library before starting optimization.');
      return;
    }

    startOptimize.mutate(
      {
        window: windowSize,
        force,
        config_path: activeAgent.config_path,
        mode: optimizeMode,
        objective,
        guardrails,
        research_algorithm: researchAlgorithm,
        budget_cycles: budgetCycles,
        budget_dollars: budgetDollars,
      },
      {
        onSuccess: (response) => {
          setActiveTaskId(response.task_id);
          setActiveTaskAgent(activeAgent);
          toastInfo(
            `Optimization ${response.task_id.slice(0, 8)} started`,
            `Running against ${activeAgent.name}.`
          );
        },
        onError: (error) => {
          toastError('Failed to start optimization', error.message);
        },
      }
    );
  }

  if (isLoading) {
    return (
      <div className="space-y-4">
        <LoadingSkeleton rows={4} />
        <LoadingSkeleton rows={7} />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {completedAgent && (
        <section className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-sm font-semibold text-emerald-900">{completedAgent.name} finished its optimization cycle</p>
              <p className="mt-1 text-sm text-emerald-800">
                Keep the loop moving by reviewing the results or re-running evals on the same saved agent.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => navigate(`/evals?agent=${encodeURIComponent(completedAgent.id)}&new=1`, { state: { agent: completedAgent } })}
                className="rounded-lg border border-gray-300 bg-white px-3.5 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
              >
                Re-eval
              </button>
              <button
                type="button"
                onClick={() => navigate('/improvements')}
                className="rounded-lg bg-gray-900 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-gray-800"
              >
                View Results
              </button>
            </div>
          </div>
        </section>
      )}

      <PageHeader
        title="Optimize"
        description="Run optimization cycles and inspect exactly which candidate changes were accepted or rejected."
        actions={
          <button
            onClick={handleStart}
            disabled={startOptimize.isPending || taskIsRunning || !activeAgent}
            className="inline-flex items-center gap-2 rounded-lg bg-gray-900 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-gray-800 disabled:opacity-60"
          >
            <Play className="h-4 w-4" />
            {startOptimize.isPending || taskIsRunning ? 'Running...' : 'Start Optimization'}
          </button>
        }
      />

      <section className="rounded-lg border border-gray-200 bg-white p-5">
        <div className="mb-3 flex gap-1 rounded-lg border border-gray-200 bg-gray-50 p-1">
          {(['standard', 'advanced', 'research'] as OptimizeMode[]).map((mode) => (
            <button
              key={mode}
              onClick={() => setOptimizeMode(mode)}
              className={classNames(
                'rounded-md px-4 py-2 text-sm font-medium capitalize transition-colors',
                optimizeMode === mode
                  ? 'bg-white text-gray-900 shadow-sm'
                  : 'text-gray-600 hover:text-gray-900'
              )}
            >
              {mode}
            </button>
          ))}
        </div>
        <p className="text-xs text-gray-500">{modeDescriptions[optimizeMode]}</p>

        {evalRunId && (
          <div className="mt-4 rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-xs text-sky-900">
            Using eval context from run <span className="font-mono">{evalRunId.slice(0, 8)}</span> while optimizing this agent.
          </div>
        )}

        {optimizeMode === 'research' && (
          <div className="mt-4 space-y-4 rounded-lg border border-blue-200 bg-blue-50 p-4">
            <div className="rounded-lg border border-blue-200 bg-white/80 px-3 py-2 text-xs text-blue-900">
              Research mode now configures the backend search strategy and evaluation budget.
              Objective text and algorithm selection are still informational in this build.
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-700">Algorithm</label>
              <div className="flex flex-wrap gap-2">
                {researchAlgorithms.map((algo) => (
                  <button
                    key={algo.key}
                    onClick={() => setResearchAlgorithm(algo.key)}
                    className={classNames(
                      'rounded-md border px-3 py-1.5 text-xs font-medium transition-colors',
                      researchAlgorithm === algo.key
                        ? 'border-blue-500 bg-blue-100 text-blue-800'
                        : 'border-gray-200 bg-white text-gray-600 hover:bg-gray-50'
                    )}
                  >
                    {algo.label}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="mb-1 block text-xs font-medium text-gray-700">Objective</label>
              <input
                type="text"
                placeholder="e.g. Maximize task_success_rate while maintaining safety > 0.99"
                value={objective}
                onChange={(e) => setObjective(e.target.value)}
                className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>

            <div>
              <label className="mb-1 block text-xs font-medium text-gray-700">
                Guardrails ({guardrails.length})
              </label>
              <div className="space-y-1.5">
                {guardrails.map((g, i) => (
                  <div
                    key={i}
                    className="flex items-center justify-between rounded-md border border-gray-200 bg-white px-3 py-1.5"
                  >
                    <span className="text-xs text-gray-700">{g}</span>
                    <button
                      onClick={() => setGuardrails(guardrails.filter((_, idx) => idx !== i))}
                      className="text-gray-400 hover:text-red-500"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))}
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    placeholder="Add guardrail..."
                    value={newGuardrail}
                    onChange={(e) => setNewGuardrail(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && newGuardrail.trim()) {
                        setGuardrails([...guardrails, newGuardrail.trim()]);
                        setNewGuardrail('');
                      }
                    }}
                    className="flex-1 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs focus:border-blue-500 focus:outline-none"
                  />
                  <button
                    onClick={() => {
                      if (newGuardrail.trim()) {
                        setGuardrails([...guardrails, newGuardrail.trim()]);
                        setNewGuardrail('');
                      }
                    }}
                    className="rounded-md border border-gray-200 bg-white p-1.5 text-gray-500 hover:bg-gray-50"
                  >
                    <Plus className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-700">Budget (cycles)</label>
                <input
                  type="number"
                  min={1}
                  max={100}
                  value={budgetCycles}
                  onChange={(e) => setBudgetCycles(Number(e.target.value))}
                  className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-700">Budget ($)</label>
                <input
                  type="number"
                  min={1}
                  max={10000}
                  value={budgetDollars}
                  onChange={(e) => setBudgetDollars(Number(e.target.value))}
                  className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                />
              </div>
            </div>
          </div>
        )}
      </section>

      <section className="rounded-lg border border-gray-200 bg-white p-5">
        <div className="grid gap-3 sm:grid-cols-3">
          <div>
            <label className="mb-1 block text-xs text-gray-500">Observation window</label>
            <input
              type="number"
              min={10}
              max={1000}
              value={windowSize}
              onChange={(event) => setWindowSize(Number(event.target.value))}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            />
          </div>
          <div className="flex items-center gap-2 self-end pb-2">
            <input
              id="force-optimization"
              type="checkbox"
              checked={force}
              onChange={(event) => setForce(event.target.checked)}
              className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
            />
            <label htmlFor="force-optimization" className="text-sm text-gray-700">
              Force optimization even if healthy
            </label>
          </div>
          <div className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-800">
            {activeAgent
              ? `Optimization will run against ${activeAgent.name} using its saved config.`
              : 'Choose an agent above before starting optimization.'}
          </div>
        </div>

        {taskIsRunning && activeTaskId && (
          <div className="mt-4 rounded-lg border border-blue-200 bg-blue-50 px-4 py-3">
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium text-blue-800">Active task {activeTaskId.slice(0, 8)}</p>
              <p className="text-xs text-blue-700">{taskStatus.data?.progress ?? 0}%</p>
            </div>
            <div className="mt-2 h-2 overflow-hidden rounded-full bg-blue-100">
              <div
                className="h-full rounded-full bg-gray-600 transition-all duration-200"
                style={{ width: `${taskStatus.data?.progress ?? 0}%` }}
              />
            </div>
          </div>
        )}
      </section>

      <section className="rounded-lg border border-gray-200 bg-white p-5">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-gray-900">Cycle Score Trajectory</h3>
          <Sparkles className="h-4 w-4 text-gray-400" />
        </div>
        {trajectoryData.length > 0 ? (
          <ScoreChart data={trajectoryData} height={260} />
        ) : (
          <div className="flex h-[260px] items-center justify-center rounded-lg border border-dashed border-gray-200 bg-gray-50 text-sm text-gray-500">
            No optimization history yet.
          </div>
        )}
      </section>

      {attempts.length > 0 ? (
        <section className="grid gap-4 xl:grid-cols-[1.2fr_1fr]">
          <div className="rounded-lg border border-gray-200 bg-white p-5">
            <h3 className="mb-4 text-sm font-semibold text-gray-900">Cycle Timeline</h3>
            <div className="space-y-3 border-l border-dashed border-gray-200 pl-2">
              {attempts.map((attempt) => (
                <button
                  key={attempt.attempt_id}
                  onClick={() =>
                    setExpandedAttempt((current) =>
                      current === attempt.attempt_id ? null : attempt.attempt_id
                    )
                  }
                  className="w-full text-left"
                >
                  <TimelineEntry
                    timestamp={attempt.timestamp}
                    title={attempt.change_description || `Attempt ${attempt.attempt_id.slice(0, 8)}`}
                    description={`Score ${attempt.score_before.toFixed(1)} → ${attempt.score_after.toFixed(1)}`}
                    status={attempt.status}
                  />
                </button>
              ))}
            </div>
          </div>

          <div className="rounded-lg border border-gray-200 bg-white p-5">
            <h3 className="mb-4 text-sm font-semibold text-gray-900">Attempt Details</h3>
            {selectedAttempt ? (
              <div className="space-y-4">
                <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                  <div className="mb-2 flex items-center justify-between">
                    <p className="font-mono text-xs text-gray-600">{selectedAttempt.attempt_id.slice(0, 12)}</p>
                    <StatusBadge variant={statusVariant(selectedAttempt.status)} label={selectedAttempt.status.replaceAll('_', ' ')} />
                  </div>
                  <p className="text-sm text-gray-700">{selectedAttempt.change_description || 'No change description'}</p>
                  <p className="mt-2 text-xs text-gray-500">
                    {formatTimestamp(selectedAttempt.timestamp)} · {selectedAttempt.score_before.toFixed(1)} → {selectedAttempt.score_after.toFixed(1)}
                  </p>
                </div>

                {selectedAttempt.config_diff ? (
                  <DiffViewer
                    lines={parseDiffLines(selectedAttempt.config_diff)}
                    versionA={0}
                    versionB={1}
                  />
                ) : (
                  <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50 p-4 text-sm text-gray-500">
                    No config diff available for this attempt.
                  </div>
                )}
              </div>
            ) : (
              <div className="flex h-48 items-center justify-center rounded-lg border border-dashed border-gray-200 bg-gray-50 text-sm text-gray-500">
                Select a timeline item to inspect details.
              </div>
            )}
          </div>
        </section>
      ) : activeAgent ? (
        <EmptyState
          icon={Zap}
          title="No optimization history"
          description="Start a cycle to let the optimizer inspect failures, propose a config update, and run gate checks."
          actionLabel="Start optimization"
          onAction={handleStart}
        />
      ) : (
        <EmptyState
          icon={Zap}
          title="Pick an agent to optimize"
          description="Build or connect an agent first, then bring it here to optimize the same saved config."
          actionLabel="Open Build"
          onAction={() => navigate('/build')}
        />
      )}
    </div>
  );
}
