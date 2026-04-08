import {
  CheckCircle2,
  AlertTriangle,
  Info,
  XCircle,
  ShieldCheck,
  Eye,
  Lock,
  Ban,
  GitFork,
  ArrowRight,
} from 'lucide-react';
import type { PortabilityReport, PortabilitySurface } from '../lib/types';

type UiVerdict = 'ready' | 'partial' | 'needs_work' | 'unsupported';
type UiSurfaceStatus = 'full' | 'partial' | 'read_only' | 'unsupported';
type UiWarningSeverity = 'info' | 'warning' | 'critical';

interface UiWarning {
  severity: UiWarningSeverity;
  category: string;
  message: string;
  recommendation: string;
}

interface UiSurfaceRow {
  name: string;
  status: UiSurfaceStatus;
  detail: string;
  item_count?: number;
  optimizable_count?: number;
}

const VERDICT_CONFIG: Record<
  UiVerdict,
  { label: string; color: string; bg: string; border: string; icon: typeof CheckCircle2 }
> = {
  ready: {
    label: 'Ready for optimization',
    color: 'text-green-700',
    bg: 'bg-green-50',
    border: 'border-green-200',
    icon: CheckCircle2,
  },
  partial: {
    label: 'Imported with gaps — review before optimizing',
    color: 'text-amber-700',
    bg: 'bg-amber-50',
    border: 'border-amber-200',
    icon: AlertTriangle,
  },
  needs_work: {
    label: 'Significant gaps — manual engineering may be needed',
    color: 'text-orange-700',
    bg: 'bg-orange-50',
    border: 'border-orange-200',
    icon: AlertTriangle,
  },
  unsupported: {
    label: 'Not well-suited for AgentLab optimization',
    color: 'text-red-700',
    bg: 'bg-red-50',
    border: 'border-red-200',
    icon: XCircle,
  },
};

const SURFACE_STATUS_CONFIG: Record<
  UiSurfaceStatus,
  { label: string; color: string; bg: string; icon: typeof CheckCircle2 }
> = {
  full: { label: 'Optimizable', color: 'text-green-700', bg: 'bg-green-100', icon: ShieldCheck },
  partial: { label: 'Partial', color: 'text-amber-700', bg: 'bg-amber-100', icon: Eye },
  read_only: { label: 'Read-only', color: 'text-blue-700', bg: 'bg-blue-100', icon: Lock },
  unsupported: { label: 'Unsupported', color: 'text-gray-500', bg: 'bg-gray-100', icon: Ban },
};

const SEVERITY_CONFIG: Record<UiWarningSeverity, { color: string; icon: typeof Info }> = {
  info: { color: 'text-blue-600', icon: Info },
  warning: { color: 'text-amber-600', icon: AlertTriangle },
  critical: { color: 'text-red-600', icon: XCircle },
};

function getNumericMetadata(surface: PortabilitySurface, key: string): number | undefined {
  const value = surface.metadata?.[key];
  return typeof value === 'number' ? value : undefined;
}

function deriveSurfaceStatus(surface: PortabilitySurface): UiSurfaceStatus {
  if (surface.portability_status === 'read_only' || surface.parity_status === 'read_only') {
    return 'read_only';
  }
  if (surface.portability_status === 'unsupported' || surface.parity_status === 'unsupported') {
    return 'unsupported';
  }
  if (
    surface.parity_status === 'partial' ||
    surface.coverage_status === 'partial' ||
    surface.coverage_status === 'referenced' ||
    surface.export_status === 'lossy'
  ) {
    return 'partial';
  }
  return 'full';
}

function deriveSurfaceRows(report: PortabilityReport): UiSurfaceRow[] {
  return report.surfaces.map((surface) => ({
    name: surface.label || surface.surface_id,
    status: deriveSurfaceStatus(surface),
    detail:
      surface.rationale[0] ||
      `${surface.coverage_status} import coverage • ${surface.export_status} export readiness`,
    item_count: getNumericMetadata(surface, 'item_count') ?? getNumericMetadata(surface, 'count'),
    optimizable_count: getNumericMetadata(surface, 'optimizable_count'),
  }));
}

