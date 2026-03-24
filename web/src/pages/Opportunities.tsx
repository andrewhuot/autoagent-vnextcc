import { PageHeader } from '../components/PageHeader';
import { OpportunityItem } from '../components/OpportunityItem';
import type { OptimizationOpportunity } from '../lib/types';

const mockOpportunities: OptimizationOpportunity[] = [
  {
    opportunity_id: 'opp_001',
    failure_family: 'tool_error',
    affected_agent_path: 'root/orders',
    severity: 0.8,
    prevalence: 0.6,
    recency: 0.9,
    business_impact: 0.7,
    priority_score: 0.75,
    status: 'open',
    recommended_operator_families: ['tool_description_edit'],
    sample_trace_ids: ['t1', 't2'],
  },
  {
    opportunity_id: 'opp_002',
    failure_family: 'quality_degradation',
    affected_agent_path: 'root/support',
    severity: 0.5,
    prevalence: 0.4,
    recency: 0.7,
    business_impact: 0.5,
    priority_score: 0.52,
    status: 'open',
    recommended_operator_families: ['instruction_rewrite', 'few_shot_edit'],
    sample_trace_ids: ['t3'],
  },
  {
    opportunity_id: 'opp_003',
    failure_family: 'latency_spike',
    affected_agent_path: 'root',
    severity: 0.3,
    prevalence: 0.2,
    recency: 0.5,
    business_impact: 0.3,
    priority_score: 0.32,
    status: 'resolved',
    recommended_operator_families: ['generation_settings'],
    sample_trace_ids: [],
  },
];

export function Opportunities() {
  const sorted = [...mockOpportunities].sort((a, b) => b.priority_score - a.priority_score);

  const counts = {
    open: mockOpportunities.filter((o) => o.status === 'open').length,
    in_progress: mockOpportunities.filter((o) => o.status === 'in_progress').length,
    resolved: mockOpportunities.filter((o) => o.status === 'resolved').length,
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

      {/* Opportunity list */}
      <div className="space-y-2">
        {sorted.map((opportunity) => (
          <OpportunityItem key={opportunity.opportunity_id} opportunity={opportunity} />
        ))}
      </div>
    </div>
  );
}
