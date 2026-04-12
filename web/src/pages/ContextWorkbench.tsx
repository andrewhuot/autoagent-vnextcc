import { useState } from 'react';
import { Gauge, Layers, NotebookPen } from 'lucide-react';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { PageHeader } from '../components/PageHeader';
import { StatusBadge } from '../components/StatusBadge';
import { useContextAnalysis, useContextReport, useRunContextSimulation } from '../lib/api';
import { toastError, toastSuccess } from '../lib/toast';
import type { ContextSimulationResult } from '../lib/types';
import { formatTimestamp, statusVariant } from '../lib/utils';

function pct(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

export function ContextWorkbench() {
  const [traceIdInput, setTraceIdInput] = useState('');
  const [activeTraceId, setActiveTraceId] = useState<string | undefined>(undefined);
  const [strategy, setStrategy] = useState<'truncate_tail' | 'sliding_window' | 'summarize'>('summarize');
  const [tokenBudget, setTokenBudget] = useState(8000);
  const [ttlSeconds, setTtlSeconds] = useState(3600);
  const [pinKeywordsInput, setPinKeywordsInput] = useState('');
  const [simulation, setSimulation] = useState<ContextSimulationResult | null>(null);

  const reportQuery = useContextReport(1000, tokenBudget);
  const analysisQuery = useContextAnalysis(activeTraceId, tokenBudget);
  const simulationMutation = useRunContextSimulation();

  function onAnalyze() {
    const traceId = traceIdInput.trim();
    if (!traceId) {
      toastError('Trace ID required', 'Provide a trace ID to run context analysis.');
      return;
    }
    setActiveTraceId(traceId);
  }

  function onSimulate() {
    const traceId = (activeTraceId || traceIdInput).trim();
    if (!traceId) {
      toastError('Trace ID required', 'Provide a trace ID before running simulation.');
      return;
    }

    const keywords = pinKeywordsInput
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean);

    simulationMutation.mutate(
      {
        trace_id: traceId,
        strategy,
        token_budget: tokenBudget,
        ttl_seconds: ttlSeconds,
        pin_keywords: keywords,
      },
      {
        onSuccess: (result) => {
          setSimulation(result);
          toastSuccess('Simulation complete', `Strategy ${result.strategy} finished for ${traceId}.`);
        },
        onError: (error) => {
          toastError('Simulation failed', error.message);
        },
      }
    );
  }

  if (reportQuery.isLoading) {
    return (
      <div className="space-y-4">
        <LoadingSkeleton rows={5} />
        <LoadingSkeleton rows={8} />
      </div>
    );
  }

  const report = reportQuery.data || {
    traces_analyzed: 0,
    total_events: 0,
    average_utilization: 0,
    growth_pattern_counts: {},
    context_correlated_failure_traces: [],
    average_handoff_fidelity: 0,
    average_memory_staleness: 0,
  };
  const analysis = analysisQuery.data;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Context Engineering Studio"
        description="Analyze context growth, simulate compaction strategies, and measure handoff fidelity and memory staleness."
      />

      <section className="grid gap-4 sm:grid-cols-3">
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <p className="text-xs text-gray-500">Traces Analyzed</p>
          <p className="mt-1 text-2xl font-semibold text-gray-900">{report.traces_analyzed}</p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <p className="text-xs text-gray-500">Average Utilization</p>
          <p className="mt-1 text-2xl font-semibold text-gray-900">{pct(report.average_utilization)}</p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <p className="text-xs text-gray-500">Avg Handoff Fidelity</p>
          <p className="mt-1 text-2xl font-semibold text-gray-900">{pct(report.average_handoff_fidelity)}</p>
        </div>
      </section>

      <section className="rounded-lg border border-gray-200 bg-white p-5">
        <h3 className="mb-4 text-sm font-semibold text-gray-900">Analyze Trace</h3>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <input
            value={traceIdInput}
            onChange={(event) => setTraceIdInput(event.target.value)}
            placeholder="Trace ID"
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
          />
          <input
            type="number"
            min={1}
            value={tokenBudget}
            onChange={(event) => setTokenBudget(Number(event.target.value))}
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
          />
          <select
            value={strategy}
            onChange={(event) => setStrategy(event.target.value as 'truncate_tail' | 'sliding_window' | 'summarize')}
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
          >
            <option value="summarize">summarize</option>
            <option value="truncate_tail">truncate_tail</option>
            <option value="sliding_window">sliding_window</option>
          </select>
          <input
            type="number"
            min={60}
            value={ttlSeconds}
            onChange={(event) => setTtlSeconds(Number(event.target.value))}
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
          />
        </div>
        <input
          value={pinKeywordsInput}
          onChange={(event) => setPinKeywordsInput(event.target.value)}
          placeholder="Pin keywords (comma-separated)"
          className="mt-3 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
        />
        <div className="mt-3 flex flex-wrap justify-end gap-2">
          <button
            onClick={onAnalyze}
            disabled={analysisQuery.isFetching}
            className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 transition hover:bg-gray-100 disabled:opacity-60"
          >
            {analysisQuery.isFetching ? 'Analyzing...' : 'Analyze'}
          </button>
          <button
            onClick={onSimulate}
            disabled={simulationMutation.isPending}
            className="rounded-lg bg-gray-900 px-3 py-1.5 text-sm font-medium text-white transition hover:bg-gray-800 disabled:opacity-60"
          >
            {simulationMutation.isPending ? 'Simulating...' : 'Simulate'}
          </button>
        </div>
      </section>

      <section className="rounded-lg border border-gray-200 bg-white p-5">
        <div className="mb-4 flex items-center gap-2">
          <Gauge className="h-4 w-4 text-gray-500" />
          <h3 className="text-sm font-semibold text-gray-900">Trace Analysis</h3>
        </div>
        {!analysis ? (
          <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50 p-4 text-sm text-gray-500">
            Provide a trace ID and click Analyze.
          </div>
        ) : (
          <div className="space-y-3">
            <div className="grid gap-2 text-xs text-gray-600 sm:grid-cols-3">
              <p>Growth: <span className="font-medium text-gray-900">{analysis.growth_pattern}</span></p>
              <p>Max util: <span className="font-medium text-gray-900">{pct(analysis.max_utilization)}</span></p>
              <p>Failures: <span className="font-medium text-gray-900">{analysis.total_failures}</span></p>
            </div>
            <div className="flex items-center justify-between">
              <p className="text-xs text-gray-600">
                High/Low failure rates: {pct(analysis.high_context_failure_rate)} / {pct(analysis.low_context_failure_rate)}
              </p>
              <StatusBadge
                variant={statusVariant(analysis.context_correlated_failures ? 'degraded' : 'active')}
                label={analysis.context_correlated_failures ? 'context-correlated' : 'stable'}
              />
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                <p className="text-xs font-semibold text-gray-900">Turn Utilization</p>
                <div className="mt-2 space-y-1">
                  {analysis.turns.slice(0, 8).map((turn) => (
                    <div key={turn.event_id} className="flex items-center justify-between text-xs text-gray-600">
                      <span>Turn {turn.turn_index}</span>
                      <span>{turn.tokens_used} tokens ({pct(turn.utilization_ratio)})</span>
                    </div>
                  ))}
                </div>
              </div>
              <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                <p className="text-xs font-semibold text-gray-900">Handoff Scores</p>
                {analysis.handoff_scores.length === 0 ? (
                  <p className="mt-2 text-xs text-gray-500">No handoff transfers in this trace.</p>
                ) : (
                  <div className="mt-2 space-y-2">
                    {analysis.handoff_scores.map((item, index) => (
                      <div key={`${item.from_agent}-${item.to_agent}-${index}`} className="text-xs text-gray-600">
                        <p>{item.from_agent} → {item.to_agent || '(unknown)'}</p>
                        <p className="text-gray-900">Score {pct(item.score)}</p>
                        {item.missing_fields.length > 0 && (
                          <p className="text-gray-500">Missing: {item.missing_fields.join(', ')}</p>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </section>

      <section className="rounded-lg border border-gray-200 bg-white p-5">
        <div className="mb-4 flex items-center gap-2">
          <Layers className="h-4 w-4 text-gray-500" />
          <h3 className="text-sm font-semibold text-gray-900">Simulation Result</h3>
        </div>
        {!simulation ? (
          <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50 p-4 text-sm text-gray-500">
            Run simulation to compare compaction strategies and budget outcomes.
          </div>
        ) : (
          <div className="space-y-3">
            <div className="grid gap-2 text-xs text-gray-600 sm:grid-cols-3">
              <p>Baseline util: <span className="font-medium text-gray-900">{pct(simulation.baseline_average_utilization)}</span></p>
              <p>Simulated util: <span className="font-medium text-gray-900">{pct(simulation.simulated_average_utilization)}</span></p>
              <p>Failure delta: <span className="font-medium text-gray-900">{simulation.estimated_failure_delta.toFixed(4)}</span></p>
            </div>
            <div className="grid gap-2 text-xs text-gray-600 sm:grid-cols-3">
              <p>Compaction loss: <span className="font-medium text-gray-900">{simulation.estimated_compaction_loss.toFixed(4)}</span></p>
              <p>Memory staleness: <span className="font-medium text-gray-900">{simulation.memory_staleness.toFixed(4)}</span></p>
              <p>Pinned hits: <span className="font-medium text-gray-900">{simulation.pinned_memory_hits}</span></p>
            </div>
            <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
              <p className="text-xs font-semibold text-gray-900">Budget Comparison</p>
              <div className="mt-2 space-y-1">
                {simulation.budget_comparison.map((row) => (
                  <div key={row.budget} className="flex items-center justify-between text-xs text-gray-600">
                    <span>{row.budget} tokens</span>
                    <span>util {pct(row.average_utilization)} · fail {pct(row.estimated_failure_rate)}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </section>

      <section className="rounded-lg border border-gray-200 bg-white p-5">
        <div className="mb-4 flex items-center gap-2">
          <NotebookPen className="h-4 w-4 text-gray-500" />
          <h3 className="text-sm font-semibold text-gray-900">Growth Patterns</h3>
        </div>
        {Object.keys(report.growth_pattern_counts).length === 0 ? (
          <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50 p-4 text-sm text-gray-500">
            No growth pattern data yet.
          </div>
        ) : (
          <div className="space-y-1">
            {Object.entries(report.growth_pattern_counts).map(([pattern, count]) => (
              <div key={pattern} className="flex items-center justify-between text-sm text-gray-700">
                <span>{pattern}</span>
                <span>{count}</span>
              </div>
            ))}
          </div>
        )}
        {report.context_correlated_failure_traces.length > 0 && (
          <p className="mt-3 text-xs text-gray-500">
            Context-correlated trace IDs (first 5):{' '}
            {report.context_correlated_failure_traces.slice(0, 5).join(', ')}
          </p>
        )}
        {activeTraceId && (
          <p className="mt-2 text-xs text-gray-400">Last analyzed trace: {activeTraceId}</p>
        )}
        {analysis && analysis.turns.length > 0 && (
          <p className="mt-2 text-xs text-gray-400">
            Most recent turn timestamp: {formatTimestamp(analysis.turns[analysis.turns.length - 1].timestamp)}
          </p>
        )}
      </section>
    </div>
  );
}
