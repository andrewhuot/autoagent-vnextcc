import { useState } from 'react';
import {
  AlertTriangle,
  AlertCircle,
  ChevronDown,
  ChevronRight,
  Clock,
  MessageSquare,
  Shield,
  TrendingDown,
  TrendingUp,
  Wrench,
  Zap,
} from 'lucide-react';
import { MetricCard } from '../../components/MetricCard';
import { classNames, formatTimestamp } from '../../lib/utils';
import type {
  EvidenceConversation,
  EvidenceTrace,
  IssueCategory,
  IssueSeverity,
  ProductionIssue,
} from './studio-types';
import {
  MOCK_EVIDENCE_CONVERSATIONS,
  MOCK_EVIDENCE_TRACES,
  MOCK_ISSUES,
  MOCK_PRODUCTION_METRICS,
} from './studio-mock';

// ─── Issue Severity helpers ───────────────────────────────────────────────────

const severityStyles: Record<IssueSeverity, { badge: string; dot: string }> = {
  critical: { badge: 'bg-red-100 text-red-700', dot: 'bg-red-500' },
  high: { badge: 'bg-orange-100 text-orange-700', dot: 'bg-orange-500' },
  medium: { badge: 'bg-amber-100 text-amber-700', dot: 'bg-amber-500' },
  low: { badge: 'bg-gray-100 text-gray-600', dot: 'bg-gray-400' },
};

const categoryIcons: Record<IssueCategory, React.ComponentType<{ className?: string }>> = {
  task_failure: AlertTriangle,
  latency: Clock,
  policy_violation: Shield,
  hallucination: AlertCircle,
  tool_error: Wrench,
};

const categoryLabels: Record<IssueCategory, string> = {
  task_failure: 'Task Failure',
  latency: 'Latency',
  policy_violation: 'Policy Violation',
  hallucination: 'Hallucination',
  tool_error: 'Tool Error',
};

// ─── Issue Card ───────────────────────────────────────────────────────────────

interface IssueCardProps {
  issue: ProductionIssue;
  isSelected: boolean;
  onSelect: () => void;
}

function IssueCard({ issue, isSelected, onSelect }: IssueCardProps) {
  const styles = severityStyles[issue.severity];
  const Icon = categoryIcons[issue.category];

  return (
    <button
      onClick={onSelect}
      className={classNames(
        'w-full rounded-lg border p-4 text-left transition-all',
        isSelected
          ? 'border-indigo-300 bg-indigo-50 shadow-sm'
          : 'border-gray-200 bg-white hover:border-indigo-200 hover:bg-gray-50'
      )}
    >
      <div className="mb-2 flex items-start justify-between gap-2">
        <div className="flex items-start gap-2">
          <Icon className="mt-0.5 h-4 w-4 shrink-0 text-gray-500" />
          <span className="text-sm font-medium text-gray-900 leading-snug">{issue.title}</span>
        </div>
        <span className={classNames('shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase', styles.badge)}>
          {issue.severity}
        </span>
      </div>

      <p className="mb-3 text-xs leading-relaxed text-gray-600 line-clamp-2">{issue.description}</p>

      <div className="flex items-center gap-4 text-[11px] text-gray-500">
        <span className="flex items-center gap-1">
          <span className={classNames('h-1.5 w-1.5 rounded-full', styles.dot)} />
          {categoryLabels[issue.category]}
        </span>
        <span>{issue.count.toLocaleString()} occurrences</span>
        <span>{issue.affected_sessions} sessions</span>
      </div>

      {isSelected && (
        <div className="mt-3 flex gap-2 border-t border-indigo-200 pt-3">
          {issue.example_trace_id && (
            <span className="rounded bg-indigo-100 px-2 py-0.5 text-[10px] font-medium text-indigo-700">
              Trace evidence
            </span>
          )}
          {issue.example_conversation_id && (
            <span className="rounded bg-violet-100 px-2 py-0.5 text-[10px] font-medium text-violet-700">
              Conversation evidence
            </span>
          )}
        </div>
      )}
    </button>
  );
}

// ─── Trace Evidence Panel ─────────────────────────────────────────────────────

const stepColors: Record<EvidenceTrace['steps'][number]['type'], string> = {
  model_call: 'bg-blue-500',
  tool_call: 'bg-green-500',
  tool_response: 'bg-green-400',
  error: 'bg-red-500',
  agent_transfer: 'bg-purple-500',
};

interface TraceEvidencePanelProps {
  traces: EvidenceTrace[];
  selectedIssue: ProductionIssue | null;
}

