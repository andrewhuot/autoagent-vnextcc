import { AlertTriangle, CheckCircle2, Info, ShieldAlert, ArrowUpDown, Ban } from 'lucide-react';
import type { CxChange, ExportCapabilityMatrix } from '../lib/types';

export interface ExportSurface {
  name: string;
  preservable: boolean;
  detail: string;
}

export interface ExportReadinessProps {
  adapter: 'ADK' | 'CX';
  surfaces?: ExportSurface[];
  exportMatrix?: ExportCapabilityMatrix | null;
  changes?: CxChange[];
  changeCount?: number;
  conflictCount?: number;
  exportAttempted?: boolean;
}

const DEFAULT_ADK_SURFACES: ExportSurface[] = [
  { name: 'Instructions', preservable: true, detail: 'System prompts round-trip safely' },
  { name: 'Tool declarations', preservable: true, detail: 'Tool names and schemas preserved' },
  { name: 'Tool code bodies', preservable: false, detail: 'Python function code is opaque to AgentLab — exported as-is without optimization' },
  { name: 'Sub-agent routing', preservable: true, detail: 'Agent delegation graph preserved' },
  { name: 'Model config', preservable: true, detail: 'Model selection and generation params round-trip' },
  { name: 'Callbacks', preservable: false, detail: 'Custom callbacks are not modeled by AgentLab and are passed through unchanged' },
];

const DEFAULT_CX_SURFACES: ExportSurface[] = [
  { name: 'Playbooks', preservable: true, detail: 'Playbook instructions and steps round-trip' },
  { name: 'Flows', preservable: true, detail: 'Flow pages and routes preserved' },
  { name: 'Intents', preservable: true, detail: 'Intent definitions and training phrases preserved' },
  { name: 'Entity types', preservable: true, detail: 'Entity types round-trip safely' },
  { name: 'Webhooks', preservable: false, detail: 'Webhook code is external — AgentLab cannot modify webhook implementations' },
  { name: 'Custom handlers', preservable: false, detail: 'Fulfillment handlers are opaque to AgentLab' },
  { name: 'Test cases', preservable: true, detail: 'Test cases exported for regression validation' },
];

function deriveSurfaces(
  adapter: 'ADK' | 'CX',
  surfaces?: ExportSurface[],
  exportMatrix?: ExportCapabilityMatrix | null
): ExportSurface[] {
  if (surfaces) return surfaces;
  if (exportMatrix) {
    return exportMatrix.surfaces.map((surface) => ({
      name: surface.label,
      preservable: surface.status === 'ready',
      detail:
        surface.notes[0] ||
        surface.blockers[0] ||
        (surface.status === 'lossy' ? 'Round-trip is lossy for this surface.' : 'Blocked from round-trip export.'),
    }));
  }
  return adapter === 'ADK' ? DEFAULT_ADK_SURFACES : DEFAULT_CX_SURFACES;
}

const SAFETY_STYLES = {
  safe: { icon: '✓', color: 'text-green-600', bg: 'bg-green-50', label: 'Safe' },
  lossy: { icon: '~', color: 'text-amber-600', bg: 'bg-amber-50', label: 'Lossy' },
  blocked: { icon: '✕', color: 'text-red-600', bg: 'bg-red-50', label: 'Blocked' },
} as const;

