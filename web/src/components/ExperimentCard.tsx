import { useState } from 'react';
import { ChevronRight } from 'lucide-react';
import type { ExperimentCard as ExperimentCardType, ArchiveRole } from '../lib/types';
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

// ---------------------------------------------------------------------------
// Archive role badge
// ---------------------------------------------------------------------------

const ROLE_COLORS: Record<ArchiveRole, string> = {
  quality_leader: 'bg-blue-50 text-blue-700',
  cost_leader: 'bg-green-50 text-green-700',
  latency_leader: 'bg-purple-50 text-purple-700',
  safety_leader: 'bg-red-50 text-red-700',
  cluster_specialist: 'bg-gray-100 text-gray-700',
  incumbent: 'bg-amber-50 text-amber-700',
};

const ROLE_LABELS: Record<ArchiveRole, string> = {
  quality_leader: 'Quality Leader',
  cost_leader: 'Cost Leader',
  latency_leader: 'Latency Leader',
  safety_leader: 'Safety Leader',
  cluster_specialist: 'Specialist',
  incumbent: 'Incumbent',
};

function ArchiveRoleBadge({ role }: { role: ArchiveRole }) {
  return (
    <span className={classNames('rounded-md px-2 py-0.5 text-[11px] font-medium', ROLE_COLORS[role])}>
      {ROLE_LABELS[role]}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Extended metadata type for evidence / failures / archive
// ---------------------------------------------------------------------------

interface ExperimentMetadata {
  evidence_spans?: string[];
  failure_reasons?: string[];
  archive_role?: ArchiveRole;
}

function getMetadata(experiment: ExperimentCardType): ExperimentMetadata {
  const raw = experiment as Record<string, unknown>;
  return {
    evidence_spans: Array.isArray(raw.evidence_spans) ? raw.evidence_spans as string[] : undefined,
    failure_reasons: Array.isArray(raw.failure_reasons) ? raw.failure_reasons as string[] : undefined,
    archive_role: typeof raw.archive_role === 'string' ? raw.archive_role as ArchiveRole : undefined,
  };
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function ExperimentCardComponent({ experiment }: ExperimentCardProps) {
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const meta = getMetadata(experiment);

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
            {meta.archive_role && <ArchiveRoleBadge role={meta.archive_role} />}
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

      {/* Failure reasons */}
      {meta.failure_reasons && meta.failure_reasons.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {meta.failure_reasons.map((reason, idx) => (
            <span
              key={idx}
              className="rounded-md bg-red-50 px-2 py-0.5 text-[11px] font-medium text-red-700"
            >
              {reason}
            </span>
          ))}
        </div>
      )}

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

      {/* Evidence spans (collapsible) */}
      {meta.evidence_spans && meta.evidence_spans.length > 0 && (
        <div className="mt-3 border-t border-gray-100 pt-3">
          <button
            onClick={() => setEvidenceOpen(!evidenceOpen)}
            className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-gray-500 hover:text-gray-700"
          >
            <ChevronRight
              className={classNames(
                'h-3 w-3 transition-transform',
                evidenceOpen ? 'rotate-90' : ''
              )}
            />
            Evidence ({meta.evidence_spans.length})
          </button>
          {evidenceOpen && (
            <div className="mt-2 space-y-1.5">
              {meta.evidence_spans.map((span, idx) => (
                <p
                  key={idx}
                  className="rounded-md bg-gray-50 px-3 py-2 text-xs text-gray-600 font-mono leading-relaxed"
                >
                  {span}
                </p>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
