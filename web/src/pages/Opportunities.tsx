import { PageHeader } from '../components/PageHeader';
import { OpportunityItem } from '../components/OpportunityItem';
import { useOpportunities } from '../lib/api';

export function Opportunities() {
  const { data: opportunities = [], isLoading, isError } = useOpportunities('open');

  const sorted = [...opportunities].sort((a, b) => b.priority_score - a.priority_score);

  const counts = {
    open: opportunities.filter((o) => o.status === 'open').length,
    in_progress: opportunities.filter((o) => o.status === 'in_progress').length,
    resolved: opportunities.filter((o) => o.status === 'resolved').length,
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Opportunity Queue"
        description="Ranked optimization opportunities from failure analysis"
      />

      {/* Summary bar */}
      <div className="flex items-center gap-4 rounded-xl border border-gray-200 bg-white px-5 py-3">
        <div className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full bg-amber-400" />
          <span className="text-sm text-gray-700">
            <span className="font-semibold tabular-nums">{counts.open}</span> open
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full bg-blue-500" />
          <span className="text-sm text-gray-700">
            <span className="font-semibold tabular-nums">{counts.in_progress}</span> in progress
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full bg-green-500" />
          <span className="text-sm text-gray-700">
            <span className="font-semibold tabular-nums">{counts.resolved}</span> resolved
          </span>
        </div>
      </div>

      {/* Loading / error states */}
      {isLoading && (
        <div className="flex h-32 items-center justify-center rounded-xl border border-dashed border-gray-200 bg-gray-50 text-sm text-gray-500">
          Loading opportunities…
        </div>
      )}
      {isError && (
        <div className="flex h-32 items-center justify-center rounded-xl border border-dashed border-red-200 bg-red-50 text-sm text-red-600">
          Failed to load opportunities.
        </div>
      )}

      {/* Opportunity list */}
      {!isLoading && !isError && (
        <div className="space-y-2">
          {sorted.length === 0 ? (
            <div className="flex h-32 items-center justify-center rounded-xl border border-dashed border-gray-200 bg-gray-50 text-sm text-gray-500">
              No open opportunities.
            </div>
          ) : (
            sorted.map((opportunity) => (
              <OpportunityItem key={opportunity.opportunity_id} opportunity={opportunity} />
            ))
          )}
        </div>
      )}
    </div>
  );
}
