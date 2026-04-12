/**
 * Compact harness metrics bar shown in the WorkbenchLayout header area.
 *
 * Displays:
 *   - Current phase icon + label (planning / executing / reflecting / presenting)
 *   - Step progress "3/8 steps" with a thin filled bar
 *   - Tokens used (formatted e.g. "2.4k tokens")
 *   - Cost ("$0.02")
 *   - Elapsed time ("12s" or "1m 32s")
 *   - Iteration badge ("Iteration 2")
 *
 * The bar is invisible until harness metrics arrive so it does not take
 * space in the idle state.
 */

import {
  Activity,
  Brain,
  Clock,
  Layers,
  Loader2,
  Presentation,
  Puzzle,
} from 'lucide-react';
import { classNames } from '../../lib/utils';
import { isWorkbenchBuildActive, useWorkbenchStore } from '../../lib/workbench-store';
import type { HarnessMetrics } from '../../lib/workbench-api';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatTokens(count: number): string {
  if (count >= 1_000_000) return `${(count / 1_000_000).toFixed(1)}M tokens`;
  if (count >= 1_000) return `${(count / 1_000).toFixed(1)}k tokens`;
  return `${count} tokens`;
}

function formatCost(usd: number): string {
  if (usd === 0) return '$0.00';
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(2)}`;
}

function formatElapsed(ms: number): string {
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}m ${secs}s`;
}

type Phase = HarnessMetrics['currentPhase'];

function phaseLabel(phase: Phase): string {
  switch (phase) {
    case 'planning':
      return 'Planning';
    case 'executing':
      return 'Executing';
    case 'reflecting':
      return 'Reflecting';
    case 'presenting':
      return 'Presenting';
    default:
      return 'Idle';
  }
}

function PhaseIcon({ phase, className }: { phase: Phase; className?: string }) {
  const cls = classNames('h-3 w-3', className);
  switch (phase) {
    case 'planning':
      return <Brain className={classNames(cls, 'animate-[phase-pulse_1.5s_ease-in-out_infinite]')} />;
    case 'executing':
      return <Loader2 className={classNames(cls, 'animate-spin')} />;
    case 'reflecting':
      return <Activity className={cls} />;
    case 'presenting':
      return <Presentation className={cls} />;
    default:
      return <Layers className={cls} />;
  }
}

