import { useState } from 'react';
import {
  CheckCircle2,
  X,
  ChevronDown,
  ChevronRight,
  AlertTriangle,
  Zap,
  GitPullRequest,
  Inbox,
  Shield,
  TrendingUp,
} from 'lucide-react';
import { EmptyState } from '../components/EmptyState';
import { StatusBadge } from '../components/StatusBadge';
import {
  useUnifiedReviews,
  useApproveUnifiedReview,
  useRejectUnifiedReview,
  useChangeAudit,
  useVerifyImprovement,
} from '../lib/api';
import { classNames, formatTimestamp } from '../lib/utils';
import type { UnifiedReviewItem } from '../lib/types';

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

const riskColors: Record<string, string> = {
  low: 'bg-green-50 text-green-700 border-green-200',
  medium: 'bg-amber-50 text-amber-700 border-amber-200',
  high: 'bg-red-50 text-red-700 border-red-200',
};

const sourceLabels: Record<string, string> = {
  optimizer: 'Optimizer',
  change_card: 'Change Card',
};

const sourceColors: Record<string, string> = {
  optimizer: 'bg-indigo-50 text-indigo-700 border-indigo-200',
  change_card: 'bg-violet-50 text-violet-700 border-violet-200',
};

function formatDelta(delta: number): string {
  if (delta === 0) return '0.000';
  const sign = delta > 0 ? '+' : '';
  return `${sign}${delta.toFixed(3)}`;
}

function deltaColor(delta: number): string {
  if (delta > 0) return 'text-emerald-700';
  if (delta < 0) return 'text-rose-700';
  return 'text-amber-700';
}

// ---------------------------------------------------------------------------
// Inline diff viewer (lightweight, for unified diff text)
// ---------------------------------------------------------------------------

function InlineDiffViewer({ diff }: { diff: string }) {
  if (!diff.trim()) {
    return <p className="text-xs text-gray-400 italic">No diff available</p>;
  }

  return (
    <pre className="max-h-64 overflow-auto rounded-lg border border-gray-200 bg-gray-50 p-3 text-xs font-mono leading-5">
      {diff.split('\n').map((line, i) => {
        let lineClass = 'text-gray-600';
        if (line.startsWith('+')) lineClass = 'text-emerald-700 bg-emerald-50';
        else if (line.startsWith('-')) lineClass = 'text-rose-700 bg-rose-50';
        else if (line.startsWith('@@') || line.startsWith('---') || line.startsWith('+++'))
          lineClass = 'text-blue-600 font-medium';

        return (
          <div key={i} className={lineClass}>
            {line || '\u00a0'}
          </div>
        );
      })}
    </pre>
  );
}

// ---------------------------------------------------------------------------
// Change card audit detail (reused from ChangeReview)
// ---------------------------------------------------------------------------

