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
import type {
  PortabilityReport,
  PortabilitySurface,
  PortabilityWarning,
  SurfaceStatus,
  PortabilityVerdict,
} from '../lib/types';

// ---------------------------------------------------------------------------
// Verdict config
// ---------------------------------------------------------------------------

const VERDICT_CONFIG: Record<
  PortabilityVerdict,
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
  SurfaceStatus,
  { label: string; color: string; bg: string; icon: typeof CheckCircle2 }
> = {
  full: { label: 'Optimizable', color: 'text-green-700', bg: 'bg-green-100', icon: ShieldCheck },
  partial: { label: 'Partial', color: 'text-amber-700', bg: 'bg-amber-100', icon: Eye },
  read_only: { label: 'Read-only', color: 'text-blue-700', bg: 'bg-blue-100', icon: Lock },
  unsupported: { label: 'Unsupported', color: 'text-gray-500', bg: 'bg-gray-100', icon: Ban },
};

const SEVERITY_CONFIG: Record<
  PortabilityWarning['severity'],
  { color: string; icon: typeof Info }
> = {
  info: { color: 'text-blue-600', icon: Info },
  warning: { color: 'text-amber-600', icon: AlertTriangle },
  critical: { color: 'text-red-600', icon: XCircle },
};

// ---------------------------------------------------------------------------
// Score ring (SVG)
// ---------------------------------------------------------------------------

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
        <circle
          cx="36"
          cy="36"
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth="6"
          className="text-gray-200"
        />
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

// ---------------------------------------------------------------------------
// Surface row
// ---------------------------------------------------------------------------