function deriveVerdict(report: PortabilityReport): UiVerdict {
  const score = Math.round(report.optimization_eligibility.score);
  const unsupported = report.summary.unsupported_surfaces;
  const blockers = report.optimization_eligibility.blockers.length;

  if (score < 25 && unsupported > 0) return 'unsupported';
  if (score >= 80 && blockers === 0 && unsupported === 0) return 'ready';
  if (score >= 55) return 'partial';
  if (score >= 25 || blockers > 0) return 'needs_work';
  return 'unsupported';
}

function deriveWarnings(report: PortabilityReport): UiWarning[] {
  const warnings: UiWarning[] = [];

  for (const blocker of report.optimization_eligibility.blockers) {
    warnings.push({
      severity: 'critical',
      category: 'eligibility_blocker',
      message: blocker,
      recommendation: 'Review this surface before trusting optimization or export results.',
    });
  }

  for (const note of report.notes) {
    warnings.push({
      severity: 'warning',
      category: 'portability_note',
      message: note,
      recommendation: 'Inspect the import summary and surface matrix before optimizing.',
    });
  }

  if (report.summary.unsupported_surfaces > 0) {
    warnings.push({
      severity: 'warning',
      category: 'unsupported_surfaces',
      message: `${report.summary.unsupported_surfaces} surface${report.summary.unsupported_surfaces !== 1 ? 's are' : ' is'} currently unsupported.`,
      recommendation: 'Treat unsupported surfaces as manual engineering work, not safe optimization targets.',
    });
  }

  if (report.summary.blocked_export_surfaces > 0) {
    warnings.push({
      severity: 'critical',
      category: 'export_blockers',
      message: `${report.summary.blocked_export_surfaces} surface${report.summary.blocked_export_surfaces !== 1 ? 's are' : ' is'} blocked from safe round-trip export.`,
      recommendation: 'Review export blockers before planning production pushback.',
    });
  }

  return warnings;
}

function ScoreRing({ score }: { score: number }) {
  const clamped = Math.max(0, Math.min(100, score));
  const radius = 28;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (clamped / 100) * circumference;
  const color =
    clamped >= 80
      ? 'text-green-500'
      : clamped >= 50
        ? 'text-amber-500'
        : clamped >= 20
          ? 'text-orange-500'
          : 'text-red-500';

  return (
    <div className="relative inline-flex items-center justify-center" data-testid="score-ring">
      <svg width="72" height="72" viewBox="0 0 72 72">
        <circle cx="36" cy="36" r={radius} fill="none" stroke="currentColor" strokeWidth="6" className="text-gray-200" />
        <circle
          cx="36"
          cy="36"
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth="6"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          className={color}
          transform="rotate(-90 36 36)"
        />
      </svg>
      <span className="absolute text-sm font-semibold text-gray-900">{clamped}%</span>
    </div>
  );
}

function SurfaceRow({ surface }: { surface: UiSurfaceRow }) {
  const cfg = SURFACE_STATUS_CONFIG[surface.status];
  const Icon = cfg.icon;
  const counts =
    surface.item_count != null
      ? surface.optimizable_count != null
        ? `${surface.optimizable_count}/${surface.item_count} optimizable`
        : `${surface.item_count} items`
      : null;

  return (
    <tr className="border-t border-gray-100">
      <td className="py-2 pr-3 text-sm font-medium text-gray-900">{surface.name}</td>
      <td className="py-2 pr-3">
        <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${cfg.bg} ${cfg.color}`}>
          <Icon className="h-3 w-3" />
          {cfg.label}
        </span>
      </td>
      <td className="py-2 pr-3 text-xs text-gray-500">{counts}</td>
      <td className="py-2 text-xs text-gray-600">{surface.detail}</td>
    </tr>
  );
}

function WarningRow({ warning }: { warning: UiWarning }) {
  const cfg = SEVERITY_CONFIG[warning.severity];
  const Icon = cfg.icon;

  return (
    <div className="flex gap-2 border-t border-gray-100 py-2 first:border-t-0">
      <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${cfg.color}`} />
      <div className="min-w-0">
        <p className="text-sm text-gray-900">{warning.message}</p>
        <p className="mt-0.5 text-xs text-gray-500">
          <span className="font-medium">Recommendation:</span> {warning.recommendation}
        </p>
      </div>
    </div>
  );
}