function AuditDetail({ cardId }: { cardId: string }) {
  const { data: auditDetail } = useChangeAudit(cardId);

  if (!auditDetail) return null;

  return (
    <div className="mt-4 space-y-3">
      {auditDetail.gate_decisions.length > 0 && (
        <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
          <h5 className="text-xs font-medium text-gray-500">Gate results</h5>
          <div className="mt-2 space-y-1">
            {auditDetail.gate_decisions.map((gate) => (
              <div
                key={gate.gate}
                className="flex items-center justify-between rounded border border-gray-200 bg-white px-2 py-1 text-xs"
              >
                <span className="font-medium text-gray-700">{gate.gate}</span>
                <span className={gate.passed ? 'text-green-700' : 'text-red-700'}>
                  {gate.passed ? 'Passed' : 'Failed'} &middot; {gate.reason}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {Object.keys(auditDetail.composite_breakdown).length > 0 && (
        <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
          <h5 className="text-xs font-medium text-gray-500">Composite breakdown</h5>
          <div className="mt-2 space-y-1">
            {Object.entries(auditDetail.composite_breakdown).map(([metric, value]) => (
              <div key={metric} className="flex items-center justify-between text-xs">
                <span className="text-gray-600">{metric}</span>
                <span className={classNames('font-mono', value >= 0 ? 'text-green-700' : 'text-red-700')}>
                  {value > 0 ? '+' : ''}
                  {value.toFixed(4)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {auditDetail.timeline.length > 0 && (
        <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
          <h5 className="text-xs font-medium text-gray-500">Timeline</h5>
          <div className="mt-2 space-y-1">
            {auditDetail.timeline.map((item, idx) => (
              <div
                key={`${item.stage}-${idx}`}
                className="rounded border border-gray-200 bg-white px-2 py-1 text-xs text-gray-700"
              >
                <span className="font-semibold">{item.stage}</span> &middot; {item.detail}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Review item detail panel
// ---------------------------------------------------------------------------

function ReviewItemDetail({
  item,
  onApprove,
  onReject,
  onVerify,
  isApproving,
  isRejecting,
  isVerifying,
}: {
  item: UnifiedReviewItem;
  onApprove: () => void;
  onReject: (reason: string) => void;
  onVerify: (() => void) | null;
  isApproving: boolean;
  isRejecting: boolean;
  isVerifying: boolean;
}) {
  const [rejectReason, setRejectReason] = useState('');
  const [showRejectInput, setShowRejectInput] = useState(false);
  const verificationPassed =
    item.source !== 'optimizer' ||
    (item.verification?.status === 'passed' && item.verification?.phase === 'pre_deploy');

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
      {/* Header */}
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="max-w-2xl">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge variant="pending" label="pending review" />
            <span
              className={classNames(
                'inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] font-medium',
                sourceColors[item.source] ?? 'bg-gray-50 text-gray-600 border-gray-200'
              )}
            >
              {item.source === 'optimizer' ? (
                <Zap className="h-3 w-3" />
              ) : (
                <GitPullRequest className="h-3 w-3" />
              )}
              {sourceLabels[item.source] ?? item.source}
            </span>
            <span
              className={classNames(
                'inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] font-medium',
                riskColors[item.risk_class] ?? 'bg-gray-50 text-gray-600 border-gray-200'
              )}
            >
              <AlertTriangle className="h-3 w-3" />
              {item.risk_class} risk
            </span>
            {item.strategy && (
              <span className="rounded-md border border-gray-200 bg-gray-50 px-2 py-0.5 text-[11px] font-medium text-gray-600">
                {item.strategy}
              </span>
            )}
            {item.operator_family && (
              <span className="rounded-md border border-gray-200 bg-gray-50 px-2 py-0.5 text-[11px] font-medium text-gray-600">
                {item.operator_family}
              </span>
            )}
          </div>
          <h4 className="mt-3 text-base font-semibold text-gray-900">{item.title}</h4>
          <p className="mt-1.5 text-sm leading-relaxed text-gray-600">{item.description}</p>
          <p className="mt-1.5 text-xs text-gray-400">{formatTimestamp(item.created_at)}</p>
        </div>

        {/* Scores */}
        <div className="grid gap-2 sm:grid-cols-3 lg:min-w-[300px]">
          <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-center">
            <p className="text-[10px] font-medium uppercase tracking-wider text-gray-400">Before</p>
            <p className="mt-1 text-lg font-semibold text-gray-900">
              {(item.score_before * 100).toFixed(1)}%
            </p>
          </div>
          <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-center">
            <p className="text-[10px] font-medium uppercase tracking-wider text-gray-400">After</p>
            <p className="mt-1 text-lg font-semibold text-gray-900">
              {(item.score_after * 100).toFixed(1)}%
            </p>
          </div>
          <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-center">
            <p className="text-[10px] font-medium uppercase tracking-wider text-gray-400">Delta</p>
            <p className={classNames('mt-1 text-lg font-semibold', deltaColor(item.score_delta))}>
              {formatDelta(item.score_delta * 100)}%
            </p>
          </div>
        </div>
      </div>

      {/* Diff */}
      <div className="mt-5">
        <h5 className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-gray-900">
          <TrendingUp className="h-3.5 w-3.5 text-gray-400" />
          Config diff
        </h5>
        <InlineDiffViewer diff={item.diff_summary} />
      </div>

      {/* Audit trail for change cards */}
      {item.has_detailed_audit && <AuditDetail cardId={item.id} />}

      {item.source === 'optimizer' && (
        <div className="mt-4 rounded-lg border border-sky-200 bg-sky-50 p-3">
          <div className="flex items-center gap-2">
            <Shield className="h-4 w-4 text-sky-700" />
            <p className="text-xs font-semibold uppercase tracking-wide text-sky-800">Verification</p>
          </div>
          {item.verification ? (
            <div className="mt-2 space-y-1 text-sm text-sky-900">
              <p className="font-medium">
                {item.verification.status === 'passed' ? 'Passed' : 'Failed'}
                {item.verification.phase ? ` · ${item.verification.phase.replace('_', ' ')}` : ''}
              </p>
              {item.verification.eval_run_id ? (
                <p className="font-mono text-xs text-sky-800">{item.verification.eval_run_id}</p>
              ) : null}
              {typeof item.verification.composite_delta === 'number' ? (
                <p className="text-xs text-sky-800">
                  Composite delta {formatDelta(item.verification.composite_delta * 100)}%
                </p>
              ) : null}
            </div>
          ) : (
            <p className="mt-2 text-sm text-sky-900">
              Run verification before approving this optimizer proposal for deployment.
            </p>
          )}
        </div>
      )}

      {/* Reject input */}
      {showRejectInput && (
        <div className="mt-4 flex items-center gap-2 rounded-lg border border-rose-200 bg-rose-50 p-3">
          <input
            type="text"
            placeholder="Rejection reason..."
            aria-label="Rejection reason"
            value={rejectReason}
            onChange={(e) => setRejectReason(e.target.value)}
            className="flex-1 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm focus:border-rose-500 focus:outline-none"
          />
          <button
            onClick={() => {
              onReject(rejectReason);
              setRejectReason('');
              setShowRejectInput(false);
            }}
            disabled={isRejecting || !rejectReason.trim()}
            className="rounded-md bg-rose-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-rose-700 disabled:opacity-60"
          >
            {isRejecting ? 'Rejecting...' : 'Confirm'}
          </button>
        </div>
      )}

      {/* Action buttons */}
      <div className="mt-4 flex flex-wrap gap-2">
        {item.source === 'optimizer' && onVerify ? (
          <button
            type="button"
            onClick={onVerify}
            disabled={isVerifying}
            className="inline-flex items-center gap-2 rounded-lg border border-sky-200 bg-white px-4 py-2 text-sm font-medium text-sky-800 transition hover:bg-sky-50 disabled:opacity-60"
          >
            <Shield className="h-4 w-4" />
            {isVerifying
              ? 'Verifying...'
              : item.verification?.status === 'passed'
                ? 'Verify again'
                : item.verification?.status === 'failed'
                  ? 'Re-verify candidate'
                  : 'Verify candidate'}
          </button>
        ) : null}
        <button
          type="button"
          onClick={onApprove}
          disabled={isApproving || !verificationPassed}
          title={
            !verificationPassed
              ? 'Run verification before approving this optimizer proposal'
              : undefined
          }
          className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-emerald-700 disabled:opacity-60"
        >
          <CheckCircle2 className="h-4 w-4" />
          {isApproving
            ? 'Approving...'
            : item.source === 'optimizer'
              ? 'Approve & Deploy'
              : 'Apply'}
        </button>
        <button
          type="button"
          onClick={() => setShowRejectInput(!showRejectInput)}
          disabled={isRejecting}
          className="inline-flex items-center gap-2 rounded-lg border border-rose-200 bg-white px-4 py-2 text-sm font-medium text-rose-700 transition hover:bg-rose-50 disabled:opacity-60"
        >
          <X className="h-4 w-4" />
          Reject
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface UnifiedReviewQueueProps {
  embedded?: boolean;
}

export function UnifiedReviewQueue({ embedded = false }: UnifiedReviewQueueProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const { data: items = [], isLoading, isError } = useUnifiedReviews();
  const approveMutation = useApproveUnifiedReview();
  const rejectMutation = useRejectUnifiedReview();
  const verifyMutation = useVerifyImprovement();

  const pendingItems = items.filter((item) => item.status === 'pending');
  const optimizerCount = pendingItems.filter((item) => item.source === 'optimizer').length;
  const changeCardCount = pendingItems.filter((item) => item.source === 'change_card').length;

  const expandedItem = pendingItems.find((item) => item.id === expandedId) ?? null;

  function handleApprove(item: UnifiedReviewItem) {
    approveMutation.mutate(
      { id: item.id, source: item.source },
      {
        onSuccess: () => {
          setExpandedId(null);
        },
      }
    );
  }

  function handleReject(item: UnifiedReviewItem, reason: string) {
    rejectMutation.mutate(
      { id: item.id, source: item.source, reason },
      {
        onSuccess: () => {
          setExpandedId(null);
        },
      }
    );
  }

  function handleVerify(item: UnifiedReviewItem) {
    if (item.source !== 'optimizer') {
      return;
    }
    verifyMutation.mutate({ attemptId: item.id });
  }

  return (
    <div
      aria-label={embedded ? 'Embedded unified review queue' : 'Unified review queue'}
      className="space-y-5"
    >
      {/* Summary stats */}
      <section className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <p className="text-xs text-gray-500">Pending review</p>
          <p className="mt-1 text-2xl font-semibold text-gray-900">{pendingItems.length}</p>
        </div>
        <div className="rounded-lg border border-indigo-100 bg-indigo-50/50 p-4">
          <div className="flex items-center gap-1.5">
            <Zap className="h-3.5 w-3.5 text-indigo-500" />
            <p className="text-xs text-indigo-600">Optimizer proposals</p>
          </div>
          <p className="mt-1 text-2xl font-semibold text-indigo-900">{optimizerCount}</p>
        </div>
        <div className="rounded-lg border border-violet-100 bg-violet-50/50 p-4">
          <div className="flex items-center gap-1.5">
            <GitPullRequest className="h-3.5 w-3.5 text-violet-500" />
            <p className="text-xs text-violet-600">Change cards</p>
          </div>
          <p className="mt-1 text-2xl font-semibold text-violet-900">{changeCardCount}</p>
        </div>
      </section>

      {/* Loading / error states */}
      {isLoading && (
        <div className="flex h-32 items-center justify-center rounded-xl border border-dashed border-gray-200 bg-gray-50 text-sm text-gray-500">
          Loading pending reviews...
        </div>
      )}
      {isError && (
        <div className="flex h-32 items-center justify-center rounded-xl border border-dashed border-red-200 bg-red-50 text-sm text-red-600">
          Failed to load reviews. The unified review endpoint may not be available.
        </div>
      )}

      {/* Empty state */}
      {!isLoading && !isError && pendingItems.length === 0 && (
        <EmptyState
          icon={Inbox}
          title="No pending reviews"
          description="All proposals have been reviewed. Run an optimization cycle or let the continuous loop propose improvements to see new items here."
          cliHint="agentlab optimize --cycles 1"
        />
      )}

      {/* Pending items list */}
      {!isLoading && !isError && pendingItems.length > 0 && (
        <section className="rounded-xl border border-amber-200 bg-amber-50/40 p-5">
          <div className="mb-4">
            <div className="flex items-center gap-2">
              <Shield className="h-4 w-4 text-amber-700" />
              <h3 className="text-sm font-semibold text-gray-900">
                Pending Reviews ({pendingItems.length})
              </h3>
            </div>
            <p className="mt-1 text-sm text-gray-600">
              These proposals passed evaluation gates and are waiting for your decision.
              {optimizerCount > 0 && changeCardCount > 0 && (
                <span className="ml-1 text-gray-500">
                  Showing items from both the optimizer pipeline and the change card pipeline.
                </span>
              )}
            </p>
          </div>

          <div className="space-y-2">
            {pendingItems.map((item) => (
              <button
                key={`${item.source}-${item.id}`}
                type="button"
                aria-expanded={expandedId === item.id}
                onClick={() => setExpandedId(expandedId === item.id ? null : item.id)}
                className={classNames(
                  'flex w-full items-center gap-3 rounded-lg border px-4 py-3 text-left transition-colors',
                  expandedId === item.id
                    ? 'border-amber-300 bg-white shadow-sm'
                    : 'border-amber-200 bg-white/70 hover:bg-white hover:shadow-sm'
                )}
              >
                {expandedId === item.id ? (
                  <ChevronDown className="h-4 w-4 shrink-0 text-amber-600" />
                ) : (
                  <ChevronRight className="h-4 w-4 shrink-0 text-gray-400" />
                )}
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <p className="truncate text-sm font-medium text-gray-900">{item.title}</p>
                  </div>
                  <p className="mt-0.5 truncate text-xs text-gray-500">{item.description}</p>
                </div>
                <span
                  className={classNames(
                    'inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[10px] font-medium',
                    sourceColors[item.source] ?? 'bg-gray-50 text-gray-600 border-gray-200'
                  )}
                >
                  {item.source === 'optimizer' ? (
                    <Zap className="h-2.5 w-2.5" />
                  ) : (
                    <GitPullRequest className="h-2.5 w-2.5" />
                  )}
                  {sourceLabels[item.source] ?? item.source}
                </span>
                <span
                  className={classNames(
                    'rounded-md border px-2 py-0.5 text-[10px] font-medium',
                    riskColors[item.risk_class] ?? 'bg-gray-50 text-gray-600 border-gray-200'
                  )}
                >
                  {item.risk_class}
                </span>
                <span className={classNames('font-mono text-xs font-medium', deltaColor(item.score_delta))}>
                  {formatDelta(item.score_delta * 100)}%
                </span>
              </button>
            ))}
          </div>
        </section>
      )}

      {/* Expanded detail */}
      {expandedItem && (
        <ReviewItemDetail
          item={expandedItem}
          onApprove={() => handleApprove(expandedItem)}
          onReject={(reason) => handleReject(expandedItem, reason)}
          onVerify={expandedItem.source === 'optimizer' ? () => handleVerify(expandedItem) : null}
          isApproving={approveMutation.isPending}
          isRejecting={rejectMutation.isPending}
          isVerifying={verifyMutation.isPending}
        />
      )}
    </div>
  );
}
