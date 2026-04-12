import { Link, useSearchParams } from 'react-router-dom';
import { ArrowRight, Clock3, Flag, FlaskConical, GitPullRequest, Rocket } from 'lucide-react';
import { PageHeader } from '../components/PageHeader';
import { StatusBadge } from '../components/StatusBadge';
import { OperatorNextStepCard } from '../components/OperatorNextStepCard';
import { UnifiedReviewQueue } from './UnifiedReviewQueue';
import { Experiments } from './Experiments';
import { Opportunities } from './Opportunities';
import { useExperiments, useOptimizeHistory, useUnifiedReviewStats } from '../lib/api';
import { createJourneyStatusSummary } from '../lib/operator-journey';
import { formatTimestamp, statusVariant, classNames } from '../lib/utils';

type ImprovementsTab = 'opportunities' | 'experiments' | 'review' | 'history';

const IMPROVEMENTS_TABS: Array<{ key: ImprovementsTab; label: string }> = [
  { key: 'opportunities', label: 'Opportunities' },
  { key: 'experiments', label: 'Experiments' },
  { key: 'review', label: 'Review' },
  { key: 'history', label: 'History' },
];

const WORKFLOW_STEPS: Array<{
  key: ImprovementsTab;
  title: string;
  description: string;
  icon: typeof Flag;
}> = [
  {
    key: 'opportunities',
    title: 'Find the gap',
    description: 'Rank failures and opportunity clusters before making changes.',
    icon: Flag,
  },
  {
    key: 'experiments',
    title: 'Test the change',
    description: 'Compare candidate improvements with evidence and eval deltas.',
    icon: FlaskConical,
  },
  {
    key: 'review',
    title: 'Approve or reject',
    description: 'Review all pending proposals from both optimizer and change card pipelines in one unified queue.',
    icon: GitPullRequest,
  },
  {
    key: 'history',
    title: 'Track the outcome',
    description: 'Keep an audit trail of accepted and rejected improvements over time.',
    icon: Clock3,
  },
];

function normalizeTab(value: string | null): ImprovementsTab {
  return IMPROVEMENTS_TABS.some((tab) => tab.key === value)
    ? (value as ImprovementsTab)
    : 'opportunities';
}

