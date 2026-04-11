import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { ArrowLeftRight, ArrowRight, Filter, FlaskConical, Sigma, Trophy } from 'lucide-react';
import { Link } from 'react-router-dom';
import {
  useConfigs,
  usePairwiseComparison,
  usePairwiseComparisons,
  useStartPairwiseComparison,
} from '../lib/api';
import { EmptyState } from '../components/EmptyState';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { PageHeader } from '../components/PageHeader';
import { toastError, toastSuccess } from '../lib/toast';
import { formatTimestamp } from '../lib/utils';
import type { PairwiseCaseResult } from '../lib/types';

type WinnerFilter = 'all' | 'tie' | 'pending_human' | string;
type SeverityFilter = 'all' | 'high' | 'medium' | 'low';
type SortMode = 'delta' | 'quality' | 'latency';
type MetricFocus = 'composite' | 'quality' | 'latency';

export function Compare() {
  const { data: comparisons, isLoading, isError, refetch } = usePairwiseComparisons();
  const { data: configs } = useConfigs();
  const startComparison = useStartPairwiseComparison();

  const [selectedComparisonId, setSelectedComparisonId] = useState<string | undefined>();
  const [winnerFilter, setWinnerFilter] = useState<WinnerFilter>('all');
  const [severityFilter, setSeverityFilter] = useState<SeverityFilter>('all');
  const [sortMode, setSortMode] = useState<SortMode>('delta');
  const [metricFocus, setMetricFocus] = useState<MetricFocus>('composite');
  const [expandedCaseId, setExpandedCaseId] = useState<string | null>(null);
  const [configA, setConfigA] = useState('');
  const [configB, setConfigB] = useState('');
  const [datasetPath, setDatasetPath] = useState('');
  const [judgeStrategy, setJudgeStrategy] = useState<'metric_delta' | 'llm_judge' | 'human_preference'>('metric_delta');

  useEffect(() => {
    const firstComparison = comparisons?.comparisons?.[0];
    if (!selectedComparisonId && firstComparison) {
      setSelectedComparisonId(firstComparison.comparison_id);
    }
  }, [comparisons, selectedComparisonId]);

  useEffect(() => {
    const entries = configs || [];
    if (!configA && entries[0]?.filename) {
      setConfigA(entries[0].filename);
    }
    if (!configB && entries[1]?.filename) {
      setConfigB(entries[1].filename);
    }
  }, [configs, configA, configB]);

  const { data: comparison, isLoading: isLoadingComparison, isError: isComparisonError } =
    usePairwiseComparison(selectedComparisonId);

  const filteredCases = useMemo(() => {
    if (!comparison) return [];

    const rows = comparison.case_results
      .filter((entry) => winnerFilter === 'all' || entry.winner === winnerFilter)
      .filter((entry) => severityFilter === 'all' || severityForDelta(entry.score_delta) === severityFilter)
      .sort((left, right) => sortCases(left, right, sortMode, metricFocus));

    return rows;
  }, [comparison, metricFocus, severityFilter, sortMode, winnerFilter]);

  const winnerOptions = useMemo(() => {
    if (!comparison) return [];
    return Array.from(
      new Set(
        [
          comparison.label_a,
          comparison.label_b,
          'tie',
          ...(comparison.summary.pending_human > 0 ? ['pending_human'] : []),
        ].filter(Boolean)
      )
    );
  }, [comparison]);

  const hasTwoDistinctConfigs = Boolean(configA) && Boolean(configB) && configA !== configB;

  function handleStartComparison() {
    if (!configA || !configB) {
      toastError('Choose both configs', 'Select a left and right config before starting a comparison.');
      return;
    }

    if (configA === configB) {
      toastError('Choose two versions', 'Select two different configs to run a meaningful comparison.');
      return;
    }

    startComparison.mutate(
      {
        config_a_path: `configs/${configA}`,
        config_b_path: `configs/${configB}`,
        dataset_path: datasetPath.trim() || undefined,
        label_a: configA.replace(/\.ya?ml$/i, ''),
        label_b: configB.replace(/\.ya?ml$/i, ''),
        judge_strategy: judgeStrategy,
      },
      {
        onSuccess: (payload) => {
          toastSuccess('Comparison ready', 'Pairwise comparison stored and ready for review.');
          setSelectedComparisonId(payload.comparison_id);
        },
        onError: (error) => {
          toastError('Comparison failed', error.message);
        },
      }
    );
  }

  if (isLoading) {
    return (
      <div className="space-y-4">
        <LoadingSkeleton rows={4} />
        <LoadingSkeleton rows={8} />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Compare"
        description="Run and inspect head-to-head evals with statistical confidence, drill-down, and side-by-side outputs."
      />

      <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
        <div className="grid gap-4 lg:grid-cols-[1.1fr,0.9fr]">
          <div>
            <div className="mb-4 flex items-center gap-2">
              <FlaskConical className="h-4 w-4 text-gray-500" />
              <h2 className="text-sm font-semibold text-gray-900">Start Pairwise Comparison</h2>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <label className="space-y-1 text-sm text-gray-700">
                <span>Config A</span>
                <select
                  value={configA}
                  onChange={(event) => setConfigA(event.target.value)}
                  className="w-full rounded-xl border border-gray-300 px-3 py-2 text-sm focus:border-gray-900 focus:outline-none"
                >
                  <option value="">Select config</option>
                  {(configs || []).map((entry) => (
                    <option key={entry.filename} value={entry.filename}>
                      {entry.filename}
                    </option>
                  ))}
                </select>
              </label>
              <label className="space-y-1 text-sm text-gray-700">
                <span>Config B</span>
                <select
                  value={configB}
                  onChange={(event) => setConfigB(event.target.value)}
                  className="w-full rounded-xl border border-gray-300 px-3 py-2 text-sm focus:border-gray-900 focus:outline-none"
                >
                  <option value="">Select config</option>
                  {(configs || []).map((entry) => (
                    <option key={entry.filename} value={entry.filename}>
                      {entry.filename}
                    </option>
                  ))}
                </select>
              </label>
              <label className="space-y-1 text-sm text-gray-700">
                <span>Dataset path</span>
                <input
                  value={datasetPath}
                  onChange={(event) => setDatasetPath(event.target.value)}
                  placeholder="dataset.jsonl"
                  className="w-full rounded-xl border border-gray-300 px-3 py-2 text-sm focus:border-gray-900 focus:outline-none"
                />
              </label>
              <label className="space-y-1 text-sm text-gray-700">
                <span>Judge strategy</span>
                <select
                  value={judgeStrategy}
                  onChange={(event) => setJudgeStrategy(event.target.value as typeof judgeStrategy)}
                  className="w-full rounded-xl border border-gray-300 px-3 py-2 text-sm focus:border-gray-900 focus:outline-none"
                >
                  <option value="metric_delta">Metric delta</option>
                  <option value="llm_judge">Pairwise judge</option>
                  <option value="human_preference">Human preference</option>
                </select>
              </label>
            </div>
            <button
              onClick={handleStartComparison}
              disabled={startComparison.isPending || !hasTwoDistinctConfigs}
              className="mt-4 inline-flex items-center gap-2 rounded-xl bg-gray-900 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-gray-800 disabled:opacity-60"
            >
              <ArrowLeftRight className="h-4 w-4" />
              {startComparison.isPending ? 'Running…' : 'Run comparison'}
            </button>
            {!hasTwoDistinctConfigs && (
              <p className="mt-2 text-sm text-amber-700">
                Choose two different configs to compare. Build or import another version if only one is available.
              </p>
            )}
          </div>

          <div className="rounded-2xl border border-gray-200 bg-gray-50 p-4">
            <div className="mb-3 flex items-center gap-2">
              <Trophy className="h-4 w-4 text-gray-500" />
              <h3 className="text-sm font-semibold text-gray-900">Recent Comparisons</h3>
            </div>
            {(comparisons?.comparisons || []).length === 0 ? (
              <p className="text-sm text-gray-500">No pairwise comparisons yet. Run your first head-to-head eval.</p>
            ) : (
              <div className="space-y-2">
                {comparisons?.comparisons.map((entry) => (
                  <button
                    key={entry.comparison_id}
                    onClick={() => setSelectedComparisonId(entry.comparison_id)}
                    className={`w-full rounded-xl border px-3 py-3 text-left transition ${
                      selectedComparisonId === entry.comparison_id
                        ? 'border-gray-900 bg-white shadow-sm'
                        : 'border-gray-200 bg-white/60 hover:border-gray-300 hover:bg-white'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <p className="font-medium text-gray-900">{entry.label_a} vs {entry.label_b}</p>
                      <span
                        className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
                          entry.is_significant
                            ? 'bg-emerald-100 text-emerald-700'
                            : 'bg-amber-100 text-amber-700'
                        }`}
                      >
                        {entry.is_significant ? 'Significant' : 'Needs more data'}
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-gray-500">
                      {entry.dataset_name} · {formatTimestamp(entry.created_at)}
                    </p>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </section>

      {isError && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Unable to load pairwise comparisons. Retry the compare API.
        </div>
      )}

      {isLoadingComparison && (
        <div className="space-y-4">
          <LoadingSkeleton rows={4} />
          <LoadingSkeleton rows={7} />
        </div>
      )}

      {isComparisonError && !isLoadingComparison && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Unable to load the selected comparison. Pick another run or retry.
        </div>
      )}

      {!comparison && !isLoadingComparison && !isComparisonError && (
        <EmptyState
          icon={ArrowLeftRight}
          title="No comparison selected"
          description="Choose a recent comparison or run a new one to inspect winners, ties, and per-case deltas."
        />
      )}

      {comparison && (
        <>
          <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-2">
                  <h2 className="text-lg font-semibold text-gray-900">
                    {comparison.label_a} vs {comparison.label_b}
                  </h2>
                  <span
                    className={`rounded-full px-2.5 py-1 text-xs font-medium ${
                      comparison.analysis.is_significant
                        ? 'bg-emerald-100 text-emerald-700'
                        : 'bg-amber-100 text-amber-700'
                    }`}
                  >
                    {comparison.analysis.is_significant ? 'Statistically significant' : 'Inconclusive'}
                  </span>
                </div>
                <p className="mt-2 text-sm text-gray-600">
                  {comparison.dataset_name} · Updated {formatTimestamp(comparison.created_at)}
                </p>
                <p className="mt-2 text-sm font-medium text-gray-900">
                  {(comparison.analysis.confidence * 100).toFixed(1)}% confidence
                </p>
                <p className="mt-1 max-w-3xl text-sm text-gray-600">
                  {comparison.analysis.summary_message}
                </p>
              </div>

              <button
                onClick={() => refetch()}
                className="rounded-xl border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                Refresh
              </button>
            </div>

            <div className="mt-5 grid gap-3 md:grid-cols-4">
              <SummaryCard
                icon={<Trophy className="h-4 w-4 text-gray-500" />}
                label={`${comparison.label_a} wins`}
                value={`${comparison.summary.left_wins} wins`}
                tone="neutral"
              />
              <SummaryCard
                icon={<Trophy className="h-4 w-4 text-emerald-600" />}
                label={`${comparison.label_b} wins`}
                value={`${comparison.summary.right_wins} wins`}
                tone="success"
              />
              <SummaryCard
                icon={<Filter className="h-4 w-4 text-amber-600" />}
                label="Ties"
                value={`${comparison.summary.ties} ties`}
                tone="warning"
              />
              <SummaryCard
                icon={<Sigma className="h-4 w-4 text-gray-500" />}
                label="p-value"
                value={comparison.analysis.p_value.toFixed(4)}
                tone="neutral"
              />
            </div>
          </section>

          <section className="rounded-2xl border border-gray-200 bg-white shadow-sm">
            <div className="flex flex-wrap items-end justify-between gap-3 border-b border-gray-200 bg-gray-50 px-4 py-4">
              <div>
                <h3 className="text-sm font-semibold text-gray-900">Per-case comparison</h3>
                <p className="mt-1 text-xs text-gray-500">
                  Filter by winner, severity, or metric focus to isolate the meaningful deltas.
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <label className="text-xs font-medium text-gray-600">
                  Winner filter
                  <select
                    aria-label="Winner filter"
                    value={winnerFilter}
                    onChange={(event) => setWinnerFilter(event.target.value)}
                    className="ml-2 rounded-lg border border-gray-300 px-2.5 py-1.5 text-sm"
                  >
                    <option value="all">All winners</option>
                    {winnerOptions.map((option) => (
                      <option key={option} value={option}>
                        {option}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="text-xs font-medium text-gray-600">
                  Severity
                  <select
                    value={severityFilter}
                    onChange={(event) => setSeverityFilter(event.target.value as SeverityFilter)}
                    className="ml-2 rounded-lg border border-gray-300 px-2.5 py-1.5 text-sm"
                  >
                    <option value="all">All severities</option>
                    <option value="high">High</option>
                    <option value="medium">Medium</option>
                    <option value="low">Low</option>
                  </select>
                </label>
                <label className="text-xs font-medium text-gray-600">
                  Sort
                  <select
                    value={sortMode}
                    onChange={(event) => setSortMode(event.target.value as SortMode)}
                    className="ml-2 rounded-lg border border-gray-300 px-2.5 py-1.5 text-sm"
                  >
                    <option value="delta">Largest delta</option>
                    <option value="quality">Quality gap</option>
                    <option value="latency">Latency gap</option>
                  </select>
                </label>
                <label className="text-xs font-medium text-gray-600">
                  Metric
                  <select
                    value={metricFocus}
                    onChange={(event) => setMetricFocus(event.target.value as MetricFocus)}
                    className="ml-2 rounded-lg border border-gray-300 px-2.5 py-1.5 text-sm"
                  >
                    <option value="composite">Composite</option>
                    <option value="quality">Quality</option>
                    <option value="latency">Latency</option>
                  </select>
                </label>
              </div>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-200 bg-white">
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Input</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Winner</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Severity</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Metric</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Delta</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Drill-down</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredCases.map((entry, index) => {
                    const isExpanded = expandedCaseId === entry.case_id;
                    return (
                      <CaseComparisonRow
                        key={entry.case_id}
                        entry={entry}
                        index={index}
                        metricFocus={metricFocus}
                        expanded={isExpanded}
                        onToggle={() => setExpandedCaseId(isExpanded ? null : entry.case_id)}
                        labelA={comparison.label_a}
                        labelB={comparison.label_b}
                      />
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>

          <section className="rounded-2xl border border-sky-100 bg-sky-50/60 p-5">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h3 className="text-sm font-semibold text-sky-900">Act on these results</h3>
                <p className="mt-1 text-sm text-sky-800">
                  {comparison.analysis.is_significant
                    ? 'The comparison is statistically significant. Optimize the weaker config or review pending improvements.'
                    : 'Results are inconclusive. Run more evals for stronger signal, or optimize to generate better candidates.'}
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Link
                  to="/optimize"
                  className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3.5 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
                >
                  Optimize
                  <ArrowRight className="h-4 w-4" />
                </Link>
                <Link
                  to="/improvements"
                  className="inline-flex items-center gap-2 rounded-lg bg-gray-900 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-gray-800"
                >
                  Review Improvements
                  <ArrowRight className="h-4 w-4" />
                </Link>
              </div>
            </div>
          </section>
        </>
      )}
    </div>
  );
}

function SummaryCard({
  icon,
  label,
  value,
  tone,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  tone: 'neutral' | 'success' | 'warning';
}) {
  const toneClass =
    tone === 'success'
      ? 'border-emerald-200 bg-emerald-50'
      : tone === 'warning'
        ? 'border-amber-200 bg-amber-50'
        : 'border-gray-200 bg-gray-50';

  return (
    <div className={`rounded-2xl border p-4 ${toneClass}`}>
      <div className="flex items-center gap-2 text-gray-500">{icon}<span className="text-xs font-medium">{label}</span></div>
      <p className="mt-2 text-lg font-semibold text-gray-900">{value}</p>
    </div>
  );
}

function CaseComparisonRow({
  entry,
  index,
  metricFocus,
  expanded,
  onToggle,
  labelA,
  labelB,
}: {
  entry: PairwiseCaseResult;
  index: number;
  metricFocus: MetricFocus;
  expanded: boolean;
  onToggle: () => void;
  labelA: string;
  labelB: string;
}) {
  const rowMetricValue = metricValue(entry, metricFocus);
  const rowClass = index % 2 === 0 ? 'bg-white' : 'bg-gray-50/60';

  return (
    <>
      <tr className={`border-b border-gray-100 ${rowClass}`}>
        <td className="px-4 py-3">
          <p className="font-medium text-gray-900">{entry.input_message}</p>
          <p className="mt-1 text-xs text-gray-500">{entry.category}</p>
        </td>
        <td className="px-4 py-3">
          <span className="rounded-full bg-gray-100 px-2.5 py-1 text-xs font-medium text-gray-700">
            {entry.winner}
          </span>
        </td>
        <td className="px-4 py-3 text-gray-700">{severityForDelta(entry.score_delta)}</td>
        <td className="px-4 py-3 text-gray-700">{rowMetricValue}</td>
        <td className="px-4 py-3 font-medium text-gray-900">{entry.score_delta.toFixed(3)}</td>
        <td className="px-4 py-3">
          <button
            onClick={onToggle}
            className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
            aria-label={`View ${entry.case_id}`}
          >
            {expanded ? 'Hide details' : 'View details'}
          </button>
        </td>
      </tr>
      {expanded && (
        <tr className="border-b border-gray-100 bg-gray-50/70">
          <td colSpan={6} className="px-4 py-4">
            <div className="grid gap-4 lg:grid-cols-2">
              <VariantPanel label={labelA} variant={entry.left} />
              <VariantPanel label={labelB} variant={entry.right} />
            </div>
            <div className="mt-4 rounded-xl border border-gray-200 bg-white px-4 py-3 text-sm text-gray-700">
              <p className="font-medium text-gray-900">Why this outcome</p>
              <p className="mt-1">{entry.winner_reason}</p>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function VariantPanel({
  label,
  variant,
}: {
  label: string;
  variant: PairwiseCaseResult['left'];
}) {
  return (
    <div className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <h4 className="text-sm font-semibold text-gray-900">{label}</h4>
        <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-600">
          composite {variant.composite_score.toFixed(3)}
        </span>
      </div>
      <div className="mt-3 grid grid-cols-3 gap-2 text-xs text-gray-500">
        <div>
          <p>Quality</p>
          <p className="mt-1 font-semibold text-gray-900">{variant.quality_score.toFixed(2)}</p>
        </div>
        <div>
          <p>Latency</p>
          <p className="mt-1 font-semibold text-gray-900">{variant.latency_ms.toFixed(0)}ms</p>
        </div>
        <div>
          <p>Safety</p>
          <p className="mt-1 font-semibold text-gray-900">{variant.safety_passed ? 'pass' : 'fail'}</p>
        </div>
      </div>
      <p className="mt-4 rounded-xl border border-gray-200 bg-gray-50 px-3 py-3 text-sm text-gray-700">
        {variant.response}
      </p>
      {variant.details && (
        <p className="mt-3 text-xs text-gray-500">Notes: {variant.details}</p>
      )}
    </div>
  );
}

function metricValue(entry: PairwiseCaseResult, metricFocus: MetricFocus): string {
  if (metricFocus === 'quality') {
    return `${entry.left.quality_score.toFixed(2)} -> ${entry.right.quality_score.toFixed(2)}`;
  }
  if (metricFocus === 'latency') {
    return `${entry.left.latency_ms.toFixed(0)}ms -> ${entry.right.latency_ms.toFixed(0)}ms`;
  }
  return `${entry.left.composite_score.toFixed(3)} -> ${entry.right.composite_score.toFixed(3)}`;
}

function severityForDelta(scoreDelta: number): SeverityFilter {
  const magnitude = Math.abs(scoreDelta);
  if (magnitude >= 0.2) return 'high';
  if (magnitude >= 0.08) return 'medium';
  return 'low';
}

function sortCases(
  left: PairwiseCaseResult,
  right: PairwiseCaseResult,
  sortMode: SortMode,
  metricFocus: MetricFocus
) {
  if (sortMode === 'quality') {
    const leftGap = Math.abs(left.left.quality_score - left.right.quality_score);
    const rightGap = Math.abs(right.left.quality_score - right.right.quality_score);
    return rightGap - leftGap;
  }
  if (sortMode === 'latency') {
    const leftGap = Math.abs(left.left.latency_ms - left.right.latency_ms);
    const rightGap = Math.abs(right.left.latency_ms - right.right.latency_ms);
    return rightGap - leftGap;
  }

  const leftDelta = Math.abs(metricFocus === 'quality'
    ? left.left.quality_score - left.right.quality_score
    : metricFocus === 'latency'
      ? left.left.latency_ms - left.right.latency_ms
      : left.score_delta);
  const rightDelta = Math.abs(metricFocus === 'quality'
    ? right.left.quality_score - right.right.quality_score
    : metricFocus === 'latency'
      ? right.left.latency_ms - right.right.latency_ms
      : right.score_delta);
  return rightDelta - leftDelta;
}
