import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import {
  ArrowUpRight,
  Bot,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock3,
  Gauge,
  Play,
  Plus,
  RotateCcw,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  Workflow,
  X,
  XCircle,
  Zap,
} from 'lucide-react';
import { EmptyState } from '../components/EmptyState';
import { DiffViewer } from '../components/DiffViewer';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { LiveOptimize } from './LiveOptimize';
import { PageHeader } from '../components/PageHeader';
import { ScoreChart } from '../components/ScoreChart';
import { StatusBadge } from '../components/StatusBadge';
import { AgentSelector } from '../components/AgentSelector';
import { OperatorNextStepCard } from '../components/OperatorNextStepCard';
import { useActiveAgent } from '../lib/active-agent';
import { createJourneyStatusSummary } from '../lib/operator-journey';
import { useWorkbenchBridge } from '../lib/workbench-api';
import {
  useAgents,
  useApproveReview,
  useOptimizeHistory,
  usePendingReviews,
  useRejectReview,
  useStartOptimize,
  useTaskStatus,
} from '../lib/api';
import { wsClient } from '../lib/websocket';
import { toastError, toastInfo, toastSuccess } from '../lib/toast';
import {
  classNames,
  formatDuration,
  formatScore,
  formatTimestamp,
  statusVariant,
  truncate,
} from '../lib/utils';
import type {
  AgentLibraryItem,
  DiffLine,
  OptimizationAttempt,
  OptimizeCycleResult,
  PendingReview,
  TaskState,
} from '../lib/types';

type OptimizeMode = 'standard' | 'advanced' | 'research';
type OptimizeTab = 'run' | 'live';
type StepState = 'complete' | 'current' | 'upcoming';

interface OptimizeJourneyState {
  agent?: AgentLibraryItem;
  evalRunId?: string;
}

interface WorkbenchOptimizeContext {
  projectId: string | null;
  journeyId: string | null;
  candidateName: string;
  configPath: string | null;
  evalHref: string;
}

interface PersistedOptimizeResult {
  agent: AgentLibraryItem | null;
  taskId: string;
  startedAt: string;
  completedAt: string;
  result: OptimizeCycleResult;
}

interface CompletedOptimizationSummary {
  agent: AgentLibraryItem | null;
  accepted: boolean;
  pendingReview: boolean;
}

const modeDescriptions: Record<OptimizeMode, string> = {
  standard: 'Default optimization with safety gates and regression checks.',
  advanced: 'Advanced mode with adaptive bandit policies and curriculum learning.',
  research: 'Research mode with full algorithm options, custom objectives, and guardrails.',
};

const modeLabels: Record<OptimizeMode, string> = {
  standard: 'Standard',
  advanced: 'Advanced',
  research: 'Research',
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

function buildWorkbenchEvalHref(context: {
  projectId: string | null;
  journeyId: string | null;
}): string {
  const params = new URLSearchParams();
  params.set('new', '1');
  params.set('from', 'workbench');
  if (context.projectId) {
    params.set('workbenchProjectId', context.projectId);
  }
  if (context.journeyId) {
    params.set('journeyId', context.journeyId);
  }
  return `/evals?${params.toString()}`;
}

function parseWorkbenchOptimizeContext(searchParams: URLSearchParams): WorkbenchOptimizeContext | null {
  const source = searchParams.get('from') ?? searchParams.get('source');
  if (source !== 'workbench') {
    return null;
  }
  const projectId = searchParams.get('workbenchProjectId') ?? searchParams.get('projectId');
  const journeyId = searchParams.get('journeyId');
  const candidateName =
    searchParams.get('candidate') ??
    searchParams.get('agentName') ??
    'Workbench candidate';
  const configPath = searchParams.get('configPath');
  return {
    projectId,
    journeyId,
    candidateName,
    configPath,
    evalHref: buildWorkbenchEvalHref({ projectId, journeyId }),
  };
}

const optimizeProgressSteps = [
  {
    key: 'observe',
    label: 'Observing...',
    shortLabel: 'Observe',
    description: 'Collecting recent conversations and measuring agent health.',
    min: 10,
    max: 20,
  },
  {
    key: 'analyze',
    label: 'Analyzing failures...',
    shortLabel: 'Analyze',
    description: 'Grouping failure patterns and deciding what needs attention.',
    min: 20,
    max: 30,
  },
  {
    key: 'generate',
    label: 'Generating candidates...',
    shortLabel: 'Generate',
    description: 'Drafting promising configuration changes for the next evaluation pass.',
    min: 30,
    max: 40,
  },
  {
    key: 'evaluate',
    label: 'Evaluating candidates...',
    shortLabel: 'Evaluate',
    description: 'Running score checks to see whether the proposed change improves outcomes.',
    min: 40,
    max: 70,
  },
  {
    key: 'deploy',
    label: 'Deploying...',
    shortLabel: 'Deploy',
    description: 'Promoting the accepted candidate to the active configuration.',
    min: 70,
    max: 100,
  },
] as const;

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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function normalizeScore(value: number | null | undefined): number | null {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return null;
  }
  if (value >= 0 && value <= 1) {
    return value * 100;
  }
  return value;
}

function scoreDelta(before: number | null | undefined, after: number | null | undefined): number | null {
  const normalizedBefore = normalizeScore(before);
  const normalizedAfter = normalizeScore(after);
  if (normalizedBefore === null || normalizedAfter === null) {
    return null;
  }
  return normalizedAfter - normalizedBefore;
}

function formatScoreValue(value: number | null | undefined): string {
  const normalized = normalizeScore(value);
  return normalized === null ? '—' : formatScore(normalized);
}

function formatDeltaValue(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return '—';
  }
  const prefix = value > 0 ? '+' : '';
  return `${prefix}${formatScore(value)}`;
}

function deltaTone(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return 'border-gray-200 bg-gray-50 text-gray-700';
  }
  if (value > 0) {
    return 'border-emerald-200 bg-emerald-50 text-emerald-700';
  }
  if (value < 0) {
    return 'border-rose-200 bg-rose-50 text-rose-700';
  }
  return 'border-amber-200 bg-amber-50 text-amber-700';
}

