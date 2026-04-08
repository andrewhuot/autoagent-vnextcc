import { AlertTriangle, CheckCircle2, Info, ShieldAlert, ArrowUpDown } from 'lucide-react';

// ---------------------------------------------------------------------------
// Export-readiness panel for deploy pages.
// Shows round-trip risk, surface preservation status, and export limitations.
// Designed to be honest: warns about what will NOT survive a round-trip.
// ---------------------------------------------------------------------------

export interface ExportSurface {
  name: string;
  preservable: boolean;
  detail: string;
}

export interface ExportReadinessProps {
  /** Adapter label for context */
  adapter: 'ADK' | 'CX';
  /** Surfaces that were imported and their round-trip status */
  surfaces?: ExportSurface[];
  /** Number of changes that will be pushed */
  changeCount?: number;
  /** Number of conflicts detected */
  conflictCount?: number;
  /** Whether export has been attempted */
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

export function ExportReadiness({
  adapter,
  surfaces,
  changeCount,
  conflictCount,
  exportAttempted,
}: ExportReadinessProps) {
  const effectiveSurfaces = surfaces ?? (adapter === 'ADK' ? DEFAULT_ADK_SURFACES : DEFAULT_CX_SURFACES);
  const preservable = effectiveSurfaces.filter((s) => s.preservable);
  const notPreservable = effectiveSurfaces.filter((s) => !s.preservable);

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 space-y-3" data-testid="export-readiness">
      <div className="flex items-center gap-2">
        <ArrowUpDown className="w-4 h-4 text-gray-400" />
        <h3 className="text-sm font-medium text-gray-900">Round-Trip Readiness</h3>
      </div>

      <p className="text-xs text-gray-500">
        Shows which surfaces will be preserved when exporting back to {adapter === 'ADK' ? 'ADK format' : 'CX Agent Studio'}.
        Surfaces marked as non-preservable will be passed through unchanged — they are outside AgentLab's optimization scope.
      </p>

      {/* Preservable surfaces */}
      {preservable.length > 0 && (
        <div>
          <p className="text-xs font-medium text-green-700 mb-1 flex items-center gap-1">
            <CheckCircle2 className="w-3 h-3" />
            Safe to round-trip ({preservable.length})
          </p>
          <div className="space-y-1">
            {preservable.map((s) => (
              <div key={s.name} className="flex items-start gap-2 text-xs">
                <span className="text-green-600 mt-0.5">+</span>
                <div>
                  <span className="font-medium text-gray-900">{s.name}</span>
                  <span className="text-gray-500 ml-1">— {s.detail}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Non-preservable surfaces */}
      {notPreservable.length > 0 && (
        <div>
          <p className="text-xs font-medium text-amber-700 mb-1 flex items-center gap-1">
            <AlertTriangle className="w-3 h-3" />
            Pass-through only ({notPreservable.length})
          </p>
          <div className="space-y-1">
            {notPreservable.map((s) => (
              <div key={s.name} className="flex items-start gap-2 text-xs">
                <span className="text-amber-600 mt-0.5">~</span>
                <div>
                  <span className="font-medium text-gray-900">{s.name}</span>
                  <span className="text-gray-500 ml-1">— {s.detail}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Export status */}
      {exportAttempted && (
        <div className="border-t border-gray-100 pt-2 space-y-1">
          {changeCount != null && (
            <div className="flex items-center gap-1.5 text-xs">
              <Info className="w-3 h-3 text-blue-500" />
              <span className="text-gray-700">
                {changeCount} change{changeCount !== 1 ? 's' : ''} identified for export
              </span>
            </div>
          )}
          {conflictCount != null && conflictCount > 0 && (
            <div className="flex items-center gap-1.5 text-xs">
              <ShieldAlert className="w-3 h-3 text-red-500" />
              <span className="text-red-700 font-medium">
                {conflictCount} conflict{conflictCount !== 1 ? 's' : ''} detected — review before pushing
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
