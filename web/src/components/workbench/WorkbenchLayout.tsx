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
import { ArrowLeft, Sparkles } from 'lucide-react';
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
  const progress = useMemo(() => summarizePlan(plan), [plan]);

  return (
    <div className="workbench-root flex h-[calc(100vh-120px)] min-h-[600px] flex-col overflow-hidden rounded-xl border border-[color:var(--wb-border)] bg-[color:var(--wb-bg)] text-neutral-100 shadow-[0_0_0_1px_rgba(255,255,255,0.03)]">
      {/* Top bar */}
      <header className="flex items-center justify-between gap-3 border-b border-[color:var(--wb-border)] bg-[color:var(--wb-bg)] px-4 py-2.5">
        <div className="flex min-w-0 items-center gap-2">
          {onBack && (
            <button
              type="button"
              onClick={onBack}
              className="flex h-7 w-7 items-center justify-center rounded-md text-neutral-500 hover:bg-white/5 hover:text-neutral-300"
              aria-label="Back"
            >
              <ArrowLeft className="h-4 w-4" />
            </button>
          )}
          <span className="flex h-6 w-6 items-center justify-center rounded bg-[color:var(--wb-accent)]/15 text-[color:var(--wb-accent)]">
            <Sparkles className="h-3.5 w-3.5" />
          </span>
          <h1 className="truncate text-[13px] font-semibold text-neutral-100">{projectName}</h1>
          <span className="rounded-full border border-[color:var(--wb-border)] px-2 py-0.5 text-[10px] uppercase tracking-wider text-neutral-500">
            {target} · v{version}
          </span>
          <StatusPill status={buildStatus} />
          {progress.leafCount > 0 && (
            <span className="text-[11px] text-neutral-500" aria-live="polite">
              {progress.done}/{progress.leafCount} steps
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            className="rounded-md border border-[color:var(--wb-border)] bg-[color:var(--wb-accent)] px-3 py-1 text-[12px] font-medium text-[#0b0b0d] hover:opacity-90"
          >
            Create agent
          </button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1 flex-col xl:grid xl:grid-cols-[460px_minmax(0,1fr)]">
        {/* Left pane: conversation + chat input + plan tree */}
        <div className="flex min-h-0 flex-col border-b border-[color:var(--wb-border)] xl:border-b-0 xl:border-r">
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
  let className = 'bg-white/[0.06] text-neutral-400';
  let label = 'Idle';
  if (status === 'running' || status === 'starting') {
    className = 'bg-[color:var(--wb-accent)]/15 text-[color:var(--wb-accent)]';
    label = 'Running';
  } else if (status === 'done') {
    className = 'bg-[color:var(--wb-success)]/15 text-[color:var(--wb-success)]';
    label = 'Ready';
  } else if (status === 'error') {
    className = 'bg-[color:var(--wb-error)]/15 text-[color:var(--wb-error)]';
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