function TopologyCard({ report }: { report: PortabilityReport }) {
  const summary = report.topology.summary;
  const hasCallbacks = report.callbacks.length > 0;
  const codeToolCount = report.surfaces.reduce((count, surface) => {
    const opaque = surface.metadata?.opaque_code_tool_count;
    return count + (typeof opaque === 'number' ? opaque : 0);
  }, 0);

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-3">
      <div className="mb-2 flex items-center gap-1.5">
        <GitFork className="h-4 w-4 text-gray-400" />
        <h4 className="text-xs font-medium uppercase tracking-wide text-gray-700">Agent Topology</h4>
      </div>
      <div className="grid grid-cols-3 gap-3 text-center">
        <div>
          <p className="text-lg font-semibold text-gray-900">{summary.node_count}</p>
          <p className="text-xs text-gray-500">Nodes</p>
        </div>
        <div>
          <p className="text-lg font-semibold text-gray-900">{summary.edge_count}</p>
          <p className="text-xs text-gray-500">Edges</p>
        </div>
        <div>
          <p className="text-lg font-semibold text-gray-900">{summary.max_depth}</p>
          <p className="text-xs text-gray-500">Max depth</p>
        </div>
      </div>
      <div className="mt-2 flex flex-wrap gap-2">
        {hasCallbacks && (
          <span className="inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">
            {report.callbacks.length} callback{report.callbacks.length !== 1 ? 's' : ''}
          </span>
        )}
        {codeToolCount > 0 && (
          <span className="inline-flex items-center rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700">
            {codeToolCount} code tool{codeToolCount !== 1 ? 's' : ''} (opaque)
          </span>
        )}
        {summary.orchestration_modes.length > 0 && (
          <span className="inline-flex items-center rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-700">
            {summary.orchestration_modes.join(', ')}
          </span>
        )}
      </div>
    </div>
  );
}

interface NextStepAction {
  label: string;
  href: string;
  primary?: boolean;
}

function deriveNextSteps(report: PortabilityReport, verdict: UiVerdict): NextStepAction[] {
  const steps: NextStepAction[] = [];

  if (verdict === 'ready' || verdict === 'partial') {
    steps.push({ label: 'Run evaluations', href: '/evals', primary: true });
    steps.push({ label: 'Review configs', href: '/configs' });
  }

  if (verdict === 'partial' || verdict === 'needs_work') {
    steps.push({ label: 'Inspect gaps', href: '/configs' });
  }

  if (report.summary.blocked_export_surfaces > 0) {
    steps.push({ label: 'Review export blockers', href: '/configs' });
  }

  if (verdict === 'unsupported') {
    steps.push({ label: 'Review config manually', href: '/configs' });
  }

  return steps;
}

export interface ReadinessReportProps {
  report: PortabilityReport | null | undefined;
  fallbackSurfaces?: string[];
  fallbackToolsCount?: number;
  adapter?: 'ADK' | 'CX';
}

