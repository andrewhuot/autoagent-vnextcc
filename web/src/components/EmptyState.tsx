import type { LucideIcon } from 'lucide-react';
import type { ProductStateKind } from '../lib/types';
import { classNames, statusLabel } from '../lib/utils';

export type EmptyStateKind = ProductStateKind | 'no-data';

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description: string;
  state?: EmptyStateKind;
  stateLabel?: string;
  reason?: string;
  nextAction?: string;
  compact?: boolean;
  cliHint?: string;
  actionLabel?: string;
  onAction?: () => void;
}

const stateTone: Record<EmptyStateKind, string> = {
  expected: 'border-gray-200 bg-white text-gray-600',
  blocked: 'border-red-200 bg-red-50 text-red-700',
  degraded: 'border-amber-200 bg-amber-50 text-amber-700',
  waiting: 'border-sky-200 bg-sky-50 text-sky-700',
  'no-data': 'border-gray-200 bg-gray-50 text-gray-600',
};

function getDefaultStateLabel(state: EmptyStateKind): string {
  if (state === 'no-data') {
    return statusLabel('no_data');
  }
  return statusLabel(state);
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  state,
  stateLabel,
  reason,
  nextAction,
  compact = false,
  cliHint,
  actionLabel,
  onAction,
}: EmptyStateProps) {
  return (
    <div
      className={classNames(
        'flex flex-col items-center justify-center px-4 text-center',
        compact ? 'py-6' : 'py-24'
      )}
    >
      <div
        className={classNames(
          'mb-5 rounded-lg bg-gradient-to-br from-gray-50 to-gray-100 shadow-sm ring-1 ring-gray-200/50',
          compact ? 'p-3' : 'p-4'
        )}
      >
        <Icon className={classNames('text-gray-400', compact ? 'h-5 w-5' : 'h-8 w-8')} />
      </div>
      {state && (
        <span
          className={classNames(
            'mb-3 inline-flex rounded-full border px-2.5 py-1 text-[11px] font-semibold uppercase',
            stateTone[state]
          )}
        >
          {stateLabel ?? getDefaultStateLabel(state)}
        </span>
      )}
      <h3 className="text-base font-semibold text-gray-900">{title}</h3>
      <p className="mt-2 max-w-md text-sm leading-relaxed text-gray-600">{description}</p>
      {state && reason && (
        <p className="mt-2 max-w-md text-sm leading-relaxed text-gray-700">
          <span className="font-semibold">{stateLabel ?? getDefaultStateLabel(state)}:</span> {reason}
        </p>
      )}
      {nextAction && (
        <p className="mt-2 max-w-md text-sm font-medium leading-relaxed text-gray-700">
          Next: {nextAction}
        </p>
      )}
      {cliHint && (
        <code className="mt-4 rounded-lg border border-gray-200 bg-gray-50 px-4 py-2 text-xs font-mono text-gray-700 shadow-sm">
          {cliHint}
        </code>
      )}
      {actionLabel && onAction && (
        <button
          onClick={onAction}
          className="mt-6 rounded-lg bg-gray-900 px-5 py-2.5 text-sm font-medium text-white shadow-sm transition-all hover:bg-gray-800 hover:shadow"
        >
          {actionLabel}
        </button>
      )}
    </div>
  );
}