function SurfaceRow({ surface }: { surface: PortabilitySurface }) {
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
      <td className="py-2 pr-3 text-sm text-gray-900 font-medium capitalize">{surface.name}</td>
      <td className="py-2 pr-3">
        <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${cfg.bg} ${cfg.color}`}>
          <Icon className="w-3 h-3" />
          {cfg.label}
        </span>
      </td>
      <td className="py-2 pr-3 text-xs text-gray-500">{counts}</td>
      <td className="py-2 text-xs text-gray-600">{surface.detail}</td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Warning row
// ---------------------------------------------------------------------------

function WarningRow({ warning }: { warning: PortabilityWarning }) {
  const cfg = SEVERITY_CONFIG[warning.severity];
  const Icon = cfg.icon;

  return (
    <div className="flex gap-2 py-2 border-t border-gray-100 first:border-t-0">
      <Icon className={`w-4 h-4 mt-0.5 shrink-0 ${cfg.color}`} />
      <div className="min-w-0">
        <p className="text-sm text-gray-900">{warning.message}</p>
        <p className="text-xs text-gray-500 mt-0.5">
          <span className="font-medium">Recommendation:</span> {warning.recommendation}
        </p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Topology card
// ---------------------------------------------------------------------------

function TopologyCard({ topology }: { topology: NonNullable<PortabilityReport['topology']> }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-3">
      <div className="flex items-center gap-1.5 mb-2">
        <GitFork className="w-4 h-4 text-gray-400" />
        <h4 className="text-xs font-medium text-gray-700 uppercase tracking-wide">Agent Topology</h4>
      </div>
      <div className="grid grid-cols-3 gap-3 text-center">
        <div>
          <p className="text-lg font-semibold text-gray-900">{topology.node_count}</p>
          <p className="text-xs text-gray-500">Nodes</p>
        </div>
        <div>
          <p className="text-lg font-semibold text-gray-900">{topology.edge_count}</p>
          <p className="text-xs text-gray-500">Edges</p>
        </div>
        <div>
          <p className="text-lg font-semibold text-gray-900">{topology.max_depth}</p>
          <p className="text-xs text-gray-500">Max depth</p>
        </div>
      </div>
      <div className="flex flex-wrap gap-2 mt-2">
        {topology.has_cycles && (
          <span className="inline-flex items-center rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">
            Cycles detected
          </span>
        )}
        {topology.callback_count > 0 && (
          <span className="inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">
            {topology.callback_count} callback{topology.callback_count !== 1 ? 's' : ''}
          </span>
        )}
        {topology.code_tool_count > 0 && (
          <span className="inline-flex items-center rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700">
            {topology.code_tool_count} code tool{topology.code_tool_count !== 1 ? 's' : ''} (opaque)
          </span>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Next-step CTAs
// ---------------------------------------------------------------------------

interface NextStepAction {
  label: string;
  href: string;
  primary?: boolean;
}

function deriveNextSteps(report: PortabilityReport): NextStepAction[] {
  const steps: NextStepAction[] = [];

  if (report.verdict === 'ready' || report.verdict === 'partial') {
    steps.push({ label: 'Run evaluations', href: '/evals', primary: true });
    steps.push({ label: 'Review config', href: '/configs' });
  }

  if (report.verdict === 'partial' || report.verdict === 'needs_work') {
    steps.push({ label: 'Inspect gaps', href: '/configs' });
  }

  if (report.warnings.some((w) => w.severity === 'critical')) {
    steps.push({ label: 'Review critical warnings', href: '/configs' });
  }

  if (report.verdict === 'unsupported') {
    steps.push({ label: 'Review config manually', href: '/configs' });
  }

  return steps;
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export interface ReadinessReportProps {
  report: PortabilityReport | null | undefined;
  /** Fallback surfaces list when no report is available */
  fallbackSurfaces?: string[];
  /** Fallback tools count for basic display */
  fallbackToolsCount?: number;
  /** Adapter label for messaging context */
  adapter?: 'ADK' | 'CX';
}

export function ReadinessReport({
  report,
  fallbackSurfaces,
  fallbackToolsCount,
  adapter = 'ADK',
}: ReadinessReportProps) {
  // Fallback: no portability report available
  if (!report) {
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-4 space-y-3">
        <div className="flex items-center gap-2">
          <Info className="w-4 h-4 text-blue-500" />
          <h3 className="text-sm font-medium text-gray-900">Import Summary</h3>
        </div>
        <p className="text-xs text-gray-500">
          Detailed readiness analysis is not yet available for this {adapter} import.
          A future backend update will provide full coverage and eligibility scoring.
        </p>
        {fallbackSurfaces && fallbackSurfaces.length > 0 && (
          <div className="text-sm text-gray-700">
            <span className="text-gray-500">Surfaces mapped:</span>{' '}
            {fallbackSurfaces.join(', ')}
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

  const verdictCfg = VERDICT_CONFIG[report.verdict];
  const VerdictIcon = verdictCfg.icon;
  const nextSteps = deriveNextSteps(report);
  const criticalCount = report.warnings.filter((w) => w.severity === 'critical').length;
  const warningCount = report.warnings.filter((w) => w.severity === 'warning').length;

  return (
    <div className="space-y-4" data-testid="readiness-report">
      {/* Verdict banner */}
      <div className={`rounded-lg border ${verdictCfg.border} ${verdictCfg.bg} p-4`}>
        <div className="flex items-start gap-3">
          <ScoreRing score={report.overall_score} />
          <div className="min-w-0 flex-1">
            <div className={`flex items-center gap-1.5 ${verdictCfg.color}`}>
              <VerdictIcon className="w-4 h-4" />
              <h3 className="text-sm font-semibold">{verdictCfg.label}</h3>
            </div>
            <p className="mt-1 text-sm text-gray-700">
              {report.overall_score}% of this {adapter} agent's surfaces are ready for AgentLab optimization.
              {criticalCount > 0 && (
                <span className="text-red-600 font-medium">
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

      {/* Surface breakdown */}
      {report.surfaces.length > 0 && (
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <h4 className="text-xs font-medium text-gray-700 uppercase tracking-wide mb-2">
            Surface Coverage
          </h4>
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
              {report.surfaces.map((s) => (
                <SurfaceRow key={s.name} surface={s} />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Topology */}
      {report.topology && <TopologyCard topology={report.topology} />}

      {/* Warnings */}
      {report.warnings.length > 0 && (
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <h4 className="text-xs font-medium text-gray-700 uppercase tracking-wide mb-1">
            Warnings & Recommendations
          </h4>
          <div>
            {report.warnings.map((w, i) => (
              <WarningRow key={`${w.category}-${i}`} warning={w} />
            ))}
          </div>
        </div>
      )}

      {/* Next steps */}
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
              <ArrowRight className="w-3 h-3" />
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