function prettifyKey(value: string): string {
  return value
    .replaceAll('_', ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatContextValue(value: unknown): string {
  if (typeof value === 'number') {
    if (Number.isInteger(value)) {
      return `${value}`;
    }
    return value.toFixed(2);
  }
  if (typeof value === 'boolean') {
    return value ? 'Yes' : 'No';
  }
  if (typeof value === 'string') {
    return value;
  }
  if (Array.isArray(value)) {
    return value.join(', ');
  }
  if (isRecord(value)) {
    return `${Object.keys(value).length} values`;
  }
  return String(value);
}

function getProgressValue(status: TaskState | undefined, progress: number | undefined): number {
  if (status === 'completed') {
    return 100;
  }
  return Math.max(0, Math.min(100, progress ?? 0));
}

function getProgressLabel(status: TaskState | undefined, progress: number | undefined): string {
  if (status === 'failed') {
    return 'Failed';
  }

  const value = getProgressValue(status, progress);
  if (value >= 100) {
    return 'Complete';
  }
  if (value >= 70) {
    return 'Deploying...';
  }
  if (value >= 40) {
    return 'Evaluating candidates...';
  }
  if (value >= 30) {
    return 'Generating candidates...';
  }
  if (value >= 20) {
    return 'Analyzing failures...';
  }
  if (value >= 10) {
    return 'Observing...';
  }
  return 'Queued...';
}

function getProgressDescription(label: string): string {
  switch (label) {
    case 'Observing...':
      return 'The optimizer is looking at recent conversations to understand how the current agent is behaving.';
    case 'Analyzing failures...':
      return 'Recent misses are being grouped into failure patterns so the optimizer can target the right configuration area.';
    case 'Generating candidates...':
      return 'Candidate config changes are being drafted based on the observed failure patterns.';
    case 'Evaluating candidates...':
      return 'Each candidate is being scored against the acceptance gates before anything is deployed.';
    case 'Deploying...':
      return 'A deployable candidate has cleared checks and is being promoted to the active configuration.';
    case 'Complete':
      return 'This optimization cycle is complete and the latest result is ready to review below.';
    case 'Failed':
      return 'The optimization cycle stopped before completion. Review the error details and retry when ready.';
    default:
      return 'The optimizer is queued and waiting for the first stage to begin.';
  }
}

function getStepState(step: (typeof optimizeProgressSteps)[number], status: TaskState | undefined, progress: number | undefined): StepState {
  if (status === 'completed') {
    return 'complete';
  }
  const value = getProgressValue(status, progress);
  if (value >= step.max) {
    return 'complete';
  }
  if (value >= step.min) {
    return 'current';
  }
  return 'upcoming';
}

function parseHealthContextEntries(raw: string): Array<{ label: string; value: string }> {
  if (!raw) {
    return [];
  }

  try {
    const parsed = JSON.parse(raw) as unknown;
    if (isRecord(parsed)) {
      return Object.entries(parsed)
        .slice(0, 6)
        .map(([key, value]) => ({
          label: prettifyKey(key),
          value: formatContextValue(value),
        }));
    }
  } catch {
    return [{ label: 'Health context', value: raw }];
  }

  return [{ label: 'Health context', value: raw }];
}

function extractMetricEntries(metrics: Record<string, unknown>): Array<{ label: string; value: string }> {
  return Object.entries(metrics)
    .filter(([, value]) => ['number', 'string', 'boolean'].includes(typeof value))
    .slice(0, 8)
    .map(([key, value]) => {
      if (typeof value === 'number') {
        const normalized = normalizeScore(value);
        return {
          label: prettifyKey(key),
          value: normalized === null ? '—' : formatScore(normalized),
        };
      }
      return {
        label: prettifyKey(key),
        value: formatContextValue(value),
      };
    });
}

function normalizeOptimizeResult(payload: unknown): OptimizeCycleResult | null {
  if (!isRecord(payload) || typeof payload.accepted !== 'boolean' || typeof payload.status_message !== 'string') {
    return null;
  }

  return {
    accepted: payload.accepted,
    pending_review: Boolean(payload.pending_review),
    status_message: payload.status_message,
    change_description: typeof payload.change_description === 'string' ? payload.change_description : null,
    config_diff: typeof payload.config_diff === 'string' ? payload.config_diff : null,
    score_before: typeof payload.score_before === 'number' ? payload.score_before : null,
    score_after: typeof payload.score_after === 'number' ? payload.score_after : null,
    deploy_message: typeof payload.deploy_message === 'string' ? payload.deploy_message : null,
    search_strategy: typeof payload.search_strategy === 'string' ? payload.search_strategy : 'simple',
    selected_operator_family:
      typeof payload.selected_operator_family === 'string' ? payload.selected_operator_family : null,
    pareto_front: Array.isArray(payload.pareto_front)
      ? payload.pareto_front.filter((candidate): candidate is Record<string, unknown> => isRecord(candidate))
      : [],
    pareto_recommendation_id:
      typeof payload.pareto_recommendation_id === 'string' ? payload.pareto_recommendation_id : null,
    governance_notes: Array.isArray(payload.governance_notes)
      ? payload.governance_notes.filter((note): note is string => typeof note === 'string' && note.length > 0)
      : [],
    global_dimensions: isRecord(payload.global_dimensions) ? payload.global_dimensions : {},
  };
}

function getAttemptImpact(attempt: OptimizationAttempt): string {
  switch (attempt.status) {
    case 'accepted':
      return 'Deployed to the active config';
    case 'pending_review':
      return 'Awaiting human review';
    case 'rejected_human':
      return 'Rejected during human review';
    case 'rejected_noop':
      return 'No config change';
    case 'error':
      return 'Failed before deployment';
    default:
      return 'Rejected by acceptance gates';
  }
}

function getAttemptLabel(attempt: OptimizationAttempt): string {
  if (attempt.status === 'rejected_noop') {
    return 'no-op';
  }
  if (attempt.status === 'rejected_human') {
    return 'rejected';
  }
  return attempt.status;
}

function getResultLabel(result: OptimizeCycleResult): string {
  if (result.pending_review) {
    return 'pending_review';
  }
  if (result.accepted) {
    return 'accepted';
  }
  if (!result.config_diff) {
    return 'no-op';
  }
  return 'rejected';
}

function ResultStat({
  label,
  value,
  helper,
  valueClassName,
}: {
  label: string;
  value: string;
  helper?: string;
  valueClassName?: string;
}) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white px-4 py-3 shadow-sm">
      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-500">{label}</p>
      <p className={classNames('mt-2 text-lg font-semibold text-gray-900', valueClassName)}>{value}</p>
      {helper ? <p className="mt-1 text-xs text-gray-500">{helper}</p> : null}
    </div>
  );
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

/** Summarize the optimize gate from selected agent, eval context, and pending proposal evidence. */
function getOptimizeJourneySummary(input: {
  activeAgent: AgentLibraryItem | null;
  evalRunId: string | null;
  pendingReviews: PendingReview[];
  taskIsRunning: boolean;
}) {
  if (input.pendingReviews.length > 0) {
    return createJourneyStatusSummary({
      currentStep: 'optimize',
      status: 'ready',
      statusLabel: `${input.pendingReviews.length} proposal${input.pendingReviews.length === 1 ? '' : 's'} ready`,
      summary: 'Optimize has proposal evidence waiting for human review. Review before deployment.',
      nextLabel: 'Review proposals',
      nextDescription: 'Open the unified review queue for pending optimization proposals.',
      href: '/improvements?tab=review',
    });
  }

  if (input.taskIsRunning) {
    return createJourneyStatusSummary({
      currentStep: 'optimize',
      status: 'active',
      statusLabel: 'Optimization running',
      summary: 'Wait for the active optimization cycle to finish before reviewing proposals.',
      nextLabel: 'Wait for results',
      nextDescription: 'The review step becomes available after a proposal is produced.',
    });
  }

  if (input.activeAgent && input.evalRunId) {
    return createJourneyStatusSummary({
      currentStep: 'optimize',
      status: 'ready',
      statusLabel: 'Eval context loaded',
      summary: `${input.activeAgent.name} and eval run ${input.evalRunId.slice(0, 8)} are selected for this optimization cycle.`,
      nextLabel: 'Start optimization',
      nextDescription: 'Run Optimize, then review any proposal before Deploy.',
    });
  }

  if (input.activeAgent) {
    return createJourneyStatusSummary({
      currentStep: 'optimize',
      status: 'waiting',
      statusLabel: 'Eval recommended',
      summary: `${input.activeAgent.name} is selected. Run or choose an eval first so Optimize has evidence.`,
      nextLabel: 'Run eval',
      nextDescription: 'Open Eval Runs with this agent selected.',
      href: `/evals?agent=${encodeURIComponent(input.activeAgent.id)}&new=1`,
    });
  }

  return createJourneyStatusSummary({
    currentStep: 'optimize',
    status: 'blocked',
    statusLabel: 'Agent needed',
    summary: 'Select a saved candidate and completed eval run before optimizing.',
    nextLabel: 'Select agent',
    nextDescription: 'Choose an agent from the library on this page.',
  });
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
  const requestedEvalRunId = journeyState?.evalRunId ?? searchParams.get('evalRunId');
  const workbenchRouteContext = useMemo(
    () => parseWorkbenchOptimizeContext(searchParams),
    [searchParams]
  );
  const workbenchBridgeQuery = useWorkbenchBridge(workbenchRouteContext?.projectId, {
    enabled: Boolean(workbenchRouteContext?.projectId),
    evalRunId: requestedEvalRunId,
  });
  const workbenchBridge = workbenchBridgeQuery.data?.bridge ?? null;
  const selectedEvalRunId =
    requestedEvalRunId ?? workbenchBridge?.optimization.request_template?.eval_run_id ?? null;
  const workbenchContext = useMemo(() => {
    if (!workbenchRouteContext) {
      return null;
    }
    const candidateName =
      workbenchBridge?.candidate.agent_name ??
      workbenchRouteContext.candidateName;
    const configPath =
      workbenchBridge?.candidate.config_path ??
      workbenchBridge?.optimization.request_template?.config_path ??
      workbenchRouteContext.configPath;
    const journeyId =
      workbenchBridge?.journey_id ??
      workbenchRouteContext.journeyId;
    const evalHref =
      workbenchBridge?.evaluation.primary_action_target ??
      buildWorkbenchEvalHref({
        projectId: workbenchRouteContext.projectId,
        journeyId,
      });
    return {
      projectId: workbenchRouteContext.projectId,
      journeyId,
      candidateName,
      configPath,
      evalHref,
    };
  }, [workbenchBridge, workbenchRouteContext]);

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
        description="Run optimization cycles and review live progress, accepted changes, and next steps in one place."
        actions={
          <Link
            to="/improvements"
            className="rounded-lg border border-gray-300 bg-white px-3.5 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
          >
            Open Review
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

      {workbenchContext && !selectedEvalRunId && (
        <section className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-sm font-semibold text-amber-950">Run Eval first</p>
              <p className="mt-1 text-sm leading-6 text-amber-900">
                {workbenchContext.candidateName} is saved, but Optimize needs a completed Eval run from this Workbench candidate.
              </p>
              {workbenchContext.configPath ? (
                <p className="mt-2 break-all font-mono text-xs text-amber-800">{workbenchContext.configPath}</p>
              ) : null}
            </div>
            <Link
              to={workbenchContext.evalHref}
              className="inline-flex items-center justify-center rounded-lg bg-gray-900 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-gray-800"
            >
              Open Eval with this candidate
            </Link>
          </div>
        </section>
      )}

      {workbenchContext && selectedEvalRunId && (
        <section className="rounded-lg border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-900">
          <p className="font-semibold">Workbench Eval context ready</p>
          <p className="mt-1">
            Eval run <span className="font-mono">{selectedEvalRunId}</span> is ready to seed Optimize for{' '}
            <span className="font-semibold">{workbenchContext.candidateName}</span>.
          </p>
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
          <OptimizeRunSection
            activeAgent={activeAgent}
            evalRunId={selectedEvalRunId}
            workbenchContext={workbenchContext}
            workbenchBridgeLoading={workbenchBridgeQuery.isLoading}
          />
        </section>
      )}
      {visitedTabs.has('live') && (
        <section hidden={activeTab !== 'live'}>
          <LiveOptimize
            activeAgentName={activeAgent?.name ?? null}
            requireSelectedAgent
          />
        </section>
      )}
    </div>
  );
}

function OptimizeRunSection({
  activeAgent,
  evalRunId,
  workbenchContext,
  workbenchBridgeLoading,
}: {
  activeAgent: AgentLibraryItem | null;
  evalRunId: string | null;
  workbenchContext: WorkbenchOptimizeContext | null;
  workbenchBridgeLoading: boolean;
}) {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { data: history, isLoading, refetch } = useOptimizeHistory();
  const startOptimize = useStartOptimize();
  const approveReview = useApproveReview();
  const rejectReview = useRejectReview();

  const [windowSize, setWindowSize] = useState(100);
  const [force, setForce] = useState(() => searchParams.get('new') === '1');
  const [requireHumanApproval, setRequireHumanApproval] = useState(true);
  const [expandedAttempt, setExpandedAttempt] = useState<string | null>(null);
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [activeTaskAgent, setActiveTaskAgent] = useState<AgentLibraryItem | null>(null);
  const [activeTaskStartedAt, setActiveTaskStartedAt] = useState<string | null>(null);
  const [completedRun, setCompletedRun] = useState<CompletedOptimizationSummary | null>(null);
  const [latestResult, setLatestResult] = useState<PersistedOptimizeResult | null>(null);
  const [optimizeMode, setOptimizeMode] = useState<OptimizeMode>('standard');
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [objective, setObjective] = useState('');
  const [guardrails, setGuardrails] = useState<string[]>([]);
  const [newGuardrail, setNewGuardrail] = useState('');
  const [researchAlgorithm, setResearchAlgorithm] = useState('bayesian');
  const [budgetCycles, setBudgetCycles] = useState(10);
  const [budgetDollars, setBudgetDollars] = useState(50);
  const [now, setNow] = useState(() => Date.now());

  const taskStatus = useTaskStatus(activeTaskId);
  const handledTerminalTaskId = useRef<string | null>(null);
  const taskIsRunning =
    !!activeTaskId &&
    (!taskStatus.data ||
      taskStatus.data.status === 'running' ||
      taskStatus.data.status === 'pending');
  const {
    data: pendingReviews = [],
    refetch: refetchPendingReviews,
  } = usePendingReviews(taskIsRunning);
  const journeySummary = getOptimizeJourneySummary({
    activeAgent,
    evalRunId,
    pendingReviews,
    taskIsRunning,
  });

  useEffect(() => {
    const handleOptimizationEvent = (
      payload: unknown,
      toastVariant: 'success' | 'info' = 'info'
    ) => {
      const data = payload as { task_id: string; accepted: boolean; status: string };
      if (activeTaskId && data.task_id === activeTaskId) {
        void taskStatus.refetch();
        void refetch();
        void refetchPendingReviews();
        return;
      }

      if (toastVariant === 'success' && data.accepted) {
        toastSuccess('Optimization accepted', data.status);
      } else {
        toastInfo('Optimization completed', data.status);
      }
      void refetch();
      void refetchPendingReviews();
    };
    const unsubscribeComplete = wsClient.onMessage('optimize_complete', (payload) => {
      handleOptimizationEvent(payload, 'success');
    });
    const unsubscribePending = wsClient.onMessage('optimize_pending_review', (payload) => {
      handleOptimizationEvent(payload);
    });

    return () => {
      unsubscribeComplete();
      unsubscribePending();
    };
  }, [activeTaskId, refetch, refetchPendingReviews, taskStatus.refetch]);

  useEffect(() => {
    if (!taskStatus.data || taskStatus.data.task_id === handledTerminalTaskId.current) {
      return;
    }

    if (taskStatus.data.status === 'completed') {
      const result = normalizeOptimizeResult(taskStatus.data.result);
      const finishedAgent = activeTaskAgent ?? activeAgent ?? null;
      if (result) {
        setLatestResult({
          agent: finishedAgent,
          taskId: taskStatus.data.task_id,
          startedAt: taskStatus.data.created_at,
          completedAt: taskStatus.data.updated_at,
          result,
        });
        setCompletedRun({
          agent: finishedAgent,
          accepted: result.accepted,
          pendingReview: result.pending_review,
        });
        if (result.pending_review) {
          toastInfo(
            'Cycle complete — proposal ready for review',
            result.status_message || 'Review the proposal below before deployment.',
          );
        } else if (result.accepted) {
          toastSuccess(
            'Cycle complete — change accepted',
            result.status_message || 'Optimizer applied a winning proposal this cycle.',
          );
        } else {
          toastInfo(
            'Cycle complete — no deployable change',
            result.status_message || 'Optimizer ran but found no improvement this cycle.',
          );
        }
      }
      handledTerminalTaskId.current = taskStatus.data.task_id;
      void refetch();
      void refetchPendingReviews();
    }

    if (taskStatus.data.status === 'failed') {
      toastError('Optimization failed', taskStatus.data.error || 'Unknown error');
      handledTerminalTaskId.current = taskStatus.data.task_id;
    }
  }, [activeAgent, activeTaskAgent, refetch, taskStatus.data]);

  useEffect(() => {
    if (!taskIsRunning) {
      return;
    }
    setNow(Date.now());
    const intervalId = window.setInterval(() => {
      setNow(Date.now());
    }, 1000);
    return () => window.clearInterval(intervalId);
  }, [taskIsRunning]);

  const trajectoryData = useMemo(() => {
    return (history || []).slice().reverse().map((attempt, index) => ({
      label: `#${index + 1}`,
      score: attempt.score_after,
    }));
  }, [history]);

  const attempts = history || [];
  const workbenchAgent: AgentLibraryItem | null =
    !activeAgent && workbenchContext?.configPath
      ? {
          id: `workbench-${workbenchContext.projectId ?? 'candidate'}`,
          name: workbenchContext.candidateName,
          model: 'workbench',
          created_at: new Date().toISOString(),
          source: 'built',
          config_path: workbenchContext.configPath,
          status: 'candidate',
        }
      : null;
  const effectiveAgent = activeAgent ?? workbenchAgent;
  const isWorkbenchEvalMissing = Boolean(workbenchContext && !evalRunId);
  const progressValue = getProgressValue(taskStatus.data?.status, taskStatus.data?.progress);
  const progressLabel = getProgressLabel(taskStatus.data?.status, taskStatus.data?.progress);
  const progressDescription = getProgressDescription(progressLabel);
  const activeRunAgent = activeTaskAgent ?? effectiveAgent ?? null;
  const activeTaskStart = taskStatus.data?.created_at ?? activeTaskStartedAt;
  const elapsedSeconds =
    activeTaskStart && Number.isFinite(Date.parse(activeTaskStart))
      ? Math.max(0, Math.floor((now - Date.parse(activeTaskStart)) / 1000))
      : 0;
  const latestResultDelta = latestResult
    ? scoreDelta(latestResult.result.score_before, latestResult.result.score_after)
    : null;
  const latestResultMetrics = latestResult ? extractMetricEntries(latestResult.result.global_dimensions) : [];
  const latestResultDuration =
    latestResult &&
    Number.isFinite(Date.parse(latestResult.startedAt)) &&
    Number.isFinite(Date.parse(latestResult.completedAt))
      ? Math.max(
          0,
          Math.floor((Date.parse(latestResult.completedAt) - Date.parse(latestResult.startedAt)) / 1000)
        )
      : null;

  const resultActionAgent = latestResult?.agent ?? completedRun?.agent ?? activeTaskAgent ?? effectiveAgent;
  const hasFailure = taskStatus.data?.status === 'failed';

  function navigateToEval(agent: AgentLibraryItem | null) {
    if (workbenchContext?.projectId) {
      navigate(workbenchContext.evalHref);
      return;
    }
    if (!agent) {
      toastError('Select an agent', 'Pick an agent from the library before navigating to eval.');
      return;
    }

    navigate(`/evals?agent=${encodeURIComponent(agent.id)}&new=1`, { state: { agent } });
  }

  function scrollToPendingReviews() {
    if (typeof document === 'undefined') {
      return;
    }
    document.getElementById('pending-reviews')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function handleApproveReview(review: PendingReview) {
    approveReview.mutate(
      { attemptId: review.attempt_id },
      {
        onSuccess: (payload) => {
          toastSuccess('Review approved', payload.deploy_message || payload.message);
          void refetch();
          void refetchPendingReviews();
        },
        onError: (error) => {
          toastError('Approve failed', error.message);
        },
      }
    );
  }

  function handleRejectReview(review: PendingReview) {
    rejectReview.mutate(
      { attemptId: review.attempt_id },
      {
        onSuccess: (payload) => {
          toastInfo('Review rejected', payload.message);
          void refetch();
          void refetchPendingReviews();
        },
        onError: (error) => {
          toastError('Reject failed', error.message);
        },
      }
    );
  }

  function handleStart(forceOverride?: boolean) {
    if (isWorkbenchEvalMissing) {
      toastError('Run Eval first', 'Optimize needs a completed Eval run from this Workbench candidate.');
      return;
    }

    if (!effectiveAgent) {
      toastError('Select an agent', 'Pick an agent from the library before starting optimization.');
      return;
    }

    const requestedForce = forceOverride ?? force;
    if (forceOverride !== undefined) {
      setForce(forceOverride);
    }

    setLatestResult(null);
    handledTerminalTaskId.current = null;
    setCompletedRun(null);

    if (pendingReviews.length > 0) {
      toastInfo(
        'Pending review already queued',
        'Another optimization proposal is awaiting human review. You can start a new run, but resolve the review when possible.'
      );
    }

    startOptimize.mutate(
      {
        window: windowSize,
        force: requestedForce,
        require_human_approval: requireHumanApproval,
        config_path: effectiveAgent.config_path,
        eval_run_id: evalRunId ?? undefined,
        require_eval_evidence: Boolean(evalRunId),
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
          setActiveTaskAgent(effectiveAgent);
          setActiveTaskStartedAt(new Date().toISOString());
          toastInfo(
            `Optimization ${response.task_id.slice(0, 8)} started`,
            `Running against ${effectiveAgent.name}.`
          );
        },
        onError: (error) => {
          toastError('Failed to start optimization', error.message);
        },
      }
    );
  }

  function addGuardrail() {
    const trimmed = newGuardrail.trim();
    if (!trimmed) {
      return;
    }
    setGuardrails((current) => [...current, trimmed]);
    setNewGuardrail('');
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
      {workbenchBridgeLoading && workbenchContext && !effectiveAgent ? (
        <div className="rounded-xl border border-gray-200 bg-white p-4 text-sm text-gray-500">
          Loading Workbench candidate...
        </div>
      ) : null}

      <OperatorNextStepCard
        summary={journeySummary}
        onAction={
          journeySummary.nextAction.label === 'Start optimization'
            ? () => handleStart()
            : undefined
        }
      />

      {!latestResult && completedRun && !taskIsRunning && (
        <section className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <p className="text-sm font-semibold text-emerald-900">
                {completedRun.agent ? `${completedRun.agent.name} finished its last optimization cycle` : 'Last optimization cycle finished'}
              </p>
              <p className="mt-1 text-sm text-emerald-800">
                {completedRun.pendingReview
                  ? 'A passing proposal is waiting in the review queue below. Approve it before it goes live.'
                  : completedRun.accepted
                  ? 'Re-run eval to verify the improvement or open Configs to inspect the deployed YAML.'
                  : 'Open advanced settings to adjust the search or force another run when you are ready.'}
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              {completedRun.pendingReview ? (
                <>
                  <button
                    type="button"
                    onClick={scrollToPendingReviews}
                    className="rounded-lg bg-gray-900 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-gray-800"
                  >
                    Review pending change
                  </button>
                  <Link
                    to="/improvements?tab=review"
                    className="rounded-lg border border-gray-300 bg-white px-3.5 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
                  >
                    Open Review
                  </Link>
                </>
              ) : completedRun.accepted ? (
                <>
                  <button
                    type="button"
                    onClick={() => navigateToEval(completedRun.agent)}
                    className="rounded-lg border border-gray-300 bg-white px-3.5 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
                  >
                    Re-run Eval to verify
                  </button>
                  <Link
                    to="/deploy"
                    className="inline-flex items-center gap-2 rounded-lg bg-gray-900 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-gray-800"
                  >
                    Deploy
                  </Link>
                </>
              ) : (
                <>
                  <button
                    type="button"
                    onClick={() => setShowAdvanced(true)}
                    className="rounded-lg border border-gray-300 bg-white px-3.5 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
                  >
                    Try again with different settings
                  </button>
                  <Link
                    to="/improvements?tab=opportunities"
                    className="rounded-lg border border-gray-300 bg-white px-3.5 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
                  >
                    View Opportunities
                  </Link>
                  <button
                    type="button"
                    onClick={() => handleStart(true)}
                    disabled={startOptimize.isPending || taskIsRunning || !activeAgent}
                    className="rounded-lg bg-gray-900 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-gray-800 disabled:opacity-60"
                  >
                    Force optimize
                  </button>
                </>
              )}
            </div>
          </div>
        </section>
      )}

      {taskIsRunning ? (
        <section className="rounded-2xl border border-sky-200 bg-gradient-to-br from-sky-50 via-white to-white p-6 shadow-sm">
          <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:justify-between">
            <div className="max-w-2xl">
              <div className="flex flex-wrap items-center gap-2">
                <span className="inline-flex items-center gap-2 rounded-full border border-sky-200 bg-white px-3 py-1 text-xs font-semibold text-sky-800">
                  <Workflow className="h-3.5 w-3.5" />
                  Optimization running
                </span>
                {activeRunAgent ? (
                  <span className="rounded-full border border-gray-200 bg-white px-3 py-1 text-xs font-medium text-gray-600">
                    {activeRunAgent.name}
                  </span>
                ) : null}
              </div>
              <h3 className="mt-4 text-3xl font-semibold tracking-tight text-gray-900">{progressLabel}</h3>
              <p className="mt-2 text-sm leading-relaxed text-gray-600">{progressDescription}</p>
            </div>

            <div className="grid w-full gap-3 sm:grid-cols-3 lg:max-w-xl">
              <ResultStat label="Progress" value={`${progressValue}%`} helper="Current cycle" />
              <ResultStat label="Elapsed" value={`${formatDuration(elapsedSeconds)} elapsed`} helper="Since start" />
              <ResultStat
                label="Task"
                value={activeTaskId ? activeTaskId.slice(0, 8) : 'Pending'}
                helper="Background task id"
              />
            </div>
          </div>

          <div className="mt-6">
            <div className="mb-2 flex items-center justify-between text-sm font-medium text-gray-700">
              <span>Optimization progress</span>
              <span>{progressValue}%</span>
            </div>
            <div
              role="progressbar"
              aria-label="Optimization progress"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={progressValue}
              className="h-3 overflow-hidden rounded-full bg-sky-100"
            >
              <div
                className="h-full rounded-full bg-sky-600 transition-all duration-300"
                style={{ width: `${progressValue}%` }}
              />
            </div>
          </div>

          <div className="mt-6 grid gap-2 lg:grid-cols-5">
            {optimizeProgressSteps.map((step) => {
              const state = getStepState(step, taskStatus.data?.status, taskStatus.data?.progress);
              return (
                <div
                  key={step.key}
                  className={classNames(
                    'rounded-xl border px-3 py-3 text-sm',
                    state === 'complete' && 'border-emerald-200 bg-emerald-50 text-emerald-700',
                    state === 'current' && 'border-sky-200 bg-sky-100 text-sky-800 shadow-sm',
                    state === 'upcoming' && 'border-gray-200 bg-white text-gray-500'
                  )}
                >
                  <p className="font-semibold">{step.shortLabel}</p>
                </div>
              );
            })}
          </div>
        </section>
      ) : latestResult ? (
        <section className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
          <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:justify-between">
            <div className="max-w-2xl">
              <div className="flex flex-wrap items-center gap-2">
                <StatusBadge variant={statusVariant(getResultLabel(latestResult.result))} label={getResultLabel(latestResult.result)} />
                {latestResult.agent ? (
                  <span className="rounded-full border border-gray-200 bg-gray-50 px-3 py-1 text-xs font-medium text-gray-600">
                    {latestResult.agent.name}
                  </span>
                ) : null}
                <span className="rounded-full border border-gray-200 bg-white px-3 py-1 text-xs font-medium text-gray-500">
                  Task {latestResult.taskId.slice(0, 8)}
                </span>
              </div>
              <h3 className="mt-4 text-3xl font-semibold tracking-tight text-gray-900">
                {latestResult.result.status_message}
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-gray-600">
                {latestResult.result.change_description ||
                  (latestResult.result.accepted
                    ? 'A configuration change was accepted and deployed.'
                    : 'The optimizer finished without a deployable change this cycle.')}
              </p>
            </div>

            <div className="flex items-start gap-3">
              <div className={classNames('rounded-2xl border px-5 py-4 text-right shadow-sm', deltaTone(latestResultDelta))}>
                <p className="text-[11px] font-semibold uppercase tracking-[0.18em]">Composite delta</p>
                <p className="mt-2 text-3xl font-semibold">{formatDeltaValue(latestResultDelta)}</p>
              </div>
              <button
                type="button"
                aria-label="Dismiss latest result"
                onClick={() => setLatestResult(null)}
                className="rounded-lg border border-gray-200 p-2 text-gray-400 transition hover:border-gray-300 hover:text-gray-600"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>

          <div className="mt-6 grid gap-3 md:grid-cols-4">
            <ResultStat label="Score before" value={formatScoreValue(latestResult.result.score_before)} />
            <ResultStat label="Score after" value={formatScoreValue(latestResult.result.score_after)} />
            <ResultStat
              label="Strategy used"
              value={prettifyKey(latestResult.result.search_strategy)}
              helper={
                latestResult.result.selected_operator_family
                  ? `Operator family: ${prettifyKey(latestResult.result.selected_operator_family)}`
                  : undefined
              }
            />
            <ResultStat
              label="Completed"
              value={formatTimestamp(latestResult.completedAt)}
              helper={latestResultDuration !== null ? `${formatDuration(latestResultDuration)} total runtime` : undefined}
            />
          </div>

          {latestResultMetrics.length > 0 ? (
            <div className="mt-6">
              <div className="mb-3 flex items-center gap-2">
                <Gauge className="h-4 w-4 text-gray-400" />
                <h4 className="text-sm font-semibold text-gray-900">Score breakdown</h4>
              </div>
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                {latestResultMetrics.map((entry) => (
                  <ResultStat key={entry.label} label={entry.label} value={entry.value} />
                ))}
              </div>
            </div>
          ) : null}

          <div className="mt-6 grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
            <div>
              <div className="mb-3 flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-gray-400" />
                <h4 className="text-sm font-semibold text-gray-900">Config diff</h4>
              </div>
              {latestResult.result.config_diff ? (
                <DiffViewer lines={parseDiffLines(latestResult.result.config_diff)} versionA={0} versionB={1} />
              ) : (
                <div className="rounded-xl border border-dashed border-gray-200 bg-gray-50 p-4 text-sm text-gray-500">
                  No config diff was recorded for this cycle.
                </div>
              )}
            </div>

            <div className="space-y-4">
              <div className="rounded-xl border border-gray-200 bg-gray-50 p-4">
                <h4 className="text-sm font-semibold text-gray-900">Deployment</h4>
                <p className="mt-2 text-sm text-gray-600">
                  {latestResult.result.deploy_message ||
                    (latestResult.result.accepted
                      ? 'Accepted and deployed to the active config.'
                      : 'No deployment happened because no candidate cleared the acceptance gates.')}
                </p>
              </div>

              <div className="rounded-xl border border-gray-200 bg-gray-50 p-4">
                <h4 className="text-sm font-semibold text-gray-900">Governance notes</h4>
                {latestResult.result.governance_notes.length > 0 ? (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {latestResult.result.governance_notes.map((note) => (
                      <span
                        key={note}
                        className="rounded-full border border-emerald-200 bg-white px-3 py-1 text-xs font-medium text-emerald-700"
                      >
                        {note}
                      </span>
                    ))}
                  </div>
                ) : (
                  <p className="mt-2 text-sm text-gray-600">No extra governance notes were returned for this cycle.</p>
                )}

                {latestResult.result.pareto_recommendation_id ? (
                  <p className="mt-3 text-xs text-gray-500">
                    Pareto recommendation: <span className="font-mono">{latestResult.result.pareto_recommendation_id}</span>
                  </p>
                ) : null}
              </div>
            </div>
          </div>

          <div className="mt-6 flex flex-wrap gap-3">
            {latestResult.result.pending_review ? (
              <>
                <button
                  type="button"
                  onClick={scrollToPendingReviews}
                  className="inline-flex items-center gap-2 rounded-lg bg-gray-900 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-gray-800"
                >
                  <Clock3 className="h-4 w-4" />
                  Review pending change
                </button>
                <Link
                  to="/improvements?tab=review"
                  className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3.5 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
                >
                  Open Review
                  <ArrowUpRight className="h-4 w-4" />
                </Link>
              </>
            ) : latestResult.result.accepted ? (
              <>
                <button
                  type="button"
                  onClick={() => navigateToEval(resultActionAgent)}
                  className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3.5 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
                >
                  <RotateCcw className="h-4 w-4" />
                  Re-run Eval to verify
                </button>
                <Link
                  to="/improvements?tab=history"
                  className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3.5 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
                >
                  View review history
                </Link>
                <Link
                  to="/deploy"
                  className="inline-flex items-center gap-2 rounded-lg bg-gray-900 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-gray-800"
                >
                  <ArrowUpRight className="h-4 w-4" />
                  Deploy
                </Link>
              </>
            ) : (
              <>
                <button
                  type="button"
                  onClick={() => setShowAdvanced(true)}
                  className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3.5 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
                >
                  <SlidersHorizontal className="h-4 w-4" />
                  Try again with different settings
                </button>
                <Link
                  to="/improvements?tab=opportunities"
                  className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3.5 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
                >
                  View Opportunities
                </Link>
                <button
                  type="button"
                  onClick={() => handleStart(true)}
                  disabled={startOptimize.isPending || taskIsRunning || !effectiveAgent || isWorkbenchEvalMissing}
                  className="inline-flex items-center gap-2 rounded-lg bg-gray-900 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-gray-800 disabled:opacity-60"
                >
                  <RotateCcw className="h-4 w-4" />
                  Force optimize
                </button>
              </>
            )}
          </div>
        </section>
      ) : (
        <section className="rounded-2xl border border-dashed border-gray-200 bg-gray-50 p-6">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div className="max-w-2xl">
              <div className="inline-flex items-center gap-2 rounded-full border border-gray-200 bg-white px-3 py-1 text-xs font-semibold text-gray-700">
                <Sparkles className="h-3.5 w-3.5" />
                Ready to optimize
              </div>
              <h3 className="mt-4 text-3xl font-semibold tracking-tight text-gray-900">
                {effectiveAgent ? `Optimize ${effectiveAgent.name}` : 'Select an agent to begin'}
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-gray-600">
                {isWorkbenchEvalMissing
                  ? 'Run Eval on this Workbench candidate first so Optimize has failure evidence to improve.'
                  : effectiveAgent
                  ? 'Run a cycle to inspect recent failures, evaluate new candidates, and promote safe improvements into the active config.'
                  : 'Pick a saved agent above so Optimize and Eval can stay on the same configuration.'}
              </p>
            </div>
            <div className="rounded-2xl border border-gray-200 bg-white px-5 py-4 shadow-sm">
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-500">Main outcome</p>
              <p className="mt-2 text-lg font-semibold text-gray-900">Live progress, rich results, clear next steps</p>
            </div>
          </div>
        </section>
      )}

      {hasFailure ? (
        <section className="rounded-xl border border-red-200 bg-red-50 px-4 py-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <p className="text-sm font-semibold text-red-900">Optimization failed</p>
              <p className="mt-1 text-sm leading-relaxed text-red-800">
                {taskStatus.data?.error || 'The optimizer stopped before it could finish this cycle.'}
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => setShowAdvanced(true)}
                className="rounded-lg border border-red-200 bg-white px-3.5 py-2 text-sm font-medium text-red-700 transition hover:bg-red-100"
              >
                Review settings
              </button>
              <button
                type="button"
                onClick={() => handleStart(force)}
                disabled={startOptimize.isPending || taskIsRunning || !activeAgent}
                className="rounded-lg bg-red-600 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-red-700 disabled:opacity-60"
              >
                Try again
              </button>
            </div>
          </div>
        </section>
      ) : null}

      <section className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
        <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:justify-between">
          <div className="max-w-2xl">
            <div className="inline-flex items-center gap-2 rounded-full border border-gray-200 bg-gray-50 px-3 py-1 text-xs font-semibold text-gray-700">
              <Bot className="h-3.5 w-3.5" />
              Run setup
            </div>
            <div className="mt-4 rounded-2xl border border-gray-200 bg-gray-50 p-4">
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-500">Selected agent</p>
              <p className="mt-2 text-lg font-semibold text-gray-900">
                {effectiveAgent ? effectiveAgent.name : 'Choose an agent from the library'}
              </p>
              <p className="mt-1 text-sm text-gray-600">
                {effectiveAgent ? effectiveAgent.config_path : 'The optimizer needs a saved config before it can start.'}
              </p>
              {evalRunId ? (
                <p className="mt-2 text-xs text-sky-700">
                  Using eval context from run <span className="font-mono">{evalRunId.slice(0, 8)}</span>.
                </p>
              ) : null}
            </div>
          </div>

          <div className="w-full max-w-sm rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-500">Start a cycle</p>
            <button
              type="button"
              onClick={() => handleStart()}
              disabled={startOptimize.isPending || taskIsRunning || !effectiveAgent || isWorkbenchEvalMissing}
              className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-gray-900 px-4 py-3 text-sm font-medium text-white transition hover:bg-gray-800 disabled:opacity-60"
            >
              <Play className="h-4 w-4" />
              {startOptimize.isPending || taskIsRunning ? 'Running...' : 'Start Optimization'}
            </button>
            <label htmlFor="require-human-approval" className="mt-4 flex items-start gap-3 rounded-xl border border-gray-200 bg-gray-50 px-3 py-3">
              <input
                id="require-human-approval"
                type="checkbox"
                checked={requireHumanApproval}
                onChange={(event) => setRequireHumanApproval(event.target.checked)}
                className="mt-0.5 h-4 w-4 rounded border-gray-300 text-emerald-600 focus:ring-emerald-500"
              />
              <span>
                <span className="block text-sm font-medium text-gray-900">Require human approval</span>
                <span className="mt-1 block text-xs text-gray-500">
                  Review proposed changes before they go live.
                </span>
              </span>
            </label>
            <p className="mt-3 text-xs text-gray-500">
              {activeAgent
                ? `This run will use ${activeAgent.name} and its saved config.`
                : workbenchAgent
                ? `This run will use ${workbenchAgent.name} and its saved Workbench config.`
                : 'Choose an agent above before you start the optimizer.'}
            </p>
          </div>
        </div>

        <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_220px]">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-500">Mode</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {(['standard', 'advanced', 'research'] as OptimizeMode[]).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  onClick={() => setOptimizeMode(mode)}
                  className={classNames(
                    'rounded-full border px-4 py-2 text-sm font-medium transition-colors',
                    optimizeMode === mode
                      ? 'border-gray-900 bg-gray-900 text-white shadow-sm'
                      : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300 hover:text-gray-900'
                  )}
                >
                  {modeLabels[mode]}
                </button>
              ))}
            </div>
            <p className="mt-3 text-sm text-gray-500">{modeDescriptions[optimizeMode]}</p>
          </div>

          <div>
            <label
              htmlFor="observation-window"
              className="block text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-500"
            >
              Observation window
            </label>
            <input
              id="observation-window"
              type="number"
              min={10}
              max={1000}
              value={windowSize}
              onChange={(event) => setWindowSize(Number(event.target.value))}
              className="mt-2 w-full rounded-xl border border-gray-300 px-3 py-2.5 text-sm focus:border-blue-500 focus:outline-none"
            />
            <p className="mt-2 text-xs text-gray-500">How many recent conversations the optimizer should inspect first.</p>
          </div>
        </div>

        <div className="mt-6 border-t border-gray-100 pt-4">
          <button
            type="button"
            onClick={() => setShowAdvanced((current) => !current)}
            aria-expanded={showAdvanced}
            className="flex w-full items-center justify-between rounded-xl border border-gray-200 bg-gray-50 px-4 py-3 text-left transition hover:bg-gray-100"
          >
            <div>
              <p className="text-sm font-semibold text-gray-900">Advanced settings</p>
              <p className="mt-1 text-sm text-gray-500">
                Objective, guardrails, force mode, and research-specific controls live here.
              </p>
            </div>
            {showAdvanced ? <ChevronUp className="h-4 w-4 text-gray-500" /> : <ChevronDown className="h-4 w-4 text-gray-500" />}
          </button>

          {showAdvanced ? (
            <div id="optimize-advanced" className="mt-4 space-y-5 rounded-2xl border border-gray-200 bg-white p-4">
              <div className="flex items-center gap-2">
                <input
                  id="force-optimization"
                  type="checkbox"
                  checked={force}
                  onChange={(event) => setForce(event.target.checked)}
                  className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                />
                <label htmlFor="force-optimization" className="text-sm text-gray-700">
                  Force optimization even if the observer says the system is healthy
                </label>
              </div>

              <div>
                <label
                  htmlFor="optimize-objective"
                  className="mb-1 block text-sm font-medium text-gray-700"
                >
                  Objective
                </label>
                <input
                  id="optimize-objective"
                  type="text"
                  placeholder="e.g. Maximize task_success_rate while maintaining safety > 0.99"
                  value={objective}
                  onChange={(event) => setObjective(event.target.value)}
                  className="w-full rounded-xl border border-gray-300 bg-white px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                />
              </div>

              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700">
                  Guardrails ({guardrails.length})
                </label>
                <div className="space-y-2">
                  {guardrails.map((guardrail, index) => (
                    <div
                      key={`${guardrail}-${index}`}
                      className="flex items-center justify-between rounded-lg border border-gray-200 bg-gray-50 px-3 py-2"
                    >
                      <span className="text-sm text-gray-700">{guardrail}</span>
                      <button
                        type="button"
                        onClick={() => setGuardrails((current) => current.filter((_, itemIndex) => itemIndex !== index))}
                        className="text-gray-400 transition hover:text-red-500"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  ))}
                  <div className="flex items-center gap-2">
                    <input
                      id="optimize-guardrail"
                      type="text"
                      placeholder="Add a guardrail..."
                      value={newGuardrail}
                      onChange={(event) => setNewGuardrail(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter') {
                          addGuardrail();
                        }
                      }}
                      className="flex-1 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                    />
                    <button
                      type="button"
                      onClick={addGuardrail}
                      className="rounded-lg border border-gray-200 bg-white p-2 text-gray-500 transition hover:bg-gray-50"
                    >
                      <Plus className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              </div>

              {optimizeMode === 'research' ? (
                <div className="space-y-4 rounded-2xl border border-blue-200 bg-blue-50 p-4">
                  <div className="rounded-lg border border-blue-200 bg-white/80 px-3 py-2 text-xs text-blue-900">
                    Research mode adjusts the backend search strategy and budget. Objective text and algorithm choice are still operator notes in this build.
                  </div>

                  <div>
                    <p className="mb-1 text-sm font-medium text-gray-700">Algorithm</p>
                    <div className="flex flex-wrap gap-2">
                      {researchAlgorithms.map((algorithm) => (
                        <button
                          key={algorithm.key}
                          type="button"
                          onClick={() => setResearchAlgorithm(algorithm.key)}
                          className={classNames(
                            'rounded-full border px-3 py-1.5 text-xs font-medium transition-colors',
                            researchAlgorithm === algorithm.key
                              ? 'border-blue-500 bg-blue-100 text-blue-800'
                              : 'border-gray-200 bg-white text-gray-600 hover:bg-gray-50'
                          )}
                        >
                          {algorithm.label}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div className="grid gap-3 sm:grid-cols-2">
                    <div>
                      <label
                        htmlFor="budget-cycles"
                        className="mb-1 block text-sm font-medium text-gray-700"
                      >
                        Budget (cycles)
                      </label>
                      <input
                        id="budget-cycles"
                        type="number"
                        min={1}
                        max={100}
                        value={budgetCycles}
                        onChange={(event) => setBudgetCycles(Number(event.target.value))}
                        className="w-full rounded-xl border border-gray-300 bg-white px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                      />
                    </div>
                    <div>
                      <label
                        htmlFor="budget-dollars"
                        className="mb-1 block text-sm font-medium text-gray-700"
                      >
                        Budget ($)
                      </label>
                      <input
                        id="budget-dollars"
                        type="number"
                        min={1}
                        max={10000}
                        value={budgetDollars}
                        onChange={(event) => setBudgetDollars(Number(event.target.value))}
                        className="w-full rounded-xl border border-gray-300 bg-white px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                      />
                    </div>
                  </div>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      </section>

      <section className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-gray-900">Cycle score trajectory</h3>
          <Sparkles className="h-4 w-4 text-gray-400" />
        </div>
        {trajectoryData.length > 0 ? (
          <ScoreChart data={trajectoryData} height={260} />
        ) : (
          <div className="flex h-[260px] items-center justify-center rounded-xl border border-dashed border-gray-200 bg-gray-50 text-sm text-gray-500">
            No optimization history yet.
          </div>
        )}
      </section>

      {pendingReviews.length > 0 ? (
        <section id="pending-reviews" className="rounded-2xl border border-amber-200 bg-amber-50/60 p-6 shadow-sm">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold text-gray-900">Pending Reviews</h3>
              <p className="mt-1 text-sm text-gray-600">
                These proposals passed the eval gates but are waiting for a human decision before deployment.
              </p>
            </div>
            <Clock3 className="h-4 w-4 text-amber-700" />
          </div>

          <div className="space-y-4">
            {pendingReviews.map((review) => {
              const delta = scoreDelta(review.score_before, review.score_after);
              return (
                <article
                  key={review.attempt_id}
                  className="rounded-2xl border border-amber-200 bg-white p-5 shadow-sm"
                >
                  <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                    <div className="max-w-2xl">
                      <div className="flex flex-wrap items-center gap-2">
                        <StatusBadge variant="pending" label="pending review" />
                        <span className="rounded-full border border-gray-200 bg-gray-50 px-2.5 py-1 text-xs font-medium text-gray-600">
                          {review.strategy}
                        </span>
                        {review.selected_operator_family ? (
                          <span className="rounded-full border border-gray-200 bg-gray-50 px-2.5 py-1 text-xs font-medium text-gray-600">
                            {review.selected_operator_family}
                          </span>
                        ) : null}
                      </div>
                      <h4 className="mt-3 text-lg font-semibold text-gray-900">{review.change_description}</h4>
                      <p className="mt-2 text-sm leading-relaxed text-gray-600">{review.reasoning}</p>
                      <p className="mt-2 text-xs text-gray-500">{formatTimestamp(review.created_at)}</p>
                    </div>

                    <div className="grid gap-3 sm:grid-cols-3 lg:min-w-[360px]">
                      <ResultStat label="Before" value={formatScoreValue(review.score_before)} />
                      <ResultStat label="After" value={formatScoreValue(review.score_after)} />
                      <ResultStat
                        label="Delta"
                        value={formatDeltaValue(delta)}
                        valueClassName={classNames(
                          delta !== null && delta > 0 && 'text-emerald-700',
                          delta !== null && delta < 0 && 'text-rose-700',
                          delta === 0 && 'text-amber-700'
                        )}
                      />
                    </div>
                  </div>

                  <div className="mt-5 grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
                    <div>
                      <h5 className="mb-3 text-sm font-semibold text-gray-900">Config diff</h5>
                      <DiffViewer lines={parseDiffLines(review.config_diff)} versionA={0} versionB={1} />
                    </div>

                    <div className="space-y-4">
                      <div className="rounded-xl border border-gray-200 bg-gray-50 p-4">
                        <h5 className="text-sm font-semibold text-gray-900">Governance notes</h5>
                        {review.governance_notes.length > 0 ? (
                          <div className="mt-3 space-y-2">
                            {review.governance_notes.map((note, index) => (
                              <p key={`${review.attempt_id}-note-${index}`} className="text-sm text-gray-600">
                                {note}
                              </p>
                            ))}
                          </div>
                        ) : (
                          <p className="mt-3 text-sm text-gray-500">No additional governance notes were recorded.</p>
                        )}
                      </div>

                      <div className="flex flex-wrap gap-2">
                        <button
                          type="button"
                          onClick={() => handleApproveReview(review)}
                          disabled={approveReview.isPending}
                          className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-emerald-700 disabled:opacity-60"
                        >
                          <CheckCircle2 className="h-4 w-4" />
                          Approve & Deploy
                        </button>
                        <button
                          type="button"
                          onClick={() => handleRejectReview(review)}
                          disabled={rejectReview.isPending}
                          className="inline-flex items-center gap-2 rounded-lg border border-rose-200 bg-white px-3.5 py-2 text-sm font-medium text-rose-700 transition hover:bg-rose-50 disabled:opacity-60"
                        >
                          <X className="h-4 w-4" />
                          Reject
                        </button>
                      </div>
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
        </section>
      ) : null}

      {attempts.length > 0 ? (
        <section className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold text-gray-900">Optimization history</h3>
              <p className="mt-1 text-sm text-gray-500">
                Expand any attempt to inspect the config diff, score movement, and deployment outcome.
              </p>
            </div>
            <Clock3 className="h-4 w-4 text-gray-400" />
          </div>

          <div className="hidden rounded-xl border border-gray-200 bg-gray-50 px-4 py-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-500 lg:grid lg:grid-cols-[190px_140px_110px_minmax(0,1fr)_24px]">
            <span>Time</span>
            <span>Status</span>
            <span>Score delta</span>
            <span>Change</span>
            <span />
          </div>

          <div className="divide-y divide-gray-100">
            {attempts.map((attempt) => {
              const expanded = expandedAttempt === attempt.attempt_id;
              const impact = getAttemptImpact(attempt);
              const contextEntries = parseHealthContextEntries(attempt.health_context);

              return (
                <div key={attempt.attempt_id} className="py-3">
                  <button
                    type="button"
                    onClick={() =>
                      setExpandedAttempt((current) => (current === attempt.attempt_id ? null : attempt.attempt_id))
                    }
                    aria-expanded={expanded}
                    className="w-full rounded-xl px-2 py-2 text-left transition hover:bg-gray-50"
                  >
                    <div className="flex flex-col gap-3 lg:grid lg:grid-cols-[190px_140px_110px_minmax(0,1fr)_24px] lg:items-center">
                      <div>
                        <p className="text-sm font-medium text-gray-900">{formatTimestamp(attempt.timestamp)}</p>
                        <p className="text-xs text-gray-500">{attempt.attempt_id.slice(0, 12)}</p>
                      </div>

                      <div>
                        <StatusBadge variant={statusVariant(attempt.status)} label={getAttemptLabel(attempt)} />
                        <p className="mt-1 text-xs text-gray-500">{impact}</p>
                      </div>

                      <div>
                        <span
                          className={classNames(
                            'inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold',
                            deltaTone(attempt.score_delta)
                          )}
                        >
                          {formatDeltaValue(attempt.score_delta)}
                        </span>
                        <p className="mt-1 text-xs text-gray-500">
                          {formatScore(attempt.score_before)} → {formatScore(attempt.score_after)}
                        </p>
                      </div>

                      <div className="min-w-0">
                        <p className="text-sm font-medium text-gray-900">
                          {truncate(attempt.change_description || impact, 110)}
                        </p>
                        <p className="mt-1 text-xs text-gray-500">
                          {attempt.status === 'rejected_noop'
                            ? 'No config change'
                            : attempt.config_section
                              ? `Config section: ${attempt.config_section}`
                              : impact}
                        </p>
                      </div>

                      <div className="flex justify-end">
                        {expanded ? (
                          <ChevronUp className="h-4 w-4 text-gray-400" />
                        ) : (
                          <ChevronDown className="h-4 w-4 text-gray-400" />
                        )}
                      </div>
                    </div>
                  </button>

                  {expanded ? (
                    <div className="mt-3 rounded-2xl border border-gray-200 bg-gray-50 p-4">
                      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
                        <div>
                          <div className="mb-3 flex items-center gap-2">
                            {attempt.status === 'accepted' ? (
                              <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                            ) : (
                              <XCircle className="h-4 w-4 text-amber-600" />
                            )}
                            <h4 className="text-sm font-semibold text-gray-900">Config diff</h4>
                          </div>
                          {attempt.config_diff ? (
                            <DiffViewer lines={parseDiffLines(attempt.config_diff)} versionA={0} versionB={1} />
                          ) : (
                            <div className="rounded-xl border border-dashed border-gray-200 bg-white p-4 text-sm text-gray-500">
                              No config diff available for this attempt.
                            </div>
                          )}
                        </div>

                        <div className="space-y-4">
                          <div className="rounded-xl border border-gray-200 bg-white p-4">
                            <h4 className="text-sm font-semibold text-gray-900">Deployment status</h4>
                            <p className="mt-2 text-sm text-gray-600">{impact}</p>
                          </div>

                          <div className="rounded-xl border border-gray-200 bg-white p-4">
                            <h4 className="text-sm font-semibold text-gray-900">Scores</h4>
                            <div className="mt-3 grid gap-3 sm:grid-cols-2">
                              <ResultStat label="Before" value={formatScore(attempt.score_before)} />
                              <ResultStat label="After" value={formatScore(attempt.score_after)} />
                              <ResultStat
                                label="Observed delta"
                                value={formatDeltaValue(attempt.score_delta)}
                                valueClassName={classNames(
                                  attempt.score_delta > 0 && 'text-emerald-700',
                                  attempt.score_delta < 0 && 'text-rose-700',
                                  attempt.score_delta === 0 && 'text-amber-700'
                                )}
                              />
                              <ResultStat label="P-value" value={attempt.significance_p_value.toFixed(2)} />
                            </div>
                            <p className="mt-3 text-xs text-gray-500">{attempt.significance_n} paired eval cases</p>
                          </div>

                          {contextEntries.length > 0 ? (
                            <div className="rounded-xl border border-gray-200 bg-white p-4">
                              <h4 className="text-sm font-semibold text-gray-900">Health context</h4>
                              <div className="mt-3 grid gap-2">
                                {contextEntries.map((entry) => (
                                  <div
                                    key={`${attempt.attempt_id}-${entry.label}`}
                                    className="flex items-center justify-between rounded-lg border border-gray-100 bg-gray-50 px-3 py-2"
                                  >
                                    <span className="text-xs font-medium text-gray-500">{entry.label}</span>
                                    <span className="text-sm text-gray-700">{entry.value}</span>
                                  </div>
                                ))}
                              </div>
                            </div>
                          ) : null}
                        </div>
                      </div>
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        </section>
      ) : activeAgent ? (
        <EmptyState
          icon={Zap}
          state="no-data"
          title="No optimization history"
          description="Start a cycle to let the optimizer inspect failures, propose a config update, and run gate checks."
          nextAction="Start optimization to create the first cycle record."
          actionLabel="Start optimization"
          onAction={() => handleStart()}
        />
      ) : (
        <EmptyState
          icon={Zap}
          state="blocked"
          title="Pick an agent to optimize"
          description="Build or connect an agent first, then bring it here to optimize the same saved config."
          nextAction="Open Build to create a saved config, or select an existing agent from the library."
          actionLabel="Open Build"
          onAction={() => navigate('/build')}
        />
      )}
    </div>
  );
}
