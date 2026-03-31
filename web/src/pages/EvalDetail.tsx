import { useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import { AlertTriangle } from 'lucide-react';
import { useEvalDetail } from '../lib/api';
import { ScoreBar } from '../components/ScoreBar';
import { StatusBadge } from '../components/StatusBadge';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { ScoreDisplay } from '../components/ScoreDisplay';
import { DimensionBreakdown } from '../components/DimensionBreakdown';
import { formatLatency, formatTimestamp, statusVariant } from '../lib/utils';
import type { EvalCase } from '../lib/types';

export function EvalDetail() {
  const { id } = useParams<{ id: string }>();
  const { data: result, isLoading, isError, refetch } = useEvalDetail(id);
  const [categoryFilter, setCategoryFilter] = useState('all');
  const [outcomeFilter, setOutcomeFilter] = useState<'all' | 'pass' | 'fail'>('all');
  const [sortBy, setSortBy] = useState<'quality' | 'latency' | 'case_id'>('quality');
  const [expandedCase, setExpandedCase] = useState<string | null>(null);

  const categories = useMemo(() => {
    if (!result) return [];
    return Array.from(new Set(result.cases.map((entry) => entry.category))).sort();
  }, [result]);

  const filteredCases = useMemo(() => {
    if (!result) return [];

    let rows = [...result.cases];
    if (categoryFilter !== 'all') {
      rows = rows.filter((entry) => entry.category === categoryFilter);
    }
    if (outcomeFilter === 'pass') {
      rows = rows.filter((entry) => entry.passed);
    }
    if (outcomeFilter === 'fail') {
      rows = rows.filter((entry) => !entry.passed);
    }

    rows.sort((a, b) => {
      if (sortBy === 'quality') return b.quality_score - a.quality_score;
      if (sortBy === 'latency') return a.latency_ms - b.latency_ms;
      return a.case_id.localeCompare(b.case_id);
    });

    return rows;
  }, [result, categoryFilter, outcomeFilter, sortBy]);

  if (isLoading) {
    return (
      <div className="space-y-4">
        <LoadingSkeleton rows={4} />
        <LoadingSkeleton rows={8} />
      </div>
    );
  }

  if (isError || !result) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-5">
        <p className="text-sm font-semibold text-red-800">Unable to load eval details.</p>
        <button
          onClick={() => refetch()}
          className="mt-3 rounded-lg border border-red-300 bg-white px-3 py-1.5 text-sm text-red-700 hover:bg-red-100"
        >
          Retry
        </button>
      </div>
    );
  }

  const score = result.composite_score;

  return (
    <div className="space-y-6">
      {result.status !== 'completed' && (
        <div className="rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-800">
          Eval run is currently <strong>{result.status}</strong>. Progress: {result.progress}%.
        </div>
      )}

      <section className="rounded-lg border border-gray-200 bg-white p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="font-mono text-sm text-gray-700">Run {result.run_id.slice(0, 12)}</h2>
              <StatusBadge variant={statusVariant(result.status)} label={result.status} />
              {result.mode && <StatusBadge variant={statusVariant(result.mode)} label={result.mode} />}
            </div>
            <p className="mt-2 text-sm text-gray-600">
              Completed {formatTimestamp(result.timestamp)} · {result.passed_cases}/{result.total_cases} passed
            </p>
            {result.safety_failures > 0 && (
              <p className="mt-2 inline-flex items-center gap-1 rounded-md bg-red-50 px-2 py-1 text-xs text-red-700">
                <AlertTriangle className="h-3.5 w-3.5" />
                {result.safety_failures} safety failures detected
              </p>
            )}
          </div>

          <div className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3 text-right">
            <p className="text-xs text-gray-500">Composite score</p>
            <ScoreDisplay score={score.overall} size="lg" />
          </div>
        </div>
      </section>

      <section className="rounded-lg border border-gray-200 bg-white p-5">
        <h3 className="mb-4 text-sm font-semibold text-gray-900">Score Breakdown</h3>
        <div className="grid gap-3 sm:grid-cols-2">
          <ScoreBar label="Quality" score={score.quality} />
          <ScoreBar label="Safety" score={score.safety} />
          <ScoreBar label="Latency" score={score.latency} />
          <ScoreBar label="Cost" score={score.cost} />
        </div>
      </section>

      {score.dimensions && (
        <section className="rounded-lg border border-gray-200 bg-white p-5">
          <details>
            <summary className="cursor-pointer text-sm font-semibold text-gray-900">
              9-Dimension Breakdown
            </summary>
            <div className="mt-4">
              <DimensionBreakdown dimensions={score.dimensions} />
            </div>
          </details>
        </section>
      )}

      <section className="overflow-hidden rounded-lg border border-gray-200 bg-white">
        <div className="flex flex-wrap items-end justify-between gap-3 border-b border-gray-200 bg-gray-50 px-4 py-3">
          <h3 className="text-sm font-semibold text-gray-900">Per-Case Results</h3>
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={categoryFilter}
              onChange={(event) => setCategoryFilter(event.target.value)}
              className="rounded-lg border border-gray-300 px-2.5 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
            >
              <option value="all">All categories</option>
              {categories.map((category) => (
                <option key={category} value={category}>
                  {category}
                </option>
              ))}
            </select>

            <select
              value={outcomeFilter}
              onChange={(event) => setOutcomeFilter(event.target.value as 'all' | 'pass' | 'fail')}
              className="rounded-lg border border-gray-300 px-2.5 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
            >
              <option value="all">All outcomes</option>
              <option value="pass">Passed only</option>
              <option value="fail">Failed only</option>
            </select>

            <select
              value={sortBy}
              onChange={(event) => setSortBy(event.target.value as 'quality' | 'latency' | 'case_id')}
              className="rounded-lg border border-gray-300 px-2.5 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
            >
              <option value="quality">Sort by quality</option>
              <option value="latency">Sort by latency</option>
              <option value="case_id">Sort by case ID</option>
            </select>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 bg-white">
                <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Case</th>
                <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Category</th>
                <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Status</th>
                <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Quality</th>
                <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Latency</th>
                <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Tokens</th>
                <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Details</th>
              </tr>
            </thead>
            <tbody>
              {filteredCases.map((entry, index) => (
                <CaseRow
                  key={entry.case_id}
                  caseData={entry}
                  isEven={index % 2 === 1}
                  expanded={expandedCase === entry.case_id}
                  onToggle={() =>
                    setExpandedCase((current) => (current === entry.case_id ? null : entry.case_id))
                  }
                />
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function CaseRow({
  caseData,
  isEven,
  expanded,
  onToggle,
}: {
  caseData: EvalCase;
  isEven: boolean;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <>
      <tr
        onClick={onToggle}
        className={`cursor-pointer border-b border-gray-100 transition hover:bg-blue-50/60 ${
          isEven ? 'bg-gray-50/60' : ''
        }`}
      >
        <td className="px-4 py-2 font-mono text-xs text-gray-700">{caseData.case_id}</td>
        <td className="px-4 py-2 text-gray-600">{caseData.category}</td>
        <td className="px-4 py-2">
          <StatusBadge variant={caseData.passed ? 'success' : 'error'} label={caseData.passed ? 'passed' : 'failed'} />
        </td>
        <td className="px-4 py-2 font-medium text-gray-900">{caseData.quality_score.toFixed(1)}</td>
        <td className="px-4 py-2 text-gray-600">{formatLatency(caseData.latency_ms)}</td>
        <td className="px-4 py-2 text-gray-600">{caseData.token_count}</td>
        <td className="max-w-sm px-4 py-2 text-gray-600">{caseData.details || 'No notes'}</td>
      </tr>

      {expanded && (
        <tr className="bg-blue-50/40">
          <td colSpan={7} className="px-4 py-4">
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="rounded-lg border border-blue-100 bg-white p-3">
                <p className="text-xs text-gray-500">Quality score</p>
                <p className="mt-1 text-lg font-semibold text-gray-900">{caseData.quality_score.toFixed(1)}</p>
              </div>
              <div className="rounded-lg border border-blue-100 bg-white p-3">
                <p className="text-xs text-gray-500">Latency</p>
                <p className="mt-1 text-lg font-semibold text-gray-900">{formatLatency(caseData.latency_ms)}</p>
              </div>
              <div className="rounded-lg border border-blue-100 bg-white p-3">
                <p className="text-xs text-gray-500">Safety</p>
                <p className="mt-1 text-lg font-semibold text-gray-900">{caseData.safety_passed ? 'Passed' : 'Failed'}</p>
              </div>
            </div>
            {caseData.details && (
              <p className="mt-3 rounded-lg border border-blue-100 bg-white p-3 text-sm text-gray-700">
                {caseData.details}
              </p>
            )}
          </td>
        </tr>
      )}
    </>
  );
}
