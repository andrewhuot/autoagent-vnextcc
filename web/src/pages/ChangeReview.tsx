import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Check, X, Download, ChevronDown, ChevronRight, AlertTriangle, FileCheck, Shield, TrendingUp } from 'lucide-react';
import { EmptyState } from '../components/EmptyState';
import { PageHeader } from '../components/PageHeader';
import { HunkDiffViewer } from '../components/DiffViewer';
import { useChanges, useApplyChange, useRejectChange, useUpdateHunkStatus, useChangeAuditSummary, useChangeAudit } from '../lib/api';
import { classNames } from '../lib/utils';
import type { ChangeCard } from '../lib/types';

const API_BASE = '/api';

const riskColors: Record<string, string> = {
  low: 'bg-green-50 text-green-700',
  medium: 'bg-yellow-50 text-yellow-700',
  high: 'bg-red-50 text-red-700',
};

function MetricBar({ label, before, after }: { label: string; before: number; after: number }) {
  const improved = after >= before;
  const pct = Math.min(after * 100, 100);
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-20 shrink-0 text-gray-600">{label}</span>
      <div className="flex-1 h-2 bg-gray-200 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full ${improved ? 'bg-green-500' : 'bg-red-400'}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className={`font-mono ${improved ? 'text-green-700' : 'text-red-600'}`}>
        {after.toFixed(4)}
      </span>
    </div>
  );
}

async function fetchChangeExport(id: string): Promise<string> {
  const res = await fetch(`${API_BASE}/changes/${encodeURIComponent(id)}/export`);
  if (!res.ok) throw new Error(`Export failed: ${res.status}`);
  const data = await res.json();
  return data.markdown ?? '';
}

