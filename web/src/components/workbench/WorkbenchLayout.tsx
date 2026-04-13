/**
 * Dark, two-pane Workbench shell. Matches the Manus / Image-2 reference:
 *
 *   ┌──────────────────────────────────────────────────┐
 *   │  ◂  Name   [Create agent]     Share  ...         │  ← top bar
 *   ├────────────────────────┬─────────────────────────┤
 *   │  conversation feed     │  artifact viewer        │
 *   │                        │                         │
 *   ├────────────────────────┤                         │
 *   │  chat input            │                         │
 *   └────────────────────────┴─────────────────────────┘
 */

import { useMemo } from 'react';
import type { ReactNode } from 'react';
import { ArrowLeft, Moon, Sparkles, Sun } from 'lucide-react';
import { classNames, statusLabel } from '../../lib/utils';
import { isWorkbenchBuildActive, useWorkbenchStore } from '../../lib/workbench-store';
import { summarizePlan } from '../../lib/workbench-plan';
import { HarnessMetricsBar } from './HarnessMetricsBar';

interface WorkbenchLayoutProps {
  left: ReactNode;
  right: ReactNode;
  footer?: ReactNode;
  iterationControls?: ReactNode;
  onBack?: () => void;
}

export function WorkbenchLayout({
  left,
  right,
  footer,
  iterationControls,
  onBack,
}: WorkbenchLayoutProps) {
  const projectName = useWorkbenchStore((s) => s.projectName);
  const target = useWorkbenchStore((s) => s.target);
  const version = useWorkbenchStore((s) => s.version);
  const buildStatus = useWorkbenchStore((s) => s.buildStatus);
  const plan = useWorkbenchStore((s) => s.plan);
  const theme = useWorkbenchStore((s) => s.theme);
  const toggleTheme = useWorkbenchStore((s) => s.toggleTheme);
  const setActiveWorkspaceTab = useWorkbenchStore((s) => s.setActiveWorkspaceTab);
  const presentation = useWorkbenchStore((s) => s.presentation);
  const activeRun = useWorkbenchStore((s) => s.activeRun);
  const harnessMetrics = useWorkbenchStore((s) => s.harnessMetrics);
  const progress = useMemo(() => summarizePlan(plan), [plan]);
  const reviewGate =
    presentation?.review_gate ??
    activeRun?.presentation?.review_gate ??
    activeRun?.review_gate ??
    null;
  const handoff =
    presentation?.handoff ??
    activeRun?.presentation?.handoff ??
    activeRun?.handoff ??
    null;
  const hasReviewState = Boolean(reviewGate || handoff);
  const reviewBlocked =
    reviewGate?.status === 'blocked' ||
    Boolean(reviewGate?.blocking_reasons?.length);
  const reviewLabel = reviewBlocked
    ? 'Review blocked'
    : hasReviewState
      ? 'Review required'
      : isWorkbenchBuildActive(buildStatus)
        ? 'Review pending'
        : 'No review gate';
  const reviewTitle = hasReviewState
    ? 'Open the review gate and handoff details'
    : isWorkbenchBuildActive(buildStatus)
      ? 'The review gate appears after presentation is ready'
      : 'Run the harness to produce a review gate';
  const showMetrics = harnessMetrics !== null || isWorkbenchBuildActive(buildStatus);
  const interruptedRun =
    buildStatus === 'interrupted' ||
    activeRun?.status === 'interrupted' ||
    activeRun?.failure_reason === 'stale_interrupted';

  return (
    <div
      className={classNames(
        'workbench-root',
        theme === 'dark' && 'dark',
        'flex h-[calc(100vh-120px)] min-h-[600px] flex-col overflow-hidden rounded-xl',
        'border border-[color:var(--wb-border)] bg-[color:var(--wb-bg)] text-[color:var(--wb-text)]',
        'shadow-[0_1px_2px_rgba(15,23,42,0.04),0_0_0_1px_rgba(15,23,42,0.02)]'
      )}
    >
      {/* Top bar */}
      <header
        className={classNames(
          'flex items-center justify-between gap-3 bg-[color:var(--wb-bg)] px-4 py-2.5',
          !showMetrics && 'border-b border-[color:var(--wb-border)]'
        )}
      >
        <div className="flex min-w-0 items-center gap-2">
          {onBack && (
            <button
              type="button"
              onClick={onBack}
              className="flex h-7 w-7 items-center justify-center rounded-md text-[color:var(--wb-text-dim)] hover:bg-[color:var(--wb-bg-hover)] hover:text-[color:var(--wb-text)]"
              aria-label="Back"
            >
              <ArrowLeft className="h-4 w-4" />
            </button>
          )}
          <span className="flex h-6 w-6 items-center justify-center rounded bg-[color:var(--wb-accent-weak)] text-[color:var(--wb-accent)]">
            <Sparkles className="h-3.5 w-3.5" />
          </span>
          <h2 className="truncate text-[13px] font-semibold text-[color:var(--wb-text)]">{projectName}</h2>
          <span className="rounded-full border border-[color:var(--wb-border)] px-2 py-0.5 text-[10px] uppercase tracking-wider text-[color:var(--wb-text-dim)]">
            {target} · v{version}
          </span>
          <StatusPill status={buildStatus} hasReviewState={hasReviewState} reviewBlocked={reviewBlocked} />
          {progress.leafCount > 0 && (
            <span className="text-[11px] text-[color:var(--wb-text-dim)]" aria-live="polite">
              {progress.done}/{progress.leafCount} steps
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={toggleTheme}
            className="flex h-7 w-7 items-center justify-center rounded-md border border-[color:var(--wb-border)] bg-[color:var(--wb-bg)] text-[color:var(--wb-text-dim)] hover:bg-[color:var(--wb-bg-hover)] hover:text-[color:var(--wb-text)]"
            aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
            title={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
          >
            {theme === 'dark' ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
          </button>
          <button
            type="button"
            disabled={!hasReviewState}
            onClick={() => setActiveWorkspaceTab('activity')}
            className={classNames(
              'rounded-md px-3 py-1 text-[12px] font-medium transition',
              hasReviewState
                ? reviewBlocked
                  ? 'border border-[color:var(--wb-error)] bg-[color:var(--wb-error-weak)] text-[color:var(--wb-error)] hover:opacity-90'
                  : 'border border-[color:var(--wb-accent-border)] bg-[color:var(--wb-accent-weak)] text-[color:var(--wb-accent)] hover:bg-[color:var(--wb-accent)] hover:text-[color:var(--wb-accent-fg)]'
                : 'cursor-not-allowed bg-[color:var(--wb-bg-hover)] text-[color:var(--wb-text-muted)] opacity-60'
            )}
            title={reviewTitle}
          >
            {reviewLabel}
          </button>
        </div>
      </header>
      {interruptedRun && (
        <div className="border-y border-[color:var(--wb-border)] bg-[color:var(--wb-warn-weak)] px-4 py-2 text-[12px] text-[color:var(--wb-warn)]">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full border border-[color:var(--wb-border)] bg-[color:var(--wb-bg)] px-2 py-0.5 font-semibold uppercase tracking-wider">
              Historical snapshot
            </span>
            <span className="font-medium">Interrupted run restored after restart</span>
          </div>
        </div>
      )}
      {showMetrics && (
        <div className="border-y border-[color:var(--wb-border)] bg-[color:var(--wb-bg)] px-4 py-2">
          <HarnessMetricsBar />
        </div>
      )}

      <div className="flex min-h-0 flex-1 flex-col lg:grid lg:grid-cols-[440px_minmax(0,1fr)]">
        {/* Left pane: conversation + chat input + iteration controls */}
        <div className="flex min-h-0 flex-col border-b border-[color:var(--wb-border)] lg:border-b-0 lg:border-r">
          <div className="flex min-h-0 flex-1 flex-col">{left}</div>
          {footer}
          {iterationControls}
        </div>
        {/* Right pane: artifact viewer */}
        <div className="min-h-0 overflow-hidden">{right}</div>
      </div>
    </div>
  );
}

function StatusPill({
  status,
  hasReviewState,
  reviewBlocked,
}: {
  status: string;
  hasReviewState: boolean;
  reviewBlocked: boolean;
}) {
  let className = 'bg-[color:var(--wb-bg-hover)] text-[color:var(--wb-text-dim)]';
  let label = 'Idle';
  if (status === 'running' || status === 'starting') {
    className = 'bg-[color:var(--wb-accent-weak)] text-[color:var(--wb-accent)]';
    label = status === 'starting' ? 'Starting' : 'Running';
  } else if (status === 'done') {
    className = reviewBlocked
      ? 'bg-[color:var(--wb-error-weak)] text-[color:var(--wb-error)]'
      : 'bg-[color:var(--wb-success-weak)] text-[color:var(--wb-success)]';
    label = reviewBlocked ? statusLabel('blocked') : hasReviewState ? statusLabel('review_required') : statusLabel('ready');
  } else if (status === 'error') {
    className = 'bg-[color:var(--wb-error-weak)] text-[color:var(--wb-error)]';
    label = statusLabel('failed');
  } else if (status === 'queued') {
    className = 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400';
    label = 'Queued';
  } else if (status === 'reflecting') {
    className = 'bg-[color:var(--wb-warn-weak)] text-[color:var(--wb-warn)]';
    label = 'Validating';
  } else if (status === 'presenting') {
    className = 'bg-teal-100 text-teal-700 dark:bg-teal-900/30 dark:text-teal-400';
    label = 'Preparing review';
  } else if (status === 'cancelled') {
    className = 'bg-[color:var(--wb-bg-hover)] text-[color:var(--wb-text-muted)]';
    label = statusLabel('interrupted');
  } else if (status === 'interrupted') {
    className = 'bg-[color:var(--wb-warn-weak)] text-[color:var(--wb-warn)]';
    label = statusLabel('interrupted');
  }
  return (
    <span
      className={classNames(
        'rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider',
        className
      )}
    >
      {label}
    </span>
  );
}
