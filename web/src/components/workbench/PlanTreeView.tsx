/**
 * Nested, live plan tree — the Manus-style "Create tools and plan all features"
 * checklist on the left pane. Expands groups, shows running spinners, lets the
 * user click a leaf task to focus its most recent artifact in the right pane.
 */

import { useMemo } from 'react';
import { CheckCircle2, ChevronDown, Circle, CircleDashed, ListTree, Loader2, PauseCircle, TriangleAlert } from 'lucide-react';
import { classNames } from '../../lib/utils';
import type { PlanTask, PlanTaskStatus } from '../../lib/workbench-api';
import { useWorkbenchStore } from '../../lib/workbench-store';
import { summarizePlan } from '../../lib/workbench-plan';

interface PlanTreeViewProps {
  plan: PlanTask;
}

function StatusIcon({ status }: { status: PlanTaskStatus }) {
  const sharedClass = 'h-4 w-4 shrink-0';
  if (status === 'done') {
    return <CheckCircle2 className={classNames(sharedClass, 'text-[color:var(--wb-success)]')} aria-label="Done" />;
  }
  if (status === 'running') {
    return (
      <Loader2
        className={classNames(sharedClass, 'animate-spin text-[color:var(--wb-accent)]')}
        aria-label="Running"
      />
    );
  }
  if (status === 'error') {
    return <TriangleAlert className={classNames(sharedClass, 'text-[color:var(--wb-error)]')} aria-label="Error" />;
  }
  if (status === 'paused') {
    return <PauseCircle className={classNames(sharedClass, 'text-[color:var(--wb-warn)]')} aria-label="Paused" />;
  }
  if (status === 'skipped') {
    return <CircleDashed className={classNames(sharedClass, 'text-neutral-500')} aria-label="Skipped" />;
  }
  return <Circle className={classNames(sharedClass, 'text-neutral-500')} aria-label="Pending" />;
}

function TaskRow({ task, depth }: { task: PlanTask; depth: number }) {
  const hasChildren = (task.children ?? []).length > 0;
  const artifacts = useWorkbenchStore((state) => state.artifacts);
  const activeArtifactId = useWorkbenchStore((state) => state.activeArtifactId);
  const setActiveArtifact = useWorkbenchStore((state) => state.setActiveArtifact);

  const firstArtifactId = useMemo(() => {
    if (!task.artifact_ids || task.artifact_ids.length === 0) return null;
    const owned = artifacts.filter((a) => task.artifact_ids?.includes(a.id));
    return owned.length > 0 ? owned[owned.length - 1].id : null;
  }, [artifacts, task.artifact_ids]);

  const isActive = firstArtifactId && firstArtifactId === activeArtifactId;

  const handleClick = () => {
    if (firstArtifactId) {
      setActiveArtifact(firstArtifactId);
    }
  };

  return (
    <li>
      <button
        type="button"
        onClick={handleClick}
        className={classNames(
          'group flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left transition-colors',
          'hover:bg-white/5 focus:outline-none focus:ring-1 focus:ring-[color:var(--wb-accent)]',
          isActive && 'bg-white/[0.06]'
        )}
        style={{ paddingLeft: `${depth * 12 + 8}px` }}
      >
        <span className="mt-0.5">
          {hasChildren ? (
            <ChevronDown className="h-3.5 w-3.5 text-neutral-500" />
          ) : (
            <StatusIcon status={task.status} />
          )}
        </span>
        <span className="min-w-0 flex-1">
          <span
            className={classNames(
              'block truncate text-[13px] leading-5',
              task.status === 'done' ? 'text-neutral-400' : 'text-neutral-100',
              hasChildren && 'font-medium text-neutral-200'
            )}
          >
            {task.title}
          </span>
          {!hasChildren && task.log && task.log.length > 0 && (
            <span className="mt-0.5 block truncate text-[11px] text-neutral-500">
              {task.log[task.log.length - 1]}
            </span>
          )}
        </span>
      </button>
      {hasChildren && (
        <ul className="mt-0.5">
          {task.children.map((child) => (
            <TaskRow key={child.id} task={child} depth={depth + 1} />
          ))}
        </ul>
      )}
    </li>
  );
}

export function PlanTreeView({ plan }: PlanTreeViewProps) {
  const summary = useMemo(() => summarizePlan(plan), [plan]);

  return (
    <section
      aria-label="Build plan"
      className="rounded-lg border border-[color:var(--wb-border)] bg-[color:var(--wb-bg-elev)] p-3"
    >
      <header className="mb-2 flex items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 text-[12px] font-semibold uppercase tracking-wider text-neutral-400">
          <ListTree className="h-3.5 w-3.5" />
          Plan
        </h3>
        <span className="text-[11px] text-neutral-500">
          {summary.done} / {summary.leafCount} steps
        </span>
      </header>
      <ul className="space-y-0.5" aria-live="polite">
        {(plan.children ?? []).length > 0
          ? plan.children.map((child) => <TaskRow key={child.id} task={child} depth={0} />)
          : <TaskRow task={plan} depth={0} />}
      </ul>
    </section>
  );
}
