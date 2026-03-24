import type { OptimizationOpportunity } from '../lib/types';
import { StatusBadge } from './StatusBadge';
import { classNames } from '../lib/utils';

interface OpportunityItemProps {
  opportunity: OptimizationOpportunity;
}

function priorityColor(score: number): string {
  if (score > 0.7) return 'bg-red-500 text-white';
  if (score > 0.4) return 'bg-amber-400 text-amber-900';
  return 'bg-gray-200 text-gray-600';
}

function statusVariant(status: string): 'success' | 'warning' | 'pending' {
  if (status === 'resolved') return 'success';
  if (status === 'in_progress') return 'warning';
  return 'pending';
}

function MiniBar({ value, label }: { value: number; label: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="w-14 text-[11px] text-gray-500">{label}</span>
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-gray-100">
        <div
          className="h-full rounded-full bg-gray-400"
          style={{ width: `${Math.round(value * 100)}%` }}
        />
      </div>
    </div>
  );
}

export function OpportunityItem({ opportunity }: OpportunityItemProps) {
  return (
    <div className="flex items-center gap-4 rounded-xl border border-gray-200 bg-white px-4 py-3 transition-colors hover:bg-gray-50">
      {/* Priority score circle */}
      <div
        className={classNames(
          'flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-sm font-semibold tabular-nums',
          priorityColor(opportunity.priority_score)
        )}
      >
        {opportunity.priority_score.toFixed(2)}
      </div>

      {/* Failure family + agent path */}
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-gray-900">{opportunity.failure_family.replaceAll('_', ' ')}</p>
        <p className="mt-0.5 truncate font-mono text-xs text-gray-500">{opportunity.affected_agent_path}</p>
      </div>

      {/* Severity bars */}
      <div className="hidden flex-col gap-1 md:flex">
        <MiniBar value={opportunity.severity} label="Severity" />
        <MiniBar value={opportunity.prevalence} label="Prevalence" />
        <MiniBar value={opportunity.recency} label="Recency" />
      </div>

      {/* Status */}
      <div className="shrink-0">
        <StatusBadge variant={statusVariant(opportunity.status)} label={opportunity.status.replaceAll('_', ' ')} />
      </div>

      {/* Recommended operators */}
      <div className="hidden shrink-0 flex-wrap gap-1 lg:flex">
        {opportunity.recommended_operator_families.map((op) => (
          <span
            key={op}
            className="rounded-md bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-600"
          >
            {op.replaceAll('_', ' ')}
          </span>
        ))}
      </div>
    </div>
  );
}
