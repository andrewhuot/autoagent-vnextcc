import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Check, X, Download, ChevronDown, ChevronRight, AlertTriangle, Shield, TrendingUp } from 'lucide-react';
import { PageHeader } from '../components/PageHeader';
import { useChanges, useApplyChange, useRejectChange } from '../lib/api';
import { classNames } from '../lib/utils';
import type { ChangeCard, DiffHunk } from '../lib/types';

const API_BASE = '/api';

const riskColors: Record<string, string> = {
  low: 'bg-green-50 text-green-700',
  medium: 'bg-yellow-50 text-yellow-700',
  high: 'bg-red-50 text-red-700',
};

function HunkViewer({ hunk, index }: { hunk: DiffHunk; index: number }) {
  const lines = hunk.content.split('\n');
  return (
    <div className="rounded-lg border border-gray-200 bg-white">
      <div className="flex items-center justify-between border-b border-gray-100 px-3 py-2">
        <span className="font-mono text-xs text-gray-600">{hunk.file_path}</span>
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-gray-400">
            @@ -{hunk.old_start},{hunk.old_count} +{hunk.new_start},{hunk.new_count} @@
          </span>
          <span
            className={classNames(
              'rounded-md px-1.5 py-0.5 text-[10px] font-medium',
              hunk.status === 'accepted'
                ? 'bg-green-50 text-green-700'
                : hunk.status === 'rejected'
                  ? 'bg-red-50 text-red-700'
                  : 'bg-gray-100 text-gray-600'
            )}
          >
            {hunk.status}
          </span>
        </div>
      </div>
      <pre className="max-h-64 overflow-auto p-3 text-xs">
        {lines.map((line, i) => (
          <div
            key={`${index}-${i}`}
            className={classNames(
              'px-1',
              line.startsWith('+') ? 'bg-green-50 text-green-800' : '',
              line.startsWith('-') ? 'bg-red-50 text-red-800' : '',
              !line.startsWith('+') && !line.startsWith('-') ? 'text-gray-600' : ''
            )}
          >
            {line}
          </div>
        ))}
      </pre>
    </div>
  );
}

async function fetchChangeExport(id: string): Promise<string> {
  const res = await fetch(`${API_BASE}/changes/${encodeURIComponent(id)}/export`);
  if (!res.ok) throw new Error(`Export failed: ${res.status}`);
  const data = await res.json();
  return data.markdown ?? '';
}

export function ChangeReview() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState('');
  const [showRejectInput, setShowRejectInput] = useState(false);

  const { data: changes = [], isLoading, isError } = useChanges();
  const applyMutation = useApplyChange();
  const rejectMutation = useRejectChange();

  const exportQuery = useQuery({
    queryKey: ['changes', 'export', selectedId],
    queryFn: () => fetchChangeExport(selectedId!),
    enabled: false,
  });

  const selectedCard = changes.find((c) => c.id === selectedId) ?? null;
  const pendingChanges = changes.filter((c) => c.status === 'pending');

  function handleApply(id: string) {
    applyMutation.mutate({ id });
  }

  function handleReject(id: string) {
    if (!rejectReason.trim()) return;
    rejectMutation.mutate(
      { id, reason: rejectReason },
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
        link.download = `change-${selectedId}.md`;
        link.click();
        URL.revokeObjectURL(url);
      }
    });
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Change Review"
        description="Review proposed changes with diffs, metrics, and confidence scores before applying"
      />

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

      {!isLoading && !isError && (
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
          {selectedCard && (
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
                    onClick={() => handleApply(selectedCard.id)}
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
                    onClick={() => handleReject(selectedCard.id)}
                    disabled={rejectMutation.isPending || !rejectReason.trim()}
                    className="rounded-md bg-red-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-60"
                  >
                    {rejectMutation.isPending ? 'Rejecting...' : 'Confirm Reject'}
                  </button>
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

              {/* Metrics before/after */}
              <div className="mb-4 grid gap-4 sm:grid-cols-2">
                <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                  <h4 className="mb-2 flex items-center gap-1.5 text-xs font-medium text-gray-500">
                    <TrendingUp className="h-3 w-3" />
                    Metrics Before
                  </h4>
                  <div className="space-y-1">
                    {Object.entries(selectedCard.metrics_before).map(([key, val]) => (
                      <div key={key} className="flex items-center justify-between text-xs">
                        <span className="text-gray-600">{key}</span>
                        <span className="font-mono font-medium text-gray-900">{typeof val === 'number' ? val.toFixed(4) : val}</span>
                      </div>
                    ))}
                  </div>
                </div>
                <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                  <h4 className="mb-2 flex items-center gap-1.5 text-xs font-medium text-gray-500">
                    <TrendingUp className="h-3 w-3" />
                    Metrics After
                  </h4>
                  <div className="space-y-1">
                    {Object.entries(selectedCard.metrics_after).map(([key, val]) => (
                      <div key={key} className="flex items-center justify-between text-xs">
                        <span className="text-gray-600">{key}</span>
                        <span className="font-mono font-medium text-gray-900">{typeof val === 'number' ? val.toFixed(4) : val}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* Rollout plan */}
              {selectedCard.rollout_plan && (
                <div className="mb-4 rounded-lg border border-gray-200 bg-gray-50 p-3">
                  <h4 className="text-xs font-medium text-gray-500">Rollout Plan</h4>
                  <p className="mt-1 text-sm text-gray-700">{selectedCard.rollout_plan}</p>
                </div>
              )}

              {/* Diff hunks */}
              <div>
                <h4 className="mb-2 text-xs font-medium text-gray-500">
                  Diff Hunks ({selectedCard.diff_hunks.length})
                </h4>
                <div className="space-y-3">
                  {selectedCard.diff_hunks.map((hunk, i) => (
                    <HunkViewer key={i} hunk={hunk} index={i} />
                  ))}
                </div>
              </div>
            </section>
          )}

          {/* All changes (non-pending) */}
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