function TraceEvidencePanel({ traces, selectedIssue }: TraceEvidencePanelProps) {
  const [expanded, setExpanded] = useState<string | null>(traces[0]?.trace_id ?? null);

  const filteredTraces = selectedIssue?.example_trace_id
    ? traces.filter((t) => t.trace_id === selectedIssue.example_trace_id)
    : traces;

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-lg border border-gray-200 bg-white">
      <div className="flex items-center gap-2 border-b border-gray-200 px-4 py-3">
        <Zap className="h-4 w-4 text-blue-500" />
        <span className="text-sm font-semibold text-gray-800">Trace Evidence</span>
        {selectedIssue && (
          <span className="ml-auto rounded-full bg-blue-50 px-2 py-0.5 text-[10px] font-medium text-blue-600">
            Filtered by issue
          </span>
        )}
      </div>

      <div className="flex-1 overflow-y-auto divide-y divide-gray-100">
        {filteredTraces.length === 0 && (
          <div className="p-6 text-center text-sm text-gray-400">No trace evidence for this issue.</div>
        )}
        {filteredTraces.map((trace) => {
          const isOpen = expanded === trace.trace_id;
          const outcomeColor =
            trace.outcome === 'success'
              ? 'text-green-600'
              : trace.outcome === 'failure'
              ? 'text-red-500'
              : 'text-amber-500';

          return (
            <div key={trace.trace_id}>
              <button
                onClick={() => setExpanded(isOpen ? null : trace.trace_id)}
                className="flex w-full items-center gap-3 px-4 py-3 hover:bg-gray-50 transition-colors"
              >
                {isOpen ? (
                  <ChevronDown className="h-3.5 w-3.5 shrink-0 text-gray-400" />
                ) : (
                  <ChevronRight className="h-3.5 w-3.5 shrink-0 text-gray-400" />
                )}
                <div className="min-w-0 flex-1 text-left">
                  <span className="text-xs font-medium text-gray-800">{trace.trace_id}</span>
                  <span className="ml-2 text-[11px] text-gray-400">{formatTimestamp(trace.started_at)}</span>
                </div>
                <span className={classNames('text-xs font-medium', outcomeColor)}>{trace.outcome}</span>
                <span className="text-[11px] text-gray-400">{trace.latency_ms}ms</span>
              </button>

              {isOpen && (
                <div className="border-t border-gray-100 bg-gray-50 px-4 pb-3 pt-2">
                  <div className="relative space-y-2">
                    {trace.steps.map((step, idx) => {
                      const isLast = idx === trace.steps.length - 1;
                      return (
                        <div key={step.step_id} className="relative flex gap-3">
                          {!isLast && (
                            <div className="absolute left-[7px] top-4 h-full w-px bg-gray-200" />
                          )}
                          <div
                            className={classNames(
                              'relative z-10 mt-1 h-3.5 w-3.5 shrink-0 rounded-full',
                              stepColors[step.type] ?? 'bg-gray-400',
                              step.error ? 'ring-2 ring-red-300' : ''
                            )}
                          />
                          <div className="flex-1 pb-1">
                            <div className="flex items-baseline gap-2">
                              <span className="text-xs font-medium text-gray-800">{step.label}</span>
                              <span className="text-[10px] text-gray-400">{step.latency_ms}ms</span>
                            </div>
                            {step.error && (
                              <p className="mt-0.5 text-[11px] text-red-600">{step.error}</p>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Conversation Evidence Panel ──────────────────────────────────────────────

interface ConversationEvidencePanelProps {
  conversations: EvidenceConversation[];
  selectedIssue: ProductionIssue | null;
}

function ConversationEvidencePanel({ conversations, selectedIssue }: ConversationEvidencePanelProps) {
  const [activeCid, setActiveCid] = useState<string>(conversations[0]?.conversation_id ?? '');

  const filtered = selectedIssue?.example_conversation_id
    ? conversations.filter((c) => c.conversation_id === selectedIssue.example_conversation_id)
    : conversations;

  const active = filtered.find((c) => c.conversation_id === activeCid) ?? filtered[0];

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-lg border border-gray-200 bg-white">
      <div className="flex items-center gap-2 border-b border-gray-200 px-4 py-3">
        <MessageSquare className="h-4 w-4 text-violet-500" />
        <span className="text-sm font-semibold text-gray-800">Conversation Evidence</span>
        {selectedIssue && (
          <span className="ml-auto rounded-full bg-violet-50 px-2 py-0.5 text-[10px] font-medium text-violet-600">
            Filtered by issue
          </span>
        )}
      </div>

      {/* Session selector */}
      {filtered.length > 1 && (
        <div className="flex gap-1 overflow-x-auto border-b border-gray-100 px-3 py-2">
          {filtered.map((c) => (
            <button
              key={c.conversation_id}
              onClick={() => setActiveCid(c.conversation_id)}
              className={classNames(
                'shrink-0 rounded px-2.5 py-1 text-[11px] font-medium transition-colors',
                activeCid === c.conversation_id
                  ? 'bg-violet-100 text-violet-700'
                  : 'text-gray-500 hover:bg-gray-100'
              )}
            >
              {c.conversation_id}
            </button>
          ))}
        </div>
      )}

      {/* Turns */}
      <div className="flex-1 overflow-y-auto space-y-3 p-4">
        {!active && (
          <div className="py-6 text-center text-sm text-gray-400">
            No conversation evidence for this issue.
          </div>
        )}
        {active?.turns.map((turn) => (
          <div
            key={turn.turn_id}
            className={classNames('flex gap-2', turn.role === 'user' ? 'justify-start' : 'justify-end')}
          >
            <div className={classNames('max-w-[85%] space-y-1', turn.role === 'agent' ? 'items-end' : '')}>
              <div
                className={classNames(
                  'rounded-xl px-3 py-2 text-sm leading-relaxed',
                  turn.role === 'user'
                    ? 'bg-gray-100 text-gray-800'
                    : turn.flagged
                    ? 'bg-red-50 text-gray-800 ring-1 ring-red-300'
                    : 'bg-indigo-600 text-white'
                )}
              >
                {turn.content}
              </div>
              {turn.flagged && turn.flag_reason && (
                <div className="flex items-center gap-1 text-[10px] text-red-600">
                  <AlertTriangle className="h-2.5 w-2.5" />
                  {turn.flag_reason}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── StudioObserve ────────────────────────────────────────────────────────────

export function StudioObserve() {
  const [selectedIssueId, setSelectedIssueId] = useState<string | null>(MOCK_ISSUES[0].issue_id);
  const m = MOCK_PRODUCTION_METRICS;

  const selectedIssue = MOCK_ISSUES.find((i) => i.issue_id === selectedIssueId) ?? null;

  const deltaArrow = (delta: number) =>
    delta < 0 ? <TrendingDown className="inline h-3 w-3 text-red-500" /> : <TrendingUp className="inline h-3 w-3 text-green-500" />;

  return (
    <div className="flex h-full flex-col overflow-y-auto bg-gray-50 p-5 space-y-5">
      {/* Metrics row */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <MetricCard
          title="Success Rate"
          value={`${(m.success_rate * 100).toFixed(1)}%`}
          trend={m.success_rate_delta < 0 ? 'down' : 'up'}
          trendValue={`${(Math.abs(m.success_rate_delta) * 100).toFixed(1)}pp ${m.success_rate_delta < 0 ? '↓' : '↑'}`}
          subtitle="vs last 7 days"
          sparklineData={m.sparkline_success}
        />
        <MetricCard
          title="P95 Latency"
          value={`${(m.latency_p95_ms / 1000).toFixed(2)}s`}
          trend={m.latency_delta_pct > 0 ? 'down' : 'up'}
          trendValue={`+${(m.latency_delta_pct * 100).toFixed(0)}% ${deltaArrow(m.latency_delta_pct) as unknown as string}`}
          subtitle={`p50 ${m.latency_p50_ms}ms`}
          sparklineData={m.sparkline_latency}
        />
        <MetricCard
          title="Error Rate"
          value={`${(m.error_rate * 100).toFixed(1)}%`}
          trend={m.error_rate_delta > 0 ? 'down' : 'up'}
          trendValue={`${m.error_rate_delta > 0 ? '+' : ''}${(m.error_rate_delta * 100).toFixed(1)}pp`}
          subtitle="vs last 7 days"
          sparklineData={m.sparkline_errors}
        />
        <MetricCard
          title="Cost / Session"
          value={`$${m.cost_per_session_usd.toFixed(4)}`}
          trend={m.cost_delta_pct > 0 ? 'down' : 'up'}
          trendValue={`+${(m.cost_delta_pct * 100).toFixed(0)}%`}
          subtitle="vs last 7 days"
        />
      </div>

      {/* Issues + evidence split */}
      <div className="flex gap-5 flex-1 min-h-0">
        {/* Issue list */}
        <div className="w-[38%] min-w-[280px] space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-gray-800">
              Active Issues
              <span className="ml-2 rounded-full bg-red-100 px-2 py-0.5 text-[10px] font-semibold text-red-700">
                {MOCK_ISSUES.filter((i) => i.severity === 'critical' || i.severity === 'high').length} critical/high
              </span>
            </h3>
            <span className="text-[11px] text-gray-400">Click to filter evidence</span>
          </div>

          <div className="space-y-2">
            {MOCK_ISSUES.map((issue) => (
              <IssueCard
                key={issue.issue_id}
                issue={issue}
                isSelected={issue.issue_id === selectedIssueId}
                onSelect={() =>
                  setSelectedIssueId(
                    issue.issue_id === selectedIssueId ? null : issue.issue_id
                  )
                }
              />
            ))}
          </div>
        </div>

        {/* Evidence panels */}
        <div className="flex flex-1 flex-col gap-4 min-h-[500px]">
          <TraceEvidencePanel
            traces={MOCK_EVIDENCE_TRACES as EvidenceTrace[]}
            selectedIssue={selectedIssue}
          />
          <ConversationEvidencePanel
            conversations={MOCK_EVIDENCE_CONVERSATIONS as EvidenceConversation[]}
            selectedIssue={selectedIssue}
          />
        </div>
      </div>
    </div>
  );
}
