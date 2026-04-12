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
import { classNames } from '../../lib/utils';
import { useWorkbenchStore } from '../../lib/workbench-store';
import { summarizePlan } from '../../lib/workbench-plan';

interface WorkbenchLayoutProps {
  left: ReactNode;
  right: ReactNode;
  footer?: ReactNode;
  onBack?: () => void;
}

export function WorkbenchLayout({ left, right, footer, onBack }: WorkbenchLayoutProps) {
  const projectName = useWorkbenchStore((s) => s.projectName);
  const target = useWorkbenchStore((s) => s.target);
  const version = useWorkbenchStore((s) => s.version);
  const buildStatus = useWorkbenchStore((s) => s.buildStatus);
  const plan = useWorkbenchStore((s) => s.plan);
  const theme = useWorkbenchStore((s) => s.theme);
  const toggleTheme = useWorkbenchStore((s) => s.toggleTheme);
  const progress = useMemo(() => summarizePlan(plan), [plan]);

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
      <header className="flex items-center justify-between gap-3 border-b border-[color:var(--wb-border)] bg-[color:var(--wb-bg)] px-4 py-2.5">
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
          <h1 className="truncate text-[13px] font-semibold text-[color:var(--wb-text)]">{projectName}</h1>
          <span className="rounded-full border border-[color:var(--wb-border)] px-2 py-0.5 text-[10px] uppercase tracking-wider text-[color:var(--wb-text-dim)]">
            {target} · v{version}
          </span>
          <StatusPill status={buildStatus} />
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
            disabled={buildStatus !== 'done'}
            className={classNames(
              'rounded-md px-3 py-1 text-[12px] font-medium transition',
              buildStatus === 'done'
                ? 'bg-[color:var(--wb-accent)] text-[color:var(--wb-accent-fg)] hover:opacity-90'
                : 'cursor-not-allowed bg-[color:var(--wb-bg-hover)] text-[color:var(--wb-text-muted)]'
            )}
            title={buildStatus === 'done' ? 'Candidate is ready for review' : 'Complete a harness run first'}
          >
            {buildStatus === 'done' ? 'Candidate ready' : 'Create agent'}
          </button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1 flex-col lg:grid lg:grid-cols-[440px_minmax(0,1fr)]">
        {/* Left pane: conversation + chat input + plan tree */}
        <div className="flex min-h-0 flex-col border-b border-[color:var(--wb-border)] lg:border-b-0 lg:border-r">
          <div className="flex min-h-0 flex-1 flex-col">{left}</div>
          {footer}
        </div>
        {/* Right pane: artifact viewer */}
        <div className="min-h-0 overflow-hidden">{right}</div>
      </div>
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  let className = 'bg-[color:var(--wb-bg-hover)] text-[color:var(--wb-text-dim)]';
  let label = 'Idle';
  if (status === 'running' || status === 'starting') {
    className = 'bg-[color:var(--wb-accent-weak)] text-[color:var(--wb-accent)]';
    label = 'Running';
  } else if (status === 'done') {
    className = 'bg-[color:var(--wb-success-weak)] text-[color:var(--wb-success)]';
    label = 'Ready';
  } else if (status === 'error') {
    className = 'bg-[color:var(--wb-error-weak)] text-[color:var(--wb-error)]';
    label = 'Error';
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
