import { useMemo, useState } from 'react';
import { Activity, ChevronDown, ChevronRight, GitBranchPlus, Search, Workflow } from 'lucide-react';
import { PageHeader } from '../components/PageHeader';
import { TraceTimeline } from '../components/TraceTimeline';
import { usePromoteTrace, useRecentTraces, useTraceGrades, useTraceGraph } from '../lib/api';
import type { Trace, TraceEvent } from '../lib/types';
import { toastError, toastSuccess } from '../lib/toast';
import { classNames } from '../lib/utils';

const eventTypes = ['all', 'model_call', 'model_response', 'tool_call', 'tool_response', 'error', 'agent_transfer'];

function groupEventsIntoTraces(events: TraceEvent[]): Trace[] {
  const traceMap = new Map<string, TraceEvent[]>();
  for (const event of events) {
    const traceId = event.event_id.split('.')[0] ?? event.event_id;
    const existing = traceMap.get(traceId);
    if (existing) {
      existing.push(event);
    } else {
      traceMap.set(traceId, [event]);
    }
  }
  return Array.from(traceMap.entries()).map(([trace_id, traceEvents]) => ({
    trace_id,
    events: traceEvents,
  }));
}

export function Traces() {
  const [expandedTrace, setExpandedTrace] = useState<string | null>(null);
  const [eventTypeFilter, setEventTypeFilter] = useState('all');
  const [agentPathFilter, setAgentPathFilter] = useState('');

  const { data: recentEvents, isLoading, isError } = useRecentTraces();

  const traces = useMemo(() => groupEventsIntoTraces(recentEvents ?? []), [recentEvents]);

  function toggleTrace(traceId: string) {
    setExpandedTrace((current) => (current === traceId ? null : traceId));
  }

  function filterEvents(trace: Trace): Trace {
    let events = trace.events;
    if (eventTypeFilter !== 'all') {
      events = events.filter((e) => e.event_type === eventTypeFilter);
    }
    if (agentPathFilter.trim()) {
      const term = agentPathFilter.toLowerCase();
      events = events.filter((e) => e.agent_path.toLowerCase().includes(term));
    }
    return { ...trace, events };
  }

  const hasErrors = (trace: Trace) => trace.events.some((e) => e.event_type === 'error');

  const totalLatency = (trace: Trace) =>
    trace.events.reduce((sum, e) => sum + e.latency_ms, 0);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Traces"
        description="ADK event traces and spans for diagnosis"
      />

      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-gray-200 bg-white px-4 py-3">
        <div className="flex items-center gap-2">
          <label className="text-xs text-gray-500">Event type</label>
          <select
            value={eventTypeFilter}
            onChange={(e) => setEventTypeFilter(e.target.value)}
            className="rounded-lg border border-gray-300 bg-white px-2.5 py-1.5 text-sm text-gray-700 focus:border-blue-500 focus:outline-none"
          >
            {eventTypes.map((type) => (
              <option key={type} value={type}>
                {type === 'all' ? 'All types' : type.replaceAll('_', ' ')}
              </option>
            ))}
          </select>
        </div>

        <div className="flex items-center gap-2">
          <label className="text-xs text-gray-500">Agent path</label>
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-gray-400" />
            <input
              type="text"
              placeholder="e.g. root/orders"
              value={agentPathFilter}
              onChange={(e) => setAgentPathFilter(e.target.value)}
              className="rounded-lg border border-gray-300 py-1.5 pl-8 pr-3 text-sm focus:border-blue-500 focus:outline-none"
            />
          </div>
        </div>
      </div>

      {/* Loading / error states */}
      {isLoading && (
        <div className="flex h-32 items-center justify-center rounded-xl border border-dashed border-gray-200 bg-gray-50 text-sm text-gray-500">
          Loading traces…
        </div>
      )}
      {isError && (
        <div className="flex h-32 items-center justify-center rounded-xl border border-dashed border-red-200 bg-red-50 text-sm text-red-600">
          Failed to load traces.
        </div>
      )}

      {/* Trace list */}
      {!isLoading && !isError && (
        <div className="space-y-2">
          {traces.length === 0 ? (
            <div className="flex h-32 items-center justify-center rounded-xl border border-dashed border-gray-200 bg-gray-50 text-sm text-gray-500">
              No traces recorded yet.
            </div>
          ) : (
            traces.map((trace) => {
              const isExpanded = expandedTrace === trace.trace_id;
              const filtered = filterEvents(trace);
              const errored = hasErrors(trace);
              const latency = totalLatency(trace);

              return (
                <div
                  key={trace.trace_id}
                  className={classNames(
                    'rounded-xl border bg-white transition-colors',
                    errored ? 'border-red-200' : 'border-gray-200'
                  )}
                >
                  {/* Trace header */}
                  <button
                    onClick={() => toggleTrace(trace.trace_id)}
                    className="flex w-full items-center gap-3 px-4 py-3 text-left"
                  >
                    {isExpanded ? (
                      <ChevronDown className="h-4 w-4 shrink-0 text-gray-400" />
                    ) : (
                      <ChevronRight className="h-4 w-4 shrink-0 text-gray-400" />
                    )}
                    <Activity className="h-4 w-4 shrink-0 text-gray-400" />
                    <span className="font-mono text-sm font-medium text-gray-900">{trace.trace_id}</span>
                    <span className="text-xs text-gray-500">{trace.events.length} events</span>
                    <span className="text-xs tabular-nums text-gray-500">{latency}ms total</span>
                    {errored && (
                      <span className="rounded-md bg-red-50 px-2 py-0.5 text-[11px] font-medium text-red-700">
                        has errors
                      </span>
                    )}
                  </button>

                  {/* Expanded trace timeline */}
                  {isExpanded && (
                    <div className="border-t border-gray-100 px-4 py-4">
                      <ExpandedTracePanel traceId={trace.trace_id} events={filtered.events} />
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}

function ExpandedTracePanel({ traceId, events }: { traceId: string; events: TraceEvent[] }) {
  const gradesQuery = useTraceGrades(traceId);
  const graphQuery = useTraceGraph(traceId);
  const promoteTrace = usePromoteTrace();

  const passingGrades = (gradesQuery.data ?? []).filter((grade) => grade.passed).length;
  const failingGrades = (gradesQuery.data ?? []).filter((grade) => !grade.passed).length;
  const criticalPath = graphQuery.data?.critical_path ?? [];
  const bottlenecks = graphQuery.data?.bottlenecks ?? [];

  function handlePromote() {
    promoteTrace.mutate(
      { traceId },
      {
        onSuccess: (result) => {
          toastSuccess('Trace promoted', `Created eval case at ${result.path}.`);
        },
        onError: (error) => {
          toastError('Promote failed', error.message);
        },
      }
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="grid min-w-0 flex-1 gap-3 sm:grid-cols-3">
          <TraceMetric label="Events" value={String(events.length)} />
          <TraceMetric
            label="Grades"
            value={
              gradesQuery.isLoading
                ? 'Loading...'
                : `${passingGrades} pass / ${failingGrades} fail`
            }
          />
          <TraceMetric
            label="Graph"
            value={
              graphQuery.isLoading
                ? 'Loading...'
                : `${criticalPath.length} critical / ${bottlenecks.length} bottlenecks`
            }
          />
        </div>

        <button
          onClick={handlePromote}
          disabled={promoteTrace.isPending}
          className="inline-flex items-center gap-2 rounded-lg bg-gray-900 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-gray-800 disabled:opacity-60"
        >
          <GitBranchPlus className="h-4 w-4" />
          {promoteTrace.isPending ? 'Promoting...' : 'Promote to Eval'}
        </button>
      </div>

      {gradesQuery.data && gradesQuery.data.length > 0 ? (
        <section className="rounded-xl border border-gray-200 bg-gray-50 p-4">
          <h4 className="text-sm font-semibold text-gray-900">Grade Detail</h4>
          <div className="mt-3 space-y-2">
            {gradesQuery.data.map((grade) => (
              <div
                key={`${grade.grader_name}-${grade.span_id}`}
                className="flex flex-wrap items-start justify-between gap-3 rounded-lg border border-gray-200 bg-white px-3 py-2"
              >
                <div>
                  <p className="text-sm font-medium text-gray-900">{grade.grader_name}</p>
                  <p className="text-xs text-gray-500">Span {grade.span_id}</p>
                  {grade.failure_reason ? (
                    <p className="mt-1 text-xs text-rose-700">{grade.failure_reason}</p>
                  ) : null}
                </div>
                <div className="text-right">
                  <p className="text-sm font-semibold text-gray-900">{grade.score.toFixed(2)}</p>
                  <p className={classNames('text-xs font-medium', grade.passed ? 'text-emerald-700' : 'text-rose-700')}>
                    {grade.passed ? 'PASS' : 'FAIL'}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : gradesQuery.isError ? (
        <section className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          Unable to load trace grades.
        </section>
      ) : null}

      {graphQuery.data ? (
        <section className="grid gap-4 xl:grid-cols-2">
          <div className="rounded-xl border border-gray-200 bg-gray-50 p-4">
            <div className="mb-3 flex items-center gap-2">
              <Workflow className="h-4 w-4 text-gray-500" />
              <h4 className="text-sm font-semibold text-gray-900">Critical Path</h4>
            </div>
            {criticalPath.length > 0 ? (
              <div className="space-y-2">
                {criticalPath.map((node) => (
                  <div key={`${node.span_id}-critical`} className="rounded-lg border border-gray-200 bg-white px-3 py-2">
                    <p className="text-sm font-medium text-gray-900">{node.operation}</p>
                    <p className="mt-1 text-xs text-gray-500">
                      {node.duration_ms.toFixed(1)}ms · {node.status}
                    </p>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-gray-500">No critical path nodes available.</p>
            )}
          </div>

          <div className="rounded-xl border border-gray-200 bg-gray-50 p-4">
            <h4 className="mb-3 text-sm font-semibold text-gray-900">Bottlenecks</h4>
            {bottlenecks.length > 0 ? (
              <div className="space-y-2">
                {bottlenecks.map((node) => (
                  <div key={`${node.span_id}-bottleneck`} className="rounded-lg border border-gray-200 bg-white px-3 py-2">
                    <p className="text-sm font-medium text-gray-900">{node.operation}</p>
                    <p className="mt-1 text-xs text-gray-500">
                      {node.duration_ms.toFixed(1)}ms · span {node.span_id}
                    </p>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-gray-500">No bottlenecks detected.</p>
            )}
          </div>
        </section>
      ) : graphQuery.isError ? (
        <section className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          Unable to load trace graph detail.
        </section>
      ) : null}

      <TraceTimeline events={events} />
    </div>
  );
}

function TraceMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-gray-200 bg-gray-50 px-3 py-2">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">{label}</p>
      <p className="mt-2 text-sm font-medium text-gray-900">{value}</p>
    </div>
  );
}