function SelectedCardDetail({ selectedCard }: { selectedCard: ChangeCard }) {
  const [rejectReason, setRejectReason] = useState('');
  const [showRejectInput, setShowRejectInput] = useState(false);

  const applyMutation = useApplyChange();
  const rejectMutation = useRejectChange();
  const updateHunkStatus = useUpdateHunkStatus();
  const { data: auditDetail } = useChangeAudit(selectedCard.id);

  const exportQuery = useQuery({
    queryKey: ['changes', 'export', selectedCard.id],
    queryFn: () => fetchChangeExport(selectedCard.id),
    enabled: false,
  });

  function handleApply() {
    applyMutation.mutate({ id: selectedCard.id });
  }

  function handleReject() {
    if (!rejectReason.trim()) return;
    rejectMutation.mutate(
      { id: selectedCard.id, reason: rejectReason },
      {
        onSuccess: () => {
          setRejectReason('');
          setShowRejectInput(false);
        },
      }
    );
  }

  function handleExport() {
    exportQuery.refetch().then((result) => {
      if (result.data) {
        const blob = new Blob([result.data], { type: 'text/markdown' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `change-${selectedCard.id}.md`;
        link.click();
        URL.revokeObjectURL(url);
      }
    });
  }

  function handleHunkAccept(hunkId: string) {
    updateHunkStatus.mutate({ cardId: selectedCard.id, hunkId, status: 'accepted' });
  }

  function handleHunkReject(hunkId: string) {
    updateHunkStatus.mutate({ cardId: selectedCard.id, hunkId, status: 'rejected' });
  }

  // Build combined metric keys from before+after for bar chart
  const metricKeys = Array.from(
    new Set([
      ...Object.keys(selectedCard.metrics_before),
      ...Object.keys(selectedCard.metrics_after),
    ])
  );
  const hasCandidateHandoff = Boolean(
    selectedCard.candidate_config_version ||
    selectedCard.candidate_config_path ||
    selectedCard.source_eval_path ||
    selectedCard.experiment_card_id
  );

  return (
    <section className="rounded-lg border border-gray-200 bg-white p-5">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-gray-900">{selectedCard.title}</h3>
          <p className="mt-1 text-sm text-gray-600">{selectedCard.why}</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleExport}
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 transition hover:bg-gray-100"
          >
            <Download className="h-3.5 w-3.5" />
            Export MD
          </button>
          <button
            onClick={handleApply}
            disabled={applyMutation.isPending}
            className="inline-flex items-center gap-1.5 rounded-lg bg-green-600 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-green-700 disabled:opacity-60"
          >
            <Check className="h-3.5 w-3.5" />
            {applyMutation.isPending ? 'Applying...' : 'Apply'}
          </button>
          <button
            onClick={() => setShowRejectInput(!showRejectInput)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-red-600 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-red-700"
          >
            <X className="h-3.5 w-3.5" />
            Reject
          </button>
        </div>
      </div>

      {showRejectInput && (
        <div className="mb-4 flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 p-3">
          <input
            type="text"
            placeholder="Rejection reason..."
            value={rejectReason}
            onChange={(e) => setRejectReason(e.target.value)}
            className="flex-1 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm focus:border-red-500 focus:outline-none"
          />
          <button
            onClick={handleReject}
            disabled={rejectMutation.isPending || !rejectReason.trim()}
            className="rounded-md bg-red-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-60"
          >
            {rejectMutation.isPending ? 'Rejecting...' : 'Confirm Reject'}
          </button>
        </div>
      )}

      {/* Summary card */}
      <div className="mb-4 rounded-lg border border-blue-200 bg-blue-50 p-4">
        <h4 className="text-sm font-semibold text-blue-900">Summary</h4>
        <p className="mt-1 text-sm text-blue-700">
          This change {selectedCard.why} by modifying {selectedCard.diff_hunks.length} config section
          {selectedCard.diff_hunks.length !== 1 ? 's' : ''}.
        </p>
      </div>

      {hasCandidateHandoff && (
        <div className="mb-4 rounded-lg border border-gray-200 bg-gray-50 p-3">
          <h4 className="text-xs font-medium text-gray-500">Candidate handoff</h4>
          <div className="mt-2 space-y-2 text-sm text-gray-700">
            {selectedCard.candidate_config_version ? (
              <p>
                <span className="font-medium text-gray-900">
                  Candidate v{selectedCard.candidate_config_version}
                </span>
              </p>
            ) : null}
            {selectedCard.candidate_config_path ? (
              <p className="break-all font-mono text-xs text-gray-600">{selectedCard.candidate_config_path}</p>
            ) : null}
            {selectedCard.source_eval_path ? (
              <p className="break-all font-mono text-xs text-gray-600">{selectedCard.source_eval_path}</p>
            ) : null}
            {selectedCard.experiment_card_id ? (
              <p className="text-xs text-gray-600">Experiment {selectedCard.experiment_card_id}</p>
            ) : null}
          </div>
          <p className="mt-3 text-sm text-gray-600">
            Apply sets this candidate as the local active config when the server has the matching
            config version, syncs the experiment decision, and should be followed by a fresh eval
            before deploy.
          </p>
        </div>
      )}

      {/* Info badges */}
      <div className="mb-4 flex flex-wrap gap-2">
        <span
          className={classNames(
            'inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium',
            riskColors[selectedCard.risk] ?? 'bg-gray-100 text-gray-600'
          )}
        >
          <AlertTriangle className="h-3 w-3" />
          {selectedCard.risk} risk
        </span>
        <span className="inline-flex items-center gap-1 rounded-md bg-blue-50 px-2 py-1 text-[11px] font-medium text-blue-700">
          <Shield className="h-3 w-3" />
          {Math.round(selectedCard.confidence.score * 100)}% confidence
        </span>
        <span className="rounded-md bg-gray-100 px-2 py-1 text-[11px] font-medium text-gray-600">
          {selectedCard.status}
        </span>
      </div>

      {/* Confidence explanation */}
      <div className="mb-4 rounded-lg border border-gray-200 bg-gray-50 p-3">
        <h4 className="text-xs font-medium text-gray-500">Confidence Explanation</h4>
        <p className="mt-1 text-sm text-gray-700">{selectedCard.confidence.explanation}</p>
        {selectedCard.confidence.evidence.length > 0 && (
          <ul className="mt-2 space-y-1">
            {selectedCard.confidence.evidence.map((e, i) => (
              <li key={i} className="text-xs text-gray-600">
                - {e}
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Metrics comparison with bar chart */}
      <div className="mb-4 rounded-lg border border-gray-200 bg-gray-50 p-3">
        <h4 className="mb-3 flex items-center gap-1.5 text-xs font-medium text-gray-500">
          <TrendingUp className="h-3 w-3" />
          Metrics Before → After
        </h4>
        <div className="space-y-2">
          {metricKeys.map((key) => {
            const before = selectedCard.metrics_before[key] ?? 0;
            const after = selectedCard.metrics_after[key] ?? 0;
            return <MetricBar key={key} label={key} before={before} after={after} />;
          })}
        </div>
      </div>

      {/* Rollout plan */}
      {selectedCard.rollout_plan && (
        <div className="mb-4 rounded-lg border border-gray-200 bg-gray-50 p-3">
          <h4 className="text-xs font-medium text-gray-500">Rollout Plan</h4>
          <p className="mt-1 text-sm text-gray-700">{selectedCard.rollout_plan}</p>
        </div>
      )}

      {auditDetail && (
        <>
          <div className="mb-4 rounded-lg border border-gray-200 bg-gray-50 p-3">
            <h4 className="text-xs font-medium text-gray-500">Gate results</h4>
            <div className="mt-2 space-y-1">
              {auditDetail.gate_decisions.map((gate) => (
                <div key={gate.gate} className="flex items-center justify-between rounded border border-gray-200 bg-white px-2 py-1 text-xs">
                  <span className="font-medium text-gray-700">{gate.gate}</span>
                  <span className={gate.passed ? 'text-green-700' : 'text-red-700'}>
                    {gate.passed ? 'Passed' : 'Failed'} · {gate.reason}
                  </span>
                </div>
              ))}
            </div>
          </div>

          <div className="mb-4 rounded-lg border border-gray-200 bg-gray-50 p-3">
            <h4 className="text-xs font-medium text-gray-500">Composite breakdown</h4>
            <div className="mt-2 space-y-2">
              {Object.entries(auditDetail.composite_breakdown).map(([metric, value]) => (
                <div key={metric} className="flex items-center justify-between text-xs">
                  <span className="text-gray-600">{metric}</span>
                  <span className={value >= 0 ? 'font-mono text-green-700' : 'font-mono text-red-700'}>
                    {value > 0 ? '+' : ''}{value.toFixed(4)}
                  </span>
                </div>
              ))}
            </div>
          </div>

          <div className="mb-4 rounded-lg border border-gray-200 bg-gray-50 p-3">
            <h4 className="text-xs font-medium text-gray-500">Attempt timeline</h4>
            <div className="mt-2 space-y-1">
              {auditDetail.timeline.map((item, idx) => (
                <div key={`${item.stage}-${idx}`} className="rounded border border-gray-200 bg-white px-2 py-1 text-xs text-gray-700">
                  <span className="font-semibold">{item.stage}</span> · {item.detail}
                </div>
              ))}
            </div>
          </div>
        </>
      )}

      {/* Diff hunks via HunkDiffViewer with per-hunk accept/reject */}
      <div>
        <h4 className="mb-2 text-xs font-medium text-gray-500">
          Diff Hunks ({selectedCard.diff_hunks.length})
        </h4>
        <HunkDiffViewer
          hunks={selectedCard.diff_hunks}
          onAccept={handleHunkAccept}
          onReject={handleHunkReject}
        />
      </div>
    </section>
  );
}

interface ChangeReviewProps {
  embedded?: boolean;
}

export function ChangeReview({ embedded = false }: ChangeReviewProps) {
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const { data: changes = [], isLoading, isError } = useChanges();
  const { data: auditSummary } = useChangeAuditSummary();

  const selectedCard = changes.find((c) => c.id === selectedId) ?? null;
  const pendingChanges = changes.filter((c) => c.status === 'pending');

  return (
    <div className="space-y-6">
      {!embedded && (
        <PageHeader
          title="Change Review"
          description="Review proposed changes with diffs, metrics, and confidence scores before applying"
        />
      )}

      {auditSummary && (
        <section className="rounded-lg border border-gray-200 bg-white p-5">
          <h3 className="text-sm font-semibold text-gray-900">Audit Summary</h3>
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            <div className="rounded-md border border-gray-200 bg-gray-50 p-3 text-xs">
              <p className="text-gray-500">Accept rate</p>
              <p className="mt-1 text-lg font-semibold text-gray-900">
                {(auditSummary.accept_rate * 100).toFixed(1)}%
              </p>
            </div>
            <div className="rounded-md border border-gray-200 bg-gray-50 p-3 text-xs">
              <p className="text-gray-500">Accepted</p>
              <p className="mt-1 text-lg font-semibold text-green-700">{auditSummary.accepted_changes}</p>
            </div>
            <div className="rounded-md border border-gray-200 bg-gray-50 p-3 text-xs">
              <p className="text-gray-500">Rejected</p>
              <p className="mt-1 text-lg font-semibold text-red-700">{auditSummary.rejected_changes}</p>
            </div>
          </div>
          <div className="mt-3 rounded-md border border-gray-200 bg-gray-50 p-3">
            <p className="text-xs font-medium text-gray-600">Top rejection reasons</p>
            <div className="mt-1 space-y-1">
              {auditSummary.top_rejection_reasons.length === 0 && (
                <p className="text-xs text-gray-500">No rejection reasons recorded yet.</p>
              )}
              {auditSummary.top_rejection_reasons.map((entry) => (
                <p key={entry.reason} className="text-xs text-gray-700">
                  {entry.reason} ({entry.count})
                </p>
              ))}
            </div>
          </div>
        </section>
      )}

      {/* Loading / error */}
      {isLoading && (
        <div className="flex h-32 items-center justify-center rounded-xl border border-dashed border-gray-200 bg-gray-50 text-sm text-gray-500">
          Loading change cards...
        </div>
      )}
      {isError && (
        <div className="flex h-32 items-center justify-center rounded-xl border border-dashed border-red-200 bg-red-50 text-sm text-red-600">
          Failed to load change cards.
        </div>
      )}

      {!isLoading && !isError && changes.length === 0 && (
        <EmptyState
          icon={FileCheck}
          title="No change cards yet"
          description="Change cards are generated when the optimizer proposes config improvements. Run an optimization cycle to see proposals here."
          cliHint="agentlab optimize"
        />
      )}

      {!isLoading && !isError && changes.length > 0 && (
        <>
          {/* Pending cards list */}
          <section className="rounded-lg border border-gray-200 bg-white p-5">
            <h3 className="mb-4 text-sm font-semibold text-gray-900">
              Pending Changes ({pendingChanges.length})
            </h3>
            {pendingChanges.length === 0 ? (
              <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50 p-4 text-sm text-gray-500">
                No pending change cards.
              </div>
            ) : (
              <div className="space-y-2">
                {pendingChanges.map((card) => (
                  <button
                    key={card.id}
                    onClick={() => setSelectedId(card.id)}
                    className={classNames(
                      'flex w-full items-center gap-3 rounded-lg border px-4 py-3 text-left transition-colors',
                      selectedId === card.id
                        ? 'border-blue-300 bg-blue-50'
                        : 'border-gray-200 bg-gray-50 hover:bg-gray-100'
                    )}
                  >
                    {selectedId === card.id ? (
                      <ChevronDown className="h-4 w-4 shrink-0 text-blue-500" />
                    ) : (
                      <ChevronRight className="h-4 w-4 shrink-0 text-gray-400" />
                    )}
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-gray-900">{card.title}</p>
                      <p className="mt-0.5 truncate text-xs text-gray-500">{card.why}</p>
                    </div>
                    <span
                      className={classNames(
                        'rounded-md px-2 py-0.5 text-[11px] font-medium',
                        riskColors[card.risk] ?? 'bg-gray-100 text-gray-600'
                      )}
                    >
                      {card.risk} risk
                    </span>
                    <span className="rounded-md bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-600">
                      {Math.round(card.confidence.score * 100)}% confidence
                    </span>
                  </button>
                ))}
              </div>
            )}
          </section>

          {/* Selected card detail */}
          {selectedCard && <SelectedCardDetail selectedCard={selectedCard} />}

          {/* Resolved changes */}
          {changes.filter((c) => c.status !== 'pending').length > 0 && (
            <section className="rounded-lg border border-gray-200 bg-white p-5">
              <h3 className="mb-4 text-sm font-semibold text-gray-900">Resolved Changes</h3>
              <div className="space-y-2">
                {changes
                  .filter((c) => c.status !== 'pending')
                  .map((card) => (
                    <div
                      key={card.id}
                      className="flex items-center justify-between rounded-lg border border-gray-200 bg-gray-50 px-4 py-3"
                    >
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium text-gray-900">{card.title}</p>
                        <p className="mt-0.5 text-xs text-gray-500">{card.updated_at}</p>
                      </div>
                      <span
                        className={classNames(
                          'rounded-md px-2 py-0.5 text-[11px] font-medium',
                          card.status === 'applied'
                            ? 'bg-green-50 text-green-700'
                            : 'bg-red-50 text-red-700'
                        )}
                      >
                        {card.status}
                      </span>
                    </div>
                  ))}
              </div>
            </section>
          )}
        </>
      )}
    </div>
  );
}