export function ExportReadiness({
  adapter,
  surfaces,
  exportMatrix,
  changes,
  changeCount,
  conflictCount,
  exportAttempted,
}: ExportReadinessProps) {
  const effectiveSurfaces = deriveSurfaces(adapter, surfaces, exportMatrix);
  const preservable = effectiveSurfaces.filter((s) => s.preservable);
  const notPreservable = effectiveSurfaces.filter((s) => !s.preservable);

  const safeChanges = changes?.filter((c) => c.safety === 'safe') ?? [];
  const lossyChanges = changes?.filter((c) => c.safety === 'lossy') ?? [];
  const blockedChanges = changes?.filter((c) => c.safety === 'blocked') ?? [];

  return (
    <div className="space-y-3 rounded-lg border border-gray-200 bg-white p-4" data-testid="export-readiness">
      <div className="flex items-center gap-2">
        <ArrowUpDown className="h-4 w-4 text-gray-400" />
        <h3 className="text-sm font-medium text-gray-900">Round-Trip Readiness</h3>
      </div>

      <p className="text-xs text-gray-500">
        Shows which surfaces will be preserved when exporting back to {adapter === 'ADK' ? 'ADK format' : 'CX Agent Studio'}.
        Surfaces marked as non-preservable will be passed through unchanged or blocked — they are outside AgentLab&apos;s optimization scope.
      </p>

      {preservable.length > 0 && (
        <div>
          <p className="mb-1 flex items-center gap-1 text-xs font-medium text-green-700">
            <CheckCircle2 className="h-3 w-3" />
            Safe to round-trip ({preservable.length})
          </p>
          <div className="space-y-1">
            {preservable.map((surface) => (
              <div key={surface.name} className="flex items-start gap-2 text-xs">
                <span className="mt-0.5 text-green-600">+</span>
                <div>
                  <span className="font-medium text-gray-900">{surface.name}</span>
                  <span className="ml-1 text-gray-500">— {surface.detail}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {notPreservable.length > 0 && (
        <div>
          <p className="mb-1 flex items-center gap-1 text-xs font-medium text-amber-700">
            <AlertTriangle className="h-3 w-3" />
            Lossy or blocked ({notPreservable.length})
          </p>
          <div className="space-y-1">
            {notPreservable.map((surface) => (
              <div key={surface.name} className="flex items-start gap-2 text-xs">
                <span className="mt-0.5 text-amber-600">~</span>
                <div>
                  <span className="font-medium text-gray-900">{surface.name}</span>
                  <span className="ml-1 text-gray-500">— {surface.detail}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Per-change safety classification */}
      {changes && changes.length > 0 && (
        <div className="space-y-2 border-t border-gray-100 pt-2" data-testid="change-classification">
          <p className="text-xs font-medium text-gray-700">Change Classification</p>

          {safeChanges.length > 0 && (
            <div className="space-y-1">
              <p className="flex items-center gap-1 text-xs font-medium text-green-700">
                <CheckCircle2 className="h-3 w-3" />
                Safe to push ({safeChanges.length})
              </p>
              {safeChanges.map((change, i) => (
                <div key={`safe-${i}`} className="ml-4 flex items-center gap-2 text-xs">
                  <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium ${SAFETY_STYLES.safe.bg} ${SAFETY_STYLES.safe.color}`}>
                    {SAFETY_STYLES.safe.label}
                  </span>
                  <span className="text-gray-700">
                    {change.action.toUpperCase()} {change.resource}/{change.name || change.field}
                  </span>
                  {change.rationale && <span className="text-gray-400">— {change.rationale}</span>}
                </div>
              ))}
            </div>
          )}

          {lossyChanges.length > 0 && (
            <div className="space-y-1">
              <p className="flex items-center gap-1 text-xs font-medium text-amber-700">
                <AlertTriangle className="h-3 w-3" />
                Lossy — may lose CX-specific attributes ({lossyChanges.length})
              </p>
              {lossyChanges.map((change, i) => (
                <div key={`lossy-${i}`} className="ml-4 flex items-center gap-2 text-xs">
                  <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium ${SAFETY_STYLES.lossy.bg} ${SAFETY_STYLES.lossy.color}`}>
                    {SAFETY_STYLES.lossy.label}
                  </span>
                  <span className="text-gray-700">
                    {change.action.toUpperCase()} {change.resource}/{change.name || change.field}
                  </span>
                  {change.rationale && <span className="text-gray-400">— {change.rationale}</span>}
                </div>
              ))}
            </div>
          )}

          {blockedChanges.length > 0 && (
            <div className="space-y-1">
              <p className="flex items-center gap-1 text-xs font-medium text-red-700">
                <Ban className="h-3 w-3" />
                Blocked — cannot push to CX ({blockedChanges.length})
              </p>
              {blockedChanges.map((change, i) => (
                <div key={`blocked-${i}`} className="ml-4 flex items-center gap-2 text-xs">
                  <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium ${SAFETY_STYLES.blocked.bg} ${SAFETY_STYLES.blocked.color}`}>
                    {SAFETY_STYLES.blocked.label}
                  </span>
                  <span className="text-gray-700">
                    {change.action.toUpperCase()} {change.resource}/{change.name || change.field}
                  </span>
                  {change.rationale && <span className="text-gray-400">— {change.rationale}</span>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {exportMatrix?.rationale.length ? (
        <div className="rounded-lg border border-blue-100 bg-blue-50 p-3 text-xs text-blue-900">
          <p className="font-medium uppercase tracking-wide text-blue-700">Export rationale</p>
          <ul className="mt-1 space-y-1">
            {exportMatrix.rationale.map((note, idx) => (
              <li key={idx}>• {note}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {exportAttempted && (
        <div className="space-y-1 border-t border-gray-100 pt-2">
          {changeCount != null && (
            <div className="flex items-center gap-1.5 text-xs">
              <Info className="h-3 w-3 text-blue-500" />
              <span className="text-gray-700">
                {changeCount} change{changeCount !== 1 ? 's' : ''} identified for export
              </span>
            </div>
          )}
          {conflictCount != null && conflictCount > 0 && (
            <div className="flex items-center gap-1.5 text-xs">
              <ShieldAlert className="h-3 w-3 text-red-500" />
              <span className="font-medium text-red-700">
                {conflictCount} conflict{conflictCount !== 1 ? 's' : ''} detected — review before pushing
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
