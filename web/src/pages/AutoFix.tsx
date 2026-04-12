import { Bot, WandSparkles } from 'lucide-react';
import { PageHeader } from '../components/PageHeader';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { EmptyState } from '../components/EmptyState';
import { StatusBadge } from '../components/StatusBadge';
import { useApplyAutoFix, useAutoFixHistory, useAutoFixProposals, useRejectAutoFix, useSuggestAutoFix } from '../lib/api';
import { toastError, toastInfo, toastSuccess } from '../lib/toast';
import { formatTimestamp, statusLabel, statusVariant } from '../lib/utils';

function formatPercent(value: number): string {
  return `${(value * 100).toFixed(2)}%`;
}

export function AutoFix() {
  const proposalsQuery = useAutoFixProposals(100);
  const historyQuery = useAutoFixHistory(50);
  const suggestMutation = useSuggestAutoFix();
  const applyMutation = useApplyAutoFix();
  const rejectMutation = useRejectAutoFix();

  function handleSuggest() {
    suggestMutation.mutate(undefined, {
      onSuccess: (result) => {
        const count = result.proposals?.length || 0;
        if (count > 0) {
          toastSuccess('AutoFix suggestions ready', `${count} proposal(s) generated.`);
        } else {
          toastInfo('AutoFix suggestions complete', 'No new proposals generated.');
        }
        proposalsQuery.refetch();
      },
      onError: (error) => {
        toastError('AutoFix suggest failed', error.message);
      },
    });
  }

  function handleApply(proposalId: string) {
    applyMutation.mutate(
      { proposal_id: proposalId },
      {
        onSuccess: (outcome) => {
          toastSuccess('Proposal applied', outcome.message || 'Config mutation applied. Run eval to validate, then deploy via canary.');
          proposalsQuery.refetch();
          historyQuery.refetch();
        },
        onError: (error) => {
          toastError('AutoFix apply failed', error.message);
        },
      }
    );
  }

  function handleReject(proposalId: string) {
    rejectMutation.mutate(
      { proposal_id: proposalId },
      {
        onSuccess: (outcome) => {
          toastInfo('AutoFix proposal rejected', outcome.message);
          proposalsQuery.refetch();
          historyQuery.refetch();
        },
        onError: (error) => {
          toastError('AutoFix reject failed', error.message);
        },
      }
    );
  }

  if (proposalsQuery.isLoading || historyQuery.isLoading) {
    return (
      <div className="space-y-4">
        <LoadingSkeleton rows={5} />
        <LoadingSkeleton rows={6} />
      </div>
    );
  }

  const proposals = proposalsQuery.data || [];
  const history = historyQuery.data || [];
  const actionableStatuses = new Set(['pending', 'suggested', 'evaluated']);

  return (
    <div className="space-y-6">
      <PageHeader
        title="AutoFix Copilot"
        description="Generate constrained, one-step improvement proposals with diff previews. Apply proposals, then run eval and deploy separately."
        actions={
          <button
            onClick={handleSuggest}
            disabled={suggestMutation.isPending}
            className="inline-flex items-center gap-2 rounded-lg bg-gray-900 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-gray-800 disabled:opacity-60"
          >
            <WandSparkles className="h-4 w-4" />
            {suggestMutation.isPending ? 'Generating...' : 'Suggest Proposals'}
          </button>
        }
      />

      {proposalsQuery.isError && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          Unable to load AutoFix proposals. Generate a fresh batch or retry the API.
        </div>
      )}

      {historyQuery.isError && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          Unable to load AutoFix history. Recent apply outcomes may be stale.
        </div>
      )}

      {proposals.length === 0 ? (
        <EmptyState
          icon={Bot}
          title="No AutoFix proposals"
          description="Generate proposals to review low-risk, typed mutations before any apply action."
          actionLabel="Generate proposals"
          onAction={handleSuggest}
        />
      ) : (
        <section className="rounded-lg border border-gray-200 bg-white p-5">
          <h3 className="mb-4 text-sm font-semibold text-gray-900">Proposals</h3>
          <div className="space-y-3">
            {proposals.map((proposal) => {
              const canReview = actionableStatuses.has(proposal.status);
              const applyDisabled = applyMutation.isPending || rejectMutation.isPending || !canReview;
              const rejectDisabled = applyMutation.isPending || rejectMutation.isPending || !canReview;
              return (
                <div key={proposal.proposal_id} className="rounded-lg border border-gray-200 bg-gray-50 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <p className="font-mono text-xs text-gray-600">{proposal.proposal_id}</p>
                      <p className="mt-1 text-sm font-medium text-gray-900">{proposal.operator_name}</p>
                    </div>
                    <StatusBadge variant={statusVariant(proposal.status)} label={statusLabel(proposal.status)} />
                  </div>

                  <div className="mt-3 grid gap-2 text-xs text-gray-600 sm:grid-cols-2 lg:grid-cols-4">
                    <p>Risk: <span className="font-medium text-gray-900">{proposal.risk_class}</span></p>
                    <p>Lift: <span className="font-medium text-gray-900">{formatPercent(proposal.expected_lift)}</span></p>
                    <p>Cost impact: <span className="font-medium text-gray-900">{proposal.cost_impact_estimate.toFixed(4)}</span></p>
                    <p>Created: <span className="font-medium text-gray-900">{formatTimestamp(proposal.created_at)}</span></p>
                  </div>

                  {proposal.affected_eval_slices.length > 0 && (
                    <p className="mt-2 text-xs text-gray-600">
                      Slices: <span className="font-medium text-gray-900">{proposal.affected_eval_slices.join(', ')}</span>
                    </p>
                  )}

                  {proposal.rationale && (
                    <p className="mt-2 text-sm text-gray-700">{proposal.rationale}</p>
                  )}

                  <pre className="mt-3 overflow-x-auto rounded-md border border-gray-200 bg-white p-2 text-[11px] text-gray-700">
                    {proposal.diff_preview}
                  </pre>

                  <div className="mt-3 flex justify-end gap-2">
                    <button
                      onClick={() => handleReject(proposal.proposal_id)}
                      disabled={rejectDisabled}
                      className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 transition hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {rejectMutation.isPending ? 'Rejecting...' : 'Reject proposal'}
                    </button>
                    <button
                      onClick={() => handleApply(proposal.proposal_id)}
                      disabled={applyDisabled}
                      className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 transition hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {applyMutation.isPending ? 'Applying...' : 'Apply Proposal'}
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      )}

      <section className="rounded-lg border border-gray-200 bg-white p-5">
        <h3 className="mb-4 text-sm font-semibold text-gray-900">Apply History</h3>
        {history.length === 0 ? (
          <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50 p-4 text-sm text-gray-500">
            No apply history yet.
          </div>
        ) : (
          <div className="space-y-2">
            {history.map((entry) => (
              <div key={entry.history_id} className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="font-mono text-xs text-gray-600">{entry.proposal_id}</p>
                  <StatusBadge variant={statusVariant(entry.status)} label={statusLabel(entry.status)} />
                </div>
                <p className="mt-2 text-sm text-gray-700">{entry.message}</p>
                <p className="mt-1 text-xs text-gray-500">
                  {formatTimestamp(entry.applied_at)} · {entry.baseline_composite.toFixed(4)} → {entry.candidate_composite.toFixed(4)} · p={entry.significance_p_value.toFixed(4)}
                </p>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
