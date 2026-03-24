import type { ExperimentCard as ExperimentCardType } from '../lib/types';
import { StatusBadge } from './StatusBadge';
import { classNames } from '../lib/utils';

interface ExperimentCardProps {
  experiment: ExperimentCardType;
}

function statusVariant(status: string): 'success' | 'error' | 'warning' {
  if (status === 'accepted') return 'success';
  if (status === 'rejected') return 'error';
  return 'warning';
}

function riskColor(risk: string): string {
  if (risk === 'high') return 'bg-red-50 text-red-700';
  if (risk === 'medium') return 'bg-amber-50 text-amber-700';
  return 'bg-green-50 text-green-700';
}

function ScoreBar({ label, value, max = 1 }: { label: string; value: number; max?: number }) {
  const pct = Math.round((value / max) * 100);
  return (
    <div className="flex items-center gap-2">
      <span className="w-16 text-[11px] text-gray-500">{label}</span>
      <div className="h-2 flex-1 overflow-hidden rounded-full bg-gray-100">
        <div
          className="h-full rounded-full bg-gray-600"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="w-10 text-right text-[11px] tabular-nums text-gray-600">
        {value.toFixed(2)}
      </span>
    </div>
  );
}

function formatAge(epochSeconds: number): string {
  const delta = Math.floor(Date.now() / 1000 - epochSeconds);
  if (delta < 60) return `${delta}s ago`;
  if (delta < 3600) return `${Math.floor(delta / 60)}m ago`;
  if (delta < 86400) return `${Math.floor(delta / 3600)}h ago`;
  return `${Math.floor(delta / 86400)}d ago`;
}

export function ExperimentCardComponent({ experiment }: ExperimentCardProps) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5 transition-colors hover:border-gray-300">
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs text-gray-500">{experiment.experiment_id}</span>
            <StatusBadge
              variant={statusVariant(experiment.status)}
              label={experiment.status}
            />
          </div>
          <p className="mt-2 text-sm font-medium text-gray-900">{experiment.hypothesis}</p>
        </div>
      </div>

      {/* Meta row */}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <span className="rounded-md bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-600">
          {experiment.operator_name.replaceAll('_', ' ')}
        </span>
        <span className={classNames('rounded-md px-2 py-0.5 text-[11px] font-medium', riskColor(experiment.risk_class))}>
          {experiment.risk_class} risk
        </span>
        {experiment.touched_surfaces.map((surface) => (
          <span
            key={surface}
            className="rounded-md bg-blue-50 px-2 py-0.5 text-[11px] font-medium text-blue-700"
          >
            {surface}
          </span>
        ))}
        <span className="ml-auto text-[11px] text-gray-400">{formatAge(experiment.created_at)}</span>
      </div>

      {/* Score comparison */}
      <div className="mt-4 space-y-2">
        <p className="text-[11px] font-medium uppercase tracking-wide text-gray-500">Score Comparison</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <p className="text-[11px] text-gray-400">Baseline</p>
            <ScoreBar label="Composite" value={experiment.baseline_scores.composite} />
            {experiment.baseline_scores.quality !== undefined && (
              <ScoreBar label="Quality" value={experiment.baseline_scores.quality} />
            )}
            {experiment.baseline_scores.safety !== undefined && (
              <ScoreBar label="Safety" value={experiment.baseline_scores.safety} />
            )}
          </div>
          <div className="space-y-1.5">
            <p className="text-[11px] text-gray-400">Candidate</p>
            <ScoreBar label="Composite" value={experiment.candidate_scores.composite} />
            {experiment.candidate_scores.quality !== undefined && (
              <ScoreBar label="Quality" value={experiment.candidate_scores.quality} />
            )}
            {experiment.candidate_scores.safety !== undefined && (
              <ScoreBar label="Safety" value={experiment.candidate_scores.safety} />
            )}
          </div>
        </div>
      </div>

      {/* Significance + deployment */}
      <div className="mt-4 flex items-center justify-between border-t border-gray-100 pt-3">
        <div className="flex items-center gap-4 text-xs text-gray-600">
          <span>
            Delta:{' '}
            <span
              className={classNames(
                'font-medium tabular-nums',
                experiment.significance_delta > 0 ? 'text-green-600' : experiment.significance_delta < 0 ? 'text-red-600' : 'text-gray-500'
              )}
            >
              {experiment.significance_delta > 0 ? '+' : ''}
              {experiment.significance_delta.toFixed(3)}
            </span>
          </span>
          <span>
            p-value:{' '}
            <span className="font-medium tabular-nums">{experiment.significance_p_value.toFixed(3)}</span>
          </span>
        </div>
        <span className="rounded-md bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-600">
          {experiment.deployment_policy}
        </span>
      </div>
    </div>
  );
}
