import { useState } from 'react';
import { Activity, ChevronDown, ChevronRight, Search } from 'lucide-react';
import { PageHeader } from '../components/PageHeader';
import { TraceTimeline } from '../components/TraceTimeline';
import type { Trace } from '../lib/types';
import { classNames } from '../lib/utils';

const mockTraces: Trace[] = [
  {
    trace_id: 'tr_001',
    events: [
      {
        event_id: 'e1',
        event_type: 'model_call',
        timestamp: Date.now() / 1000 - 10,
        agent_path: 'root',
        latency_ms: 450,
        tokens_in: 500,
        tokens_out: 200,
      },
      {
        event_id: 'e2',
        event_type: 'tool_call',
        timestamp: Date.now() / 1000 - 8,
        agent_path: 'root/orders',
        tool_name: 'orders_db',
        latency_ms: 50,
      },
      {
        event_id: 'e3',
        event_type: 'tool_response',
        timestamp: Date.now() / 1000 - 7,
        agent_path: 'root/orders',
        tool_name: 'orders_db',
        latency_ms: 0,
      },
      {
        event_id: 'e4',
        event_type: 'model_response',
        timestamp: Date.now() / 1000 - 5,
        agent_path: 'root',
        latency_ms: 300,
        tokens_out: 150,
      },
    ],
  },
  {
    trace_id: 'tr_002',
    events: [
      {
        event_id: 'e5',
        event_type: 'model_call',
        timestamp: Date.now() / 1000 - 60,
        agent_path: 'root',
        latency_ms: 200,
        tokens_in: 300,
      },
      {
        event_id: 'e6',
        event_type: 'error',
        timestamp: Date.now() / 1000 - 58,
        agent_path: 'root/support',
        latency_ms: 0,
        error_message: 'Tool timeout after 5000ms',
      },
    ],
  },
];

const eventTypes = ['all', 'model_call', 'model_response', 'tool_call', 'tool_response', 'error', 'agent_transfer'];

export function Traces() {
  const [expandedTrace, setExpandedTrace] = useState<string | null>(null);
  const [eventTypeFilter, setEventTypeFilter] = useState('all');
  const [agentPathFilter, setAgentPathFilter] = useState('');

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

      {/* Trace list */}
      <div className="space-y-2">
        {mockTraces.map((trace) => {
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
                  <TraceTimeline events={filtered.events} />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