export function ReadinessReport({
  report,
  fallbackSurfaces,
  fallbackToolsCount,
  adapter = 'ADK',
}: ReadinessReportProps) {
  if (!report) {
    return (
      <div className="space-y-3 rounded-lg border border-gray-200 bg-white p-4">
        <div className="flex items-center gap-2">
          <Info className="h-4 w-4 text-blue-500" />
          <h3 className="text-sm font-medium text-gray-900">Import Summary</h3>
        </div>
        <p className="text-xs text-gray-500">
          Detailed readiness analysis is not yet available for this {adapter} import.
          A future backend update will provide full coverage and eligibility scoring.
        </p>
        {fallbackSurfaces && fallbackSurfaces.length > 0 && (
          <div className="text-sm text-gray-700">
            <span className="text-gray-500">Surfaces mapped:</span> {fallbackSurfaces.join(', ')}
          </div>
        )}
        {fallbackToolsCount != null && (
          <div className="text-sm text-gray-700">
            <span className="text-gray-500">Tools imported:</span> {fallbackToolsCount}
          </div>
        )}
        <div className="rounded-lg border border-blue-100 bg-blue-50 p-3">
          <p className="text-xs font-medium uppercase tracking-wide text-blue-700">Next steps</p>
          <p className="mt-1 text-sm text-blue-900">
            Run evaluations to validate behavior, then review the generated config before optimization.
          </p>
        </div>
      </div>
    );
  }

  const score = Math.round(report.optimization_eligibility.score);
  const verdict = deriveVerdict(report);
  const verdictCfg = VERDICT_CONFIG[verdict];
  const VerdictIcon = verdictCfg.icon;
  const surfaceRows = deriveSurfaceRows(report);
  const warnings = deriveWarnings(report);
  const nextSteps = deriveNextSteps(report, verdict);
  const criticalCount = warnings.filter((w) => w.severity === 'critical').length;
  const warningCount = warnings.filter((w) => w.severity === 'warning').length;

  return (
    <div className="space-y-4" data-testid="readiness-report">
      <div className={`rounded-lg border ${verdictCfg.border} ${verdictCfg.bg} p-4`}>
        <div className="flex items-start gap-3">
          <ScoreRing score={score} />
          <div className="min-w-0 flex-1">
            <div className={`flex items-center gap-1.5 ${verdictCfg.color}`}>
              <VerdictIcon className="h-4 w-4" />
              <h3 className="text-sm font-semibold">{verdictCfg.label}</h3>
            </div>
            <p className="mt-1 text-sm text-gray-700">
              {score}% of this {adapter} agent's surfaces are currently within AgentLab's optimization envelope.
              {criticalCount > 0 && (
                <span className="font-medium text-red-600">
                  {' '}{criticalCount} critical issue{criticalCount !== 1 ? 's' : ''} need attention.
                </span>
              )}
              {warningCount > 0 && criticalCount === 0 && (
                <span className="text-amber-600">
                  {' '}{warningCount} warning{warningCount !== 1 ? 's' : ''} to review.
                </span>
              )}
            </p>
          </div>
        </div>
      </div>

      {surfaceRows.length > 0 && (
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <h4 className="mb-2 text-xs font-medium uppercase tracking-wide text-gray-700">Surface Coverage</h4>
          <table className="w-full text-left">
            <thead>
              <tr className="text-xs text-gray-500">
                <th className="pb-1 pr-3 font-medium">Surface</th>
                <th className="pb-1 pr-3 font-medium">Status</th>
                <th className="pb-1 pr-3 font-medium">Coverage</th>
                <th className="pb-1 font-medium">Detail</th>
              </tr>
            </thead>
            <tbody>
              {surfaceRows.map((surface) => (
                <SurfaceRow key={surface.name} surface={surface} />
              ))}
            </tbody>
          </table>
        </div>
      )}

      <TopologyCard report={report} />

      {warnings.length > 0 && (
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <h4 className="mb-1 text-xs font-medium uppercase tracking-wide text-gray-700">
            Warnings & Recommendations
          </h4>
          <div>
            {warnings.map((warning, i) => (
              <WarningRow key={`${warning.category}-${i}`} warning={warning} />
            ))}
          </div>
        </div>
      )}

      {nextSteps.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {nextSteps.map((step) => (
            <a
              key={step.href + step.label}
              href={step.href}
              className={`inline-flex items-center gap-1 rounded-lg border px-3 py-1.5 text-sm font-medium transition ${
                step.primary
                  ? 'border-blue-200 bg-blue-50 text-blue-700 hover:bg-blue-100'
                  : 'border-gray-300 bg-white text-gray-700 hover:bg-gray-100'
              }`}
            >
              {step.label}
              <ArrowRight className="h-3 w-3" />
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
