import { AlertTriangle, Info, ShieldAlert, X } from 'lucide-react';
import { useMemo } from 'react';
import {
  useAcceptGuidance,
  useDismissGuidance,
  useGuidance,
  type GuidanceSuggestion,
} from '../lib/api';
import { classNames } from '../lib/utils';

interface GuidancePanelProps {
  /** Limit how many suggestions render at once. */
  limit?: number;
  /** Optional filter by suggestion id prefix (e.g. ``'workflow'``). */
  includeIds?: (id: string) => boolean;
  /** Compact style — single-line title + body, no action buttons. */
  compact?: boolean;
}

const SEVERITY_STYLES: Record<GuidanceSuggestion['severity'], string> = {
  blocker: 'border-red-500/50 bg-red-500/5 text-red-100',
  warn: 'border-amber-500/40 bg-amber-500/5 text-amber-100',
  info: 'border-sky-500/40 bg-sky-500/5 text-sky-100',
};

const SEVERITY_ICONS: Record<GuidanceSuggestion['severity'], typeof Info> = {
  blocker: ShieldAlert,
  warn: AlertTriangle,
  info: Info,
};

export function GuidancePanel({
  limit = 3,
  includeIds,
  compact = false,
}: GuidancePanelProps) {
  const { data, isLoading } = useGuidance();
  const dismiss = useDismissGuidance();
  const accept = useAcceptGuidance();

  const suggestions = useMemo(() => {
    const all = data?.suggestions ?? [];
    const filtered = includeIds ? all.filter((s) => includeIds(s.id)) : all;
    return filtered.slice(0, limit);
  }, [data?.suggestions, includeIds, limit]);

  if (isLoading || suggestions.length === 0) {
    return null;
  }

  return (
    <div className="space-y-2" data-testid="guidance-panel">
      {suggestions.map((suggestion) => {
        const Icon = SEVERITY_ICONS[suggestion.severity];
        return (
          <div
            key={suggestion.id}
            className={classNames(
              'flex items-start gap-3 rounded-lg border px-3 py-2',
              SEVERITY_STYLES[suggestion.severity]
            )}
            data-suggestion-id={suggestion.id}
          >
            <Icon className="mt-0.5 h-4 w-4 flex-shrink-0" aria-hidden />
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium truncate">
                  {suggestion.title}
                </span>
                {!compact && (
                  <button
                    type="button"
                    className="text-xs opacity-60 hover:opacity-100"
                    aria-label="Dismiss suggestion"
                    onClick={() =>
                      dismiss.mutate({ suggestionId: suggestion.id })
                    }
                  >
                    <X className="h-3 w-3" />
                  </button>
                )}
              </div>
              <p className="mt-1 text-xs opacity-80">{suggestion.body}</p>
              {!compact && (suggestion.command || suggestion.href) && (
                <div className="mt-2 flex items-center gap-3 text-xs">
                  {suggestion.command && (
                    <code className="rounded bg-black/30 px-1.5 py-0.5">
                      {suggestion.command}
                    </code>
                  )}
                  {suggestion.href && (
                    <a
                      href={suggestion.href}
                      className="underline hover:no-underline"
                      onClick={() =>
                        accept.mutate({ suggestionId: suggestion.id })
                      }
                    >
                      Open →
                    </a>
                  )}
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default GuidancePanel;
