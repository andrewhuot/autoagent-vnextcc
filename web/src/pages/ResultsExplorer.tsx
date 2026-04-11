import { useEffect, useMemo, useState } from 'react';
import { ArrowLeft, ArrowRight, BarChart3, Download, Flag, ListFilter, Search, Sparkles } from 'lucide-react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  useAddResultAnnotation,
  useExportEvalResults,
  useResultRuns,
  useResultsDiff,
  useResultsRun,
} from '../lib/api';
import { AnnotationPanel } from '../components/AnnotationPanel';
import { EmptyState } from '../components/EmptyState';
import { ExampleDetail } from '../components/ExampleDetail';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { PageHeader } from '../components/PageHeader';
import { RunDiff } from '../components/RunDiff';
import { ScoreDistribution } from '../components/ScoreDistribution';
import { toastError, toastSuccess } from '../lib/toast';
import { formatTimestamp } from '../lib/utils';
import type { EvalResultExample } from '../lib/types';

type OutcomeFilter = 'all' | 'pass' | 'fail';
type MetricFilter = 'all' | 'quality' | 'composite' | 'safety' | 'latency' | 'token_count';
type SortMode = 'severity' | 'quality' | 'annotations' | 'category';

export function ResultsExplorer() {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const { data: runsData, isLoading: isLoadingRuns, isError: isRunsError } = useResultRuns();
  const selectedRunId = runId || runsData?.runs?.[0]?.run_id;
  const { data: resultRun, isLoading: isLoadingRun, isError: isRunError, refetch } = useResultsRun(selectedRunId);
  const annotateResult = useAddResultAnnotation();
  const exportResult = useExportEvalResults();

  const [compareRunId, setCompareRunId] = useState('');
  const [outcomeFilter, setOutcomeFilter] = useState<OutcomeFilter>('all');
  const [metricFilter, setMetricFilter] = useState<MetricFilter>('all');
  const [sortMode, setSortMode] = useState<SortMode>('severity');
  const [searchQuery, setSearchQuery] = useState('');
  const [belowThreshold, setBelowThreshold] = useState('');
  const [selectedExampleId, setSelectedExampleId] = useState<string | null>(null);

  const { data: diff, isLoading: isDiffLoading } = useResultsDiff(
    compareRunId || undefined,
    selectedRunId
  );

  useEffect(() => {
    if (!runId && runsData?.runs?.[0]?.run_id) {
      navigate(`/results/${runsData.runs[0].run_id}`, { replace: true });
    }
  }, [navigate, runId, runsData]);

  const filteredExamples = useMemo(() => {
    if (!resultRun) return [];

    const normalizedQuery = searchQuery.trim().toLowerCase();
    const threshold = belowThreshold.trim() === '' ? null : Number(belowThreshold);

    const rows = resultRun.examples.filter((example) => {
      if (outcomeFilter === 'pass' && !example.passed) return false;
      if (outcomeFilter === 'fail' && example.passed) return false;

      if (metricFilter !== 'all' && threshold !== null && Number.isFinite(threshold)) {
        const metricScore = example.scores[metricFilter];
        if (!metricScore || metricScore.value >= threshold) {
          return false;
        }
      }

      if (!normalizedQuery) return true;
      return exampleSearchText(example).includes(normalizedQuery);
    });

    rows.sort((left, right) => {
      if (sortMode === 'quality') {
        return (right.scores.quality?.value || 0) - (left.scores.quality?.value || 0);
      }
      if (sortMode === 'annotations') {
        return right.annotations.length - left.annotations.length;
      }
      if (sortMode === 'category') {
        return left.category.localeCompare(right.category);
      }
      return severityScore(right) - severityScore(left);
    });

    return rows;
  }, [belowThreshold, metricFilter, outcomeFilter, resultRun, searchQuery, sortMode]);

  useEffect(() => {
    if (!filteredExamples.length) {
      setSelectedExampleId(null);
      return;
    }
    const stillVisible = filteredExamples.some((example) => example.example_id === selectedExampleId);
    if (!stillVisible) {
      setSelectedExampleId(filteredExamples[0].example_id);
    }
  }, [filteredExamples, selectedExampleId]);

  const selectedExample = useMemo(() => {
    if (!resultRun || !selectedExampleId) return null;
    return resultRun.examples.find((example) => example.example_id === selectedExampleId) ?? null;
  }, [resultRun, selectedExampleId]);

  const failurePatterns = useMemo(() => {
    if (!resultRun) return [];
    const counts = new Map<string, number>();
    resultRun.examples.forEach((example) => {
      example.failure_reasons.forEach((reason) => {
        counts.set(reason, (counts.get(reason) || 0) + 1);
      });
    });
    return Array.from(counts.entries())
      .sort((left, right) => right[1] - left[1])
      .slice(0, 6);
  }, [resultRun]);

  const recentTrend = useMemo(() => {
    return (runsData?.runs || []).slice(0, 6);
  }, [runsData]);

  const passRate = useMemo(() => {
    if (!resultRun || resultRun.summary.total === 0) return 0;
    return (resultRun.summary.passed / resultRun.summary.total) * 100;
  }, [resultRun]);

  function handleRunChange(nextRunId: string) {
    navigate(`/results/${nextRunId}`);
  }

  function handleAnnotationSave(payload: {
    author: string;
    type: string;
    content: string;
    score_override: number | null;
  }) {
    if (!selectedRunId || !selectedExample) return;

    annotateResult.mutate(
      {
        runId: selectedRunId,
        exampleId: selectedExample.example_id,
        ...payload,
      },
      {
        onSuccess: () => {
          toastSuccess('Annotation saved', 'The example note is now part of this run review.');
          refetch();
        },
        onError: (error) => {
          toastError('Annotation failed', error.message);
        },
      }
    );
  }

  function handleExport(format: 'json' | 'csv' | 'markdown') {
    if (!selectedRunId) return;

    exportResult.mutate(
      { runId: selectedRunId, format },
      {
        onSuccess: (payload) => {
          downloadExport(`eval-results-${selectedRunId}.${extensionForFormat(format)}`, payload, mimeForFormat(format));
          toastSuccess('Export ready', `${format.toUpperCase()} export downloaded for ${selectedRunId}.`);
        },
        onError: (error) => {
          toastError('Export failed', error.message);
        },
      }
    );
  }

  if (isLoadingRuns || (selectedRunId && isLoadingRun)) {
    return (
      <div className="space-y-4">
        <LoadingSkeleton rows={4} />
        <LoadingSkeleton rows={8} />
      </div>
    );
  }

  if (!runsData?.runs?.length) {
    return (
      <EmptyState
        icon={BarChart3}
        title="No eval results yet"
        description="Run an evaluation first, then come back here to inspect examples, failure clusters, and run-to-run changes."
        actionLabel="Go to Eval Runs"
        onAction={() => navigate('/evals')}
      />
    );
  }

  if (isRunsError || isRunError || !resultRun) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
        Unable to load results explorer data. Retry the API or refresh the page.
      </div>
    );
  }

  const qualitySummary = resultRun.summary.metrics.quality;
  const compositeSummary = resultRun.summary.metrics.composite;
  const safetySummary = resultRun.summary.metrics.safety;

  return (
    <div className="space-y-6">
      <Link
        to="/evals"
        className="inline-flex items-center gap-1.5 text-sm font-medium text-gray-600 transition hover:text-gray-900"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to Eval Runs
      </Link>

      <PageHeader
        title="Results Explorer"
        description="Filter failures, inspect grader reasoning, annotate edge cases, and compare one run against another."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => handleExport('json')}
              className="inline-flex items-center gap-2 rounded-xl border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
            >
              <Download className="h-4 w-4" />
              JSON
            </button>
            <button
              onClick={() => handleExport('csv')}
              className="inline-flex items-center gap-2 rounded-xl border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
            >
              <Download className="h-4 w-4" />
              CSV
            </button>
            <button
              onClick={() => handleExport('markdown')}
              className="inline-flex items-center gap-2 rounded-xl bg-gray-900 px-3 py-2 text-sm font-medium text-white transition hover:bg-gray-800"
            >
              <Download className="h-4 w-4" />
              Markdown
            </button>
          </div>
        }
      />

      <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
        <div className="grid gap-4 lg:grid-cols-[1.1fr,0.9fr]">
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <SummaryCard label="Run" value={resultRun.run_id} hint={formatTimestamp(resultRun.timestamp)} />
            <SummaryCard label="Pass rate" value={`${passRate.toFixed(1)}%`} hint={`${resultRun.summary.passed}/${resultRun.summary.total} passed`} />
            <SummaryCard label="Mode" value={resultRun.mode} hint={stringValue(resultRun.config_snapshot['variant']) || 'current config'} />
            <SummaryCard label="Composite mean" value={compositeSummary ? compositeSummary.mean.toFixed(3) : 'n/a'} hint="run average" />
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <label className="space-y-1 text-sm text-gray-700">
              <span>Run</span>
              <select
                aria-label="Run"
                value={selectedRunId}
                onChange={(event) => handleRunChange(event.target.value)}
                className="w-full rounded-xl border border-gray-300 px-3 py-2 text-sm focus:border-gray-900 focus:outline-none"
              >
                {runsData.runs.map((run) => (
                  <option key={run.run_id} value={run.run_id}>
                    {run.run_id}
                  </option>
                ))}
              </select>
            </label>

            <label className="space-y-1 text-sm text-gray-700">
              <span>Compare to</span>
              <select
                aria-label="Compare to"
                value={compareRunId}
                onChange={(event) => setCompareRunId(event.target.value)}
                className="w-full rounded-xl border border-gray-300 px-3 py-2 text-sm focus:border-gray-900 focus:outline-none"
              >
                <option value="">No comparison</option>
                {runsData.runs
                  .filter((run) => run.run_id !== selectedRunId)
                  .map((run) => (
                    <option key={run.run_id} value={run.run_id}>
                      {run.run_id}
                    </option>
                  ))}
              </select>
            </label>

            <label className="space-y-1 text-sm text-gray-700">
              <span>Outcome filter</span>
              <select
                aria-label="Outcome filter"
                value={outcomeFilter}
                onChange={(event) => setOutcomeFilter(event.target.value as OutcomeFilter)}
                className="w-full rounded-xl border border-gray-300 px-3 py-2 text-sm focus:border-gray-900 focus:outline-none"
              >
                <option value="all">All outcomes</option>
                <option value="pass">Passed only</option>
                <option value="fail">Failed only</option>
              </select>
            </label>

            <label className="space-y-1 text-sm text-gray-700">
              <span>Metric filter</span>
              <select
                aria-label="Metric filter"
                value={metricFilter}
                onChange={(event) => setMetricFilter(event.target.value as MetricFilter)}
                className="w-full rounded-xl border border-gray-300 px-3 py-2 text-sm focus:border-gray-900 focus:outline-none"
              >
                <option value="all">No metric filter</option>
                <option value="quality">Quality</option>
                <option value="composite">Composite</option>
                <option value="safety">Safety</option>
                <option value="latency">Latency</option>
                <option value="token_count">Token count</option>
              </select>
            </label>
          </div>
        </div>
      </section>

      <section className="grid gap-4 xl:grid-cols-[1.3fr,0.7fr]">
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {qualitySummary && <ScoreDistribution title="Quality distribution" summary={qualitySummary} />}
          {compositeSummary && <ScoreDistribution title="Composite distribution" summary={compositeSummary} />}
          {safetySummary && <ScoreDistribution title="Safety distribution" summary={safetySummary} />}
        </div>

        <section className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-gray-500" />
            <h3 className="text-sm font-semibold text-gray-900">Recent Trend</h3>
          </div>
          <div className="mt-4 space-y-3">
            {recentTrend.map((run) => {
              const runPassRate = run.summary.total > 0 ? (run.summary.passed / run.summary.total) * 100 : 0;
              const compositeMean = run.summary.metrics.composite?.mean || 0;
              return (
                <div key={run.run_id} className="space-y-1">
                  <div className="flex items-center justify-between gap-3 text-xs text-gray-500">
                    <span className="font-mono text-gray-700">{run.run_id}</span>
                    <span>{formatTimestamp(run.timestamp)}</span>
                  </div>
                  <div className="grid gap-2">
                    <div>
                      <div className="mb-1 flex items-center justify-between text-[11px] text-gray-500">
                        <span>Pass rate</span>
                        <span>{runPassRate.toFixed(0)}%</span>
                      </div>
                      <div className="h-2 overflow-hidden rounded-full bg-gray-100">
                        <div className="h-full rounded-full bg-gray-900" style={{ width: `${Math.min(runPassRate, 100)}%` }} />
                      </div>
                    </div>
                    <div>
                      <div className="mb-1 flex items-center justify-between text-[11px] text-gray-500">
                        <span>Composite mean</span>
                        <span>{compositeMean.toFixed(3)}</span>
                      </div>
                      <div className="h-2 overflow-hidden rounded-full bg-gray-100">
                        <div className="h-full rounded-full bg-amber-500" style={{ width: `${Math.min(compositeMean * 100, 100)}%` }} />
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      </section>

      <section className="grid gap-4 xl:grid-cols-[0.8fr,1.2fr]">
        <section className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
          <div className="flex items-center gap-2">
            <Flag className="h-4 w-4 text-gray-500" />
            <h3 className="text-sm font-semibold text-gray-900">Failure Patterns</h3>
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            {failurePatterns.length === 0 ? (
              <p className="text-sm text-gray-500">No failure patterns. This run is clean.</p>
            ) : (
              failurePatterns.map(([reason, count]) => (
                <span
                  key={reason}
                  className="rounded-full bg-amber-100 px-2.5 py-1 text-[11px] font-medium text-amber-700"
                >
                  {reason} · {count}
                </span>
              ))
            )}
          </div>
        </section>

        <RunDiff diff={compareRunId ? diff : undefined} isLoading={Boolean(compareRunId) && isDiffLoading} />
      </section>

      <section className="rounded-2xl border border-sky-100 bg-sky-50/60 p-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h3 className="text-sm font-semibold text-sky-900">Next steps</h3>
            <p className="mt-1 text-sm text-sky-800">
              Use these results to compare configs head-to-head or run an optimization cycle to address failures.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Link
              to="/compare"
              className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3.5 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
            >
              Compare Configs
              <ArrowRight className="h-4 w-4" />
            </Link>
            <Link
              to={`/optimize${selectedRunId ? `?evalRunId=${selectedRunId}` : ''}`}
              className="inline-flex items-center gap-2 rounded-lg bg-gray-900 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-gray-800"
            >
              Optimize Agent
              <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
        </div>
      </section>

      <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
        <div className="mb-4 flex flex-wrap items-end gap-3">
          <label className="min-w-[240px] flex-1 space-y-1 text-sm text-gray-700">
            <span>Search</span>
            <div className="flex items-center gap-2 rounded-xl border border-gray-300 px-3 py-2">
              <Search className="h-4 w-4 text-gray-400" />
              <input
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder="Search example id, prompt, response, or failure reason"
                className="w-full bg-transparent text-sm focus:outline-none"
              />
            </div>
          </label>

          <label className="space-y-1 text-sm text-gray-700">
            <span>Sort</span>
            <select
              value={sortMode}
              onChange={(event) => setSortMode(event.target.value as SortMode)}
              className="rounded-xl border border-gray-300 px-3 py-2 text-sm focus:border-gray-900 focus:outline-none"
            >
              <option value="severity">Severity</option>
              <option value="quality">Quality</option>
              <option value="annotations">Annotations</option>
              <option value="category">Category</option>
            </select>
          </label>

          <label className="space-y-1 text-sm text-gray-700">
            <span>Below threshold</span>
            <input
              value={belowThreshold}
              onChange={(event) => setBelowThreshold(event.target.value)}
              placeholder={metricFilter === 'all' ? 'Choose metric first' : 'e.g. 0.8'}
              className="rounded-xl border border-gray-300 px-3 py-2 text-sm focus:border-gray-900 focus:outline-none"
            />
          </label>
        </div>

        <div className="grid gap-4 xl:grid-cols-[0.95fr,1.05fr]">
          <div className="space-y-3">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <ListFilter className="h-4 w-4 text-gray-500" />
                <h3 className="text-sm font-semibold text-gray-900">Examples</h3>
              </div>
              <span className="rounded-full bg-gray-100 px-2.5 py-1 text-[11px] font-medium text-gray-700">
                {filteredExamples.length} visible
              </span>
            </div>

            {filteredExamples.length === 0 ? (
              <div className="rounded-xl border border-dashed border-gray-200 bg-gray-50 p-4 text-sm text-gray-500">
                No examples match the current filters.
              </div>
            ) : (
              filteredExamples.map((example) => (
                <button
                  key={example.example_id}
                  type="button"
                  aria-label={`Inspect ${example.example_id}`}
                  onClick={() => setSelectedExampleId(example.example_id)}
                  className={`w-full rounded-2xl border px-4 py-3 text-left transition ${
                    selectedExampleId === example.example_id
                      ? 'border-gray-900 bg-white shadow-sm'
                      : 'border-gray-200 bg-gray-50 hover:border-gray-300 hover:bg-white'
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="font-mono text-xs text-gray-700">{example.example_id}</p>
                      <p className="mt-1 text-sm font-medium text-gray-900">{inputPreview(example)}</p>
                    </div>
                    <span
                      className={`rounded-full px-2 py-1 text-[11px] font-medium ${
                        example.passed ? 'bg-emerald-100 text-emerald-700' : 'bg-red-100 text-red-700'
                      }`}
                    >
                      {example.passed ? 'Pass' : 'Fail'}
                    </span>
                  </div>

                  <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-gray-500">
                    <span className="rounded-full bg-white px-2 py-0.5">{example.category}</span>
                    <span className="rounded-full bg-white px-2 py-0.5">
                      quality {(example.scores.quality?.value || 0).toFixed(3)}
                    </span>
                    <span className="rounded-full bg-white px-2 py-0.5">
                      composite {(example.scores.composite?.value || 0).toFixed(3)}
                    </span>
                    <span className="rounded-full bg-white px-2 py-0.5">
                      annotations {example.annotations.length}
                    </span>
                  </div>

                  {example.failure_reasons.length > 0 && (
                    <p className="mt-3 text-xs text-amber-700">{example.failure_reasons.join(', ')}</p>
                  )}
                </button>
              ))
            )}
          </div>

          <div className="space-y-4">
            <ExampleDetail example={selectedExample} />
            <AnnotationPanel
              example={selectedExample}
              isPending={annotateResult.isPending}
              onSubmit={handleAnnotationSave}
            />
          </div>
        </div>
      </section>
    </div>
  );
}

function SummaryCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint: string;
}) {
  return (
    <div className="rounded-2xl border border-gray-200 bg-gray-50 px-4 py-4">
      <p className="text-xs uppercase tracking-wide text-gray-500">{label}</p>
      <p className="mt-1 break-all text-lg font-semibold text-gray-900">{value}</p>
      <p className="mt-1 text-xs text-gray-500">{hint}</p>
    </div>
  );
}

function exampleSearchText(example: EvalResultExample): string {
  return [
    example.example_id,
    example.category,
    inputPreview(example),
    stringValue(example.actual['response']),
    example.failure_reasons.join(' '),
  ]
    .join(' ')
    .toLowerCase();
}

function inputPreview(example: EvalResultExample): string {
  return stringValue(example.input['user_message']) || stringValue(example.input['prompt']) || example.example_id;
}

function severityScore(example: EvalResultExample): number {
  const qualityPenalty = 1 - (example.scores.quality?.value || 0);
  const annotationWeight = example.annotations.length * 0.05;
  const failureWeight = example.failure_reasons.length * 0.2;
  const passPenalty = example.passed ? 0 : 1;
  return passPenalty + qualityPenalty + annotationWeight + failureWeight;
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function extensionForFormat(format: 'json' | 'csv' | 'markdown') {
  if (format === 'markdown') return 'md';
  return format;
}

function mimeForFormat(format: 'json' | 'csv' | 'markdown') {
  if (format === 'json') return 'application/json';
  if (format === 'csv') return 'text/csv';
  return 'text/markdown';
}

function downloadExport(filename: string, content: string, mimeType: string) {
  const blob = new Blob([content], { type: mimeType });
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  window.URL.revokeObjectURL(url);
}
