import { useNavigate } from 'react-router-dom';
import { PageHeader } from '../components/PageHeader';
import { OpportunityItem } from '../components/OpportunityItem';
import { useOpportunities } from '../lib/api';

interface OpportunitiesProps {
  embedded?: boolean;
}

export function Opportunities({ embedded = false }: OpportunitiesProps) {
  const navigate = useNavigate();
  const { data: opportunities = [], isLoading, isError } = useOpportunities('open');

  const sorted = [...opportunities].sort((a, b) => b.priority_score - a.priority_score);

  const counts = {
    open: opportunities.filter((o) => o.status === 'open').length,
    in_progress: opportunities.filter((o) => o.status === 'in_progress').length,
    resolved: opportunities.filter((o) => o.status === 'resolved').length,
  };

  return (
    <div className="space-y-6">
      {!embedded && (
        <PageHeader
          title="Opportunity Queue"
          description="Ranked optimization opportunities from failure analysis"
        />
      )}

      {/* Summary bar */}
      <div className="flex items-center gap-4 rounded-xl border border-gray-200 bg-white px-5 py-3">
        <div className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full bg-amber-400" />
          <span className="text-sm text-gray-700">
            <span className="font-semibold tabular-nums">{counts.open}</span> open opportunities
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
            <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-gray-200 bg-gray-50 px-4 py-8 text-center text-sm text-gray-500">
              <p>No open opportunities. Run an eval or optimization cycle to surface failure clusters.</p>
              <button
                onClick={() => navigate('/optimize')}
                className="rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-gray-800"
              >
                Run Optimization
              </button>
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
