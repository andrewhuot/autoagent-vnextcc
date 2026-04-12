import { Link } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import type { JourneyStatusSummary } from '../lib/types';
import { getOperatorJourneyStepLabel } from '../lib/operator-journey';
import { classNames } from '../lib/utils';

interface OperatorNextStepCardProps {
  summary: JourneyStatusSummary;
  onAction?: () => void;
  className?: string;
}

function statusTone(status: JourneyStatusSummary['status']): string {
  switch (status) {
    case 'ready':
      return 'border-emerald-200 bg-emerald-50 text-emerald-800';
    case 'blocked':
      return 'border-amber-200 bg-amber-50 text-amber-800';
    case 'complete':
      return 'border-sky-200 bg-sky-50 text-sky-800';
    case 'active':
      return 'border-gray-300 bg-gray-900 text-white';
    default:
      return 'border-gray-200 bg-gray-50 text-gray-700';
  }
}

/** Keep the primary operator flow visible with one accessible contract on every core page. */
export function OperatorNextStepCard({
  summary,
  onAction,
  className,
}: OperatorNextStepCardProps) {
  const currentLabel = getOperatorJourneyStepLabel(summary.currentStep);
  const nextLabel = summary.nextAction.label.toLowerCase();
  const actionClassName = classNames(
    'inline-flex items-center justify-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition',
    summary.nextAction.disabled
      ? 'cursor-not-allowed border border-gray-200 bg-gray-100 text-gray-400'
      : 'bg-gray-900 text-white hover:bg-gray-800'
  );

  return (
    <section
      aria-label="Operator journey"
      className={classNames(
        'rounded-lg border border-gray-200 bg-white p-4 shadow-sm',
        className
      )}
    >
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full border border-gray-200 bg-gray-50 px-3 py-1 text-xs font-semibold text-gray-700">
              Current step: {currentLabel}
            </span>
            <span className={classNames('rounded-full border px-3 py-1 text-xs font-semibold', statusTone(summary.status))}>
              {summary.statusLabel}
            </span>
          </div>
          <p className="mt-3 text-base font-semibold text-gray-900">Next: {nextLabel}</p>
          <p className="mt-1 max-w-3xl text-sm leading-6 text-gray-600">{summary.summary}</p>
          <p className="mt-1 max-w-3xl text-xs leading-5 text-gray-500">
            {summary.nextAction.description}
          </p>
        </div>

        {summary.nextAction.href ? (
          <Link
            to={summary.nextAction.href}
            className={actionClassName}
            aria-disabled={summary.nextAction.disabled || undefined}
            tabIndex={summary.nextAction.disabled ? -1 : undefined}
          >
            {summary.nextAction.label}
            <ArrowRight className="h-4 w-4" />
          </Link>
        ) : (
          <button
            type="button"
            onClick={onAction}
            disabled={summary.nextAction.disabled || !onAction}
            className={actionClassName}
          >
            {summary.nextAction.label}
            <ArrowRight className="h-4 w-4" />
          </button>
        )}
      </div>
    </section>
  );
}