function ImprovementsTabButton({
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

/** Summarize Review readiness from the existing unified review counters. */
function getReviewJourneySummary(input: { pendingCount: number; appliedCount: number }) {
  if (input.pendingCount > 0) {
    return createJourneyStatusSummary({
      currentStep: 'review',
      status: 'ready',
      statusLabel: `${input.pendingCount} pending`,
      summary: 'The unified review queue has proposal work waiting. Resolve it before Deploy.',
      nextLabel: 'Review proposals',
      nextDescription: 'Open the review tab and approve or reject each proposal.',
      href: '/improvements?tab=review',
    });
  }

  if (input.appliedCount > 0) {
    return createJourneyStatusSummary({
      currentStep: 'review',
      status: 'ready',
      statusLabel: `${input.appliedCount} approved`,
      summary: 'Approved improvements are ready for deployment planning.',
      nextLabel: 'Deploy approved improvements',
      nextDescription: 'Open Deploy and start a canary for the approved config.',
      href: '/deploy',
    });
  }

  return createJourneyStatusSummary({
    currentStep: 'review',
    status: 'waiting',
    statusLabel: 'No review queue',
    summary: 'No proposals are waiting for review yet. Optimize or inspect opportunities to produce a reviewable change.',
    nextLabel: 'Find proposals',
    nextDescription: 'Return to Optimize or Opportunities when you need the next proposal.',
    href: '/optimize',
  });
}

interface HistoryEntry {
  id: string;
  source: 'experiment' | 'optimizer';
  title: string;
  subtitle: string;
  status: string;
  delta: number;
  pValue: number | null;
  policy: string | null;
  timestamp: number | string;
}

function ImprovementHistoryPanel() {
  const { data: experiments = [], isLoading: expLoading, isError: expError } = useExperiments();
  const { data: attempts = [], isLoading: attLoading, isError: attError } = useOptimizeHistory();

  const isLoading = expLoading || attLoading;
  const isError = expError || attError;

  // Merge experiment decisions and optimizer attempt decisions into one timeline
  const history: HistoryEntry[] = [];

  for (const exp of experiments) {
    if (exp.status !== 'accepted' && exp.status !== 'rejected') continue;
    history.push({
      id: exp.experiment_id,
      source: 'experiment',
      title: exp.hypothesis,
      subtitle: `${exp.operator_name.replaceAll('_', ' ')}`,
      status: exp.status,
      delta: exp.significance_delta,
      pValue: exp.significance_p_value,
      policy: exp.deployment_policy,
      timestamp: exp.created_at,
    });
  }

  for (const attempt of attempts) {
    if (attempt.status !== 'accepted' && !attempt.status.startsWith('rejected')) continue;
    // Avoid duplicates — if an experiment already covers this attempt_id, skip
    if (history.some((h) => h.id === attempt.attempt_id)) continue;
    history.push({
      id: attempt.attempt_id,
      source: 'optimizer',
      title: attempt.change_description || 'Optimizer attempt',
      subtitle: attempt.config_section || 'config change',
      status: attempt.status,
      delta: attempt.score_delta / 100, // score_delta is already in percent form
      pValue: attempt.significance_p_value,
      policy: null,
      timestamp: attempt.timestamp,
    });
  }

  // Sort newest first
  history.sort((a, b) => {
    const tsA = typeof a.timestamp === 'number' ? a.timestamp : new Date(a.timestamp).getTime();
    const tsB = typeof b.timestamp === 'number' ? b.timestamp : new Date(b.timestamp).getTime();
    return tsB - tsA;
  });

  const acceptedCount = history.filter((h) => h.status === 'accepted').length;
  const rejectedCount = history.filter((h) => h.status.startsWith('rejected')).length;

  return (
    <div className="space-y-4">
      <section className="grid gap-4 md:grid-cols-4">
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <p className="text-xs text-gray-500">Total decisions</p>
          <p className="mt-1 text-2xl font-semibold text-gray-900">{history.length}</p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <p className="text-xs text-gray-500">Accepted</p>
          <p className="mt-1 text-2xl font-semibold text-green-700">{acceptedCount}</p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <p className="text-xs text-gray-500">Rejected</p>
          <p className="mt-1 text-2xl font-semibold text-red-700">{rejectedCount}</p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <p className="text-xs text-gray-500">Sources</p>
          <div className="mt-1 flex items-center gap-2">
            <span className="rounded bg-indigo-50 px-1.5 py-0.5 text-[10px] font-medium text-indigo-700">
              Optimizer
            </span>
            <span className="rounded bg-violet-50 px-1.5 py-0.5 text-[10px] font-medium text-violet-700">
              Experiments
            </span>
          </div>
        </div>
      </section>

      {isLoading && (
        <div className="flex h-32 items-center justify-center rounded-xl border border-dashed border-gray-200 bg-gray-50 text-sm text-gray-500">
          Loading improvement history...
        </div>
      )}

      {isError && (
        <div className="flex h-32 items-center justify-center rounded-xl border border-dashed border-red-200 bg-red-50 text-sm text-red-600">
          Failed to load improvement history.
        </div>
      )}

      {!isLoading && !isError && history.length === 0 && (
        <div className="flex h-32 items-center justify-center rounded-xl border border-dashed border-gray-200 bg-gray-50 text-sm text-gray-500">
          No completed improvements yet.
        </div>
      )}

      {!isLoading && !isError && history.length > 0 && (
        <section className="rounded-lg border border-gray-200 bg-white p-5">
          <h3 className="mb-4 text-sm font-semibold text-gray-900">Decision history</h3>
          <div className="space-y-3">
            {history.map((entry) => (
              <div key={entry.id} className="rounded-lg border border-gray-200 bg-gray-50 p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="font-mono text-xs text-gray-500">{entry.id}</p>
                      <span
                        className={classNames(
                          'rounded px-1.5 py-0.5 text-[10px] font-medium',
                          entry.source === 'optimizer'
                            ? 'bg-indigo-50 text-indigo-700'
                            : 'bg-violet-50 text-violet-700'
                        )}
                      >
                        {entry.source === 'optimizer' ? 'Optimizer' : 'Experiment'}
                      </span>
                    </div>
                    <p className="mt-1 text-sm font-medium text-gray-900">{entry.title}</p>
                    <p className="mt-1 text-xs text-gray-500">
                      {entry.subtitle} &middot; {formatTimestamp(entry.timestamp)}
                    </p>
                  </div>
                  <StatusBadge
                    variant={statusVariant(entry.status)}
                    label={entry.status}
                  />
                </div>
                <div className="mt-3 grid gap-3 text-xs text-gray-600 sm:grid-cols-3">
                  <p>
                    Delta:{' '}
                    <span className={entry.delta >= 0 ? 'font-medium text-green-700' : 'font-medium text-red-700'}>
                      {entry.delta > 0 ? '+' : ''}
                      {entry.delta.toFixed(3)}
                    </span>
                  </p>
                  {entry.pValue != null && (
                    <p>
                      p-value:{' '}
                      <span className="font-medium text-gray-900">{entry.pValue.toFixed(3)}</span>
                    </p>
                  )}
                  {entry.policy && (
                    <p>
                      Policy:{' '}
                      <span className="font-medium text-gray-900">{entry.policy}</span>
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

export function Improvements() {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = normalizeTab(searchParams.get('tab'));
  const { data: reviewStats } = useUnifiedReviewStats();
  const pendingCount = reviewStats?.total_pending ?? 0;
  const appliedCount = reviewStats?.total_approved ?? 0;
  const journeySummary = getReviewJourneySummary({ pendingCount, appliedCount });

  function selectTab(tab: ImprovementsTab) {
    const next = new URLSearchParams(searchParams);
    next.set('tab', tab);
    setSearchParams(next);
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Improvements"
        description="One workflow for opportunities, experiments, approval decisions, and outcome history."
        actions={
          <div className="flex items-center gap-2">
            <Link
              to="/optimize"
              className="rounded-lg border border-gray-300 bg-white px-3.5 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
            >
              Back to Optimize
            </Link>
            <Link
              to="/deploy"
              className="inline-flex items-center gap-2 rounded-lg bg-gray-900 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-gray-800"
            >
              <Rocket className="h-4 w-4" />
              Deploy
            </Link>
          </div>
        }
      />

      <OperatorNextStepCard summary={journeySummary} />

      {appliedCount > 0 && (
        <section className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm text-emerald-900">
              <span className="font-semibold">{appliedCount} improvement{appliedCount !== 1 ? 's' : ''}</span>{' '}
              applied and ready to deploy. Verify with an eval run, then promote to production.
            </p>
            <div className="flex items-center gap-2">
              <Link
                to="/evals"
                className="rounded-lg border border-emerald-300 bg-white px-3 py-1.5 text-xs font-medium text-emerald-700 transition hover:bg-emerald-100"
              >
                Re-run Eval
              </Link>
              <Link
                to="/deploy"
                className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-700 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-emerald-800"
              >
                Deploy Now
                <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            </div>
          </div>
        </section>
      )}

      <section className="grid gap-3 lg:grid-cols-4">
        {WORKFLOW_STEPS.map(({ key, title, description, icon: Icon }, index) => (
          <div
            key={key}
            className={classNames(
              'rounded-lg border p-4 transition-colors',
              activeTab === key ? 'border-gray-900 bg-gray-900 text-white' : 'border-gray-200 bg-white'
            )}
          >
            <div className="flex items-center justify-between gap-3">
              <Icon className={classNames('h-4 w-4', activeTab === key ? 'text-white' : 'text-gray-500')} />
              {index < WORKFLOW_STEPS.length - 1 && (
                <ArrowRight className={classNames('h-4 w-4', activeTab === key ? 'text-white/70' : 'text-gray-300')} />
              )}
            </div>
            <h3 className={classNames('mt-4 text-sm font-semibold', activeTab === key ? 'text-white' : 'text-gray-900')}>
              {title}
            </h3>
            <p className={classNames('mt-1 text-sm', activeTab === key ? 'text-white/80' : 'text-gray-600')}>
              {description}
            </p>
          </div>
        ))}
      </section>

      <section className="rounded-lg border border-gray-200 bg-white p-2">
        <div className="flex flex-wrap gap-1">
          {IMPROVEMENTS_TABS.map((tab) => (
            <ImprovementsTabButton
              key={tab.key}
              active={activeTab === tab.key}
              label={tab.key === 'review' && pendingCount > 0 ? `Review (${pendingCount})` : tab.label}
              onClick={() => selectTab(tab.key)}
            />
          ))}
        </div>
      </section>

      {activeTab === 'opportunities' && <Opportunities embedded />}
      {activeTab === 'experiments' && <Experiments embedded showAnalysisPanels={false} defaultTab="all" />}
      {activeTab === 'review' && <UnifiedReviewQueue embedded />}
      {activeTab === 'history' && <ImprovementHistoryPanel />}
    </div>
  );
}