function phaseAccentClass(phase: Phase): string {
  switch (phase) {
    case 'planning':
      return 'text-[color:var(--wb-accent)]';
    case 'executing':
      return 'text-[color:var(--wb-warn)]';
    case 'reflecting':
      return 'text-[color:var(--wb-success)]';
    case 'presenting':
      return 'text-[color:var(--wb-accent)]';
    default:
      return 'text-[color:var(--wb-text-dim)]';
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function HarnessMetricsBar() {
  const metrics = useWorkbenchStore((s) => s.harnessMetrics);
  const iterationCount = useWorkbenchStore((s) => s.iterationCount);
  const buildStatus = useWorkbenchStore((s) => s.buildStatus);
  const activeRun = useWorkbenchStore((s) => s.activeRun);
  const skillContext = useWorkbenchStore((s) => s.skillContext);

  // Show when there are real metrics OR when a build is active (shows zeros
  // while the first harness.metrics event hasn't arrived yet).
  const visible = metrics !== null || isWorkbenchBuildActive(buildStatus);

  if (!visible) return null;

  const phase: Phase = metrics?.currentPhase ?? 'idle';
  const stepsCompleted = metrics?.stepsCompleted ?? 0;
  const totalSteps = metrics?.totalSteps ?? 0;
  const tokensUsed = metrics?.tokensUsed ?? 0;
  const costUsd = metrics?.costUsd ?? 0;
  const elapsedMs = metrics?.elapsedMs ?? 0;
  const executionMode = activeRun?.execution_mode;
  const executionLabel =
    executionMode === 'live'
      ? 'Live'
      : executionMode === 'mock'
        ? 'Mock'
        : executionMode
          ? executionMode
          : null;
  const providerModel =
    activeRun?.provider || activeRun?.model
      ? [activeRun.provider, activeRun.model].filter(Boolean).join(' / ')
      : undefined;
  const tokenLimit = activeRun?.budget?.limits?.max_tokens ?? null;
  const budgetTokensUsed =
    activeRun?.budget?.usage?.tokens ??
    activeRun?.budget?.usage?.tokens_used ??
    tokensUsed;
  const progressPct =
    totalSteps > 0 ? Math.min(100, Math.round((stepsCompleted / totalSteps) * 100)) : 0;
  const eventCount =
    activeRun?.telemetry_summary?.event_count ??
    activeRun?.events?.length ??
    0;

  return (
    <div
      className={classNames(
        'flex flex-wrap items-center gap-x-3 gap-y-1',
        'rounded-md border border-[color:var(--wb-border)] bg-[color:var(--wb-bg-elev)]',
        'px-2.5 py-1.5 text-[11px]'
      )}
      aria-label="Harness metrics"
    >
      {executionLabel && (
        <span
          className={classNames(
            'rounded border border-[color:var(--wb-border)] px-1.5 py-0.5',
            'font-medium text-[color:var(--wb-text)]'
          )}
          title={providerModel}
        >
          {executionLabel}
        </span>
      )}

      {/* Phase indicator */}
      <span
        className={classNames(
          'flex items-center gap-1 font-medium',
          phaseAccentClass(phase)
        )}
      >
        <PhaseIcon phase={phase} />
        {phaseLabel(phase)}
      </span>

      {/* Step progress */}
      {totalSteps > 0 && (
        <span className="flex items-center gap-1.5 text-[color:var(--wb-text-dim)]">
          <span className="tabular-nums">
            {stepsCompleted}/{totalSteps} steps
          </span>
          <span
            className="h-1 w-16 overflow-hidden rounded-full bg-[color:var(--wb-bg-hover)]"
            aria-hidden="true"
          >
            <span
              className="block h-full rounded-full bg-[color:var(--wb-accent)] transition-all duration-300"
              style={{ width: `${progressPct}%` }}
            />
          </span>
        </span>
      )}

      {/* Tokens */}
      {tokensUsed > 0 && (
        <span className="tabular-nums text-[color:var(--wb-text-dim)]">
          {formatTokens(tokensUsed)}
        </span>
      )}

      {tokenLimit && (
        <span className="tabular-nums text-[color:var(--wb-text-dim)]">
          {budgetTokensUsed}/{tokenLimit} tokens
        </span>
      )}

      {/* Cost */}
      {costUsd > 0 && (
        <span className="tabular-nums text-[color:var(--wb-text-dim)]">
          {formatCost(costUsd)}
        </span>
      )}

      {/* Elapsed */}
      {elapsedMs > 0 && (
        <span className="flex items-center gap-1 tabular-nums text-[color:var(--wb-text-dim)]">
          <Clock className="h-2.5 w-2.5" />
          {formatElapsed(elapsedMs)}
        </span>
      )}

      {eventCount > 0 && (
        <span className="tabular-nums text-[color:var(--wb-text-dim)]">
          event {eventCount}
        </span>
      )}

      {/* Iteration badge */}
      {iterationCount > 0 && (
        <span
          className={classNames(
            'rounded-full border border-[color:var(--wb-accent-border)]',
            'bg-[color:var(--wb-accent-weak)] px-1.5 py-0.5',
            'text-[10px] font-medium text-[color:var(--wb-accent)]'
          )}
        >
          Iteration {iterationCount}
        </span>
      )}

      {/* Skill context summary */}
      {skillContext?.skill_store_loaded && (
        <span
          className="flex items-center gap-1 text-[color:var(--wb-text-dim)]"
          title={`Build skills: ${skillContext.build_skills_available}, Runtime skills: ${skillContext.runtime_skills_available}`}
        >
          <Puzzle className="h-2.5 w-2.5" />
          <span className="tabular-nums">
            {skillContext.build_skills_available}B / {skillContext.runtime_skills_available}R skills
          </span>
        </span>
      )}
    </div>
  );
}
