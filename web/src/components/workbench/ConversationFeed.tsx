/**
 * Left-pane scrolling feed — multi-turn, Claude-Code/Manus-style running log.
 *
 * The feed renders the conversation as a sequence of TURNS. Each turn has:
 *   1. The user message that started it
 *   2. The plan tree the agent generated (fills in live)
 *   3. Assistant narration streamed from that turn
 *   4. One ArtifactCard per artifact produced in that turn
 *   5. Autonomous validation + iteration markers when the agent self-corrects
 *
 * The latest turn also shows the "Next: <task>" spinner while the plan is
 * still running. Completing a turn leaves its plan+artifacts visible so the
 * user can scroll back through the full session history.
 */

import { Fragment, useEffect, useMemo, useRef } from 'react';
import { AlertTriangle, CheckCircle2, Info, Loader2, RotateCw } from 'lucide-react';
import { classNames } from '../../lib/utils';
import {
  isWorkbenchBuildActive,
  useWorkbenchStore,
  type AssistantMessage,
  type BuildStatus,
  type WorkbenchTurn,
} from '../../lib/workbench-store';
import { walkTasks } from '../../lib/workbench-plan';
import type { WorkbenchArtifact, WorkbenchRun } from '../../lib/workbench-api';
import { AssistantMessageCard } from './AssistantMessageCard';
import { ArtifactCard } from './ArtifactCard';
import { PlanTreeView } from './PlanTreeView';
import { ReflectionCard } from './ReflectionCard';

interface ConversationFeedProps {
  /** Called when the user clicks "Apply" on a reflection suggestion. */
  onApplySuggestion?: (suggestion: string) => void;
}

export function ConversationFeed({ onApplySuggestion }: ConversationFeedProps = {}) {
  const plan = useWorkbenchStore((s) => s.plan);
  const messages = useWorkbenchStore((s) => s.messages);
  const artifacts = useWorkbenchStore((s) => s.artifacts);
  const buildStatus = useWorkbenchStore((s) => s.buildStatus);
  const error = useWorkbenchStore((s) => s.error);
  const turns = useWorkbenchStore((s) => s.turns);
  const activeTurnId = useWorkbenchStore((s) => s.activeTurnId);
  const currentIterationIndex = useWorkbenchStore(
    (s) => s.currentIterationIndex
  );
  const reflections = useWorkbenchStore((s) => s.reflections);
  const activeRun = useWorkbenchStore((s) => s.activeRun);

  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = scrollRef.current;
    if (!container) return;
    container.scrollTop = container.scrollHeight;
  }, [
    messages.length,
    artifacts.length,
    plan?.status,
    buildStatus,
    turns.length,
    currentIterationIndex,
    reflections.length,
  ]);

  const runningTask = plan
    ? Array.from(walkTasks(plan)).find(
        (task) => (task.children ?? []).length === 0 && task.status === 'running'
      )
    : null;

  const turnGroups = useMemo(
    () => buildTurnGroups(turns, messages, artifacts, plan, activeTurnId),
    [turns, messages, artifacts, plan, activeTurnId]
  );

  // Messages that never got tagged with a turn (safety net for transient
  // state while turn.started hasn't landed yet).
  const pendingMessages = useMemo(() => messages.filter((m) => !m.turnId), [messages]);
  const terminalNotice = buildTerminalNotice(buildStatus, error, activeRun);

  return (
    <div
      ref={scrollRef}
      className="flex-1 overflow-y-auto px-4 py-4"
      aria-label="Build conversation"
    >
      <div className="mx-auto flex max-w-2xl flex-col gap-4">
        {buildStatus === 'idle' && messages.length === 0 && turns.length === 0 && (
          <div className="mt-12 text-center">
            <h2 className="text-[15px] font-semibold text-[color:var(--wb-text)]">
              Describe the agent you want to build
            </h2>
            <p className="mt-2 text-[12px] leading-5 text-[color:var(--wb-text-dim)]">
              I&rsquo;ll produce a plan, generate tools and guardrails, and render the
              source code so you can review it — all live on the right. Follow-up
              messages will refine the same agent across multiple turns.
            </p>
          </div>
        )}

        {turns.length === 0 && pendingMessages.map((message) => (
          <AssistantMessageCard
            key={message.id}
            message={message}
            role={message.id.startsWith('msg-user-') ? 'user' : 'assistant'}
          />
        ))}

        {turnGroups.map((group, index) => {
          const isLast = index === turnGroups.length - 1;
          const isActive = group.turn.turnId === activeTurnId && isWorkbenchBuildActive(buildStatus);
          return (
            <TurnBlock
              key={group.turn.turnId}
              group={group}
              index={index}
              isActive={isActive}
              isLast={isLast}
              runningTask={isLast ? runningTask ?? null : null}
              currentIterationIndex={
                isActive ? currentIterationIndex : group.turn.iterationCount
              }
              buildStatus={buildStatus}
            />
          );
        })}

        {turns.length > 0 && pendingMessages.map((message) => (
          <AssistantMessageCard
            key={message.id}
            message={message}
            role={message.id.startsWith('msg-user-') ? 'user' : 'assistant'}
          />
        ))}

        {/* Reflection cards from the harness reflect phase */}
        {reflections.length > 0 && (
          <div className="flex flex-col gap-2">
            {reflections.map((reflection) => (
              <ReflectionCard
                key={reflection.id}
                reflection={reflection}
                onApplySuggestion={onApplySuggestion ?? (() => {})}
              />
            ))}
          </div>
        )}

        {buildStatus === 'done' && turns.length > 0 && (
          <div className="flex items-center gap-2 rounded-md border border-[color:var(--wb-border)] bg-[color:var(--wb-success-weak)] px-3 py-2 text-[12px] text-[color:var(--wb-success)]">
            <CheckCircle2 className="h-3.5 w-3.5" />
            <span>
              {turns.length === 1
                ? 'Candidate ready for human review. Inspect artifacts, source, and the review gate before promotion.'
                : `Turn ${turns.length} complete. Review the updated candidate or send another follow-up.`}
            </span>
          </div>
        )}

        {terminalNotice && (
          <div
            className={classNames(
              'flex items-center gap-2 rounded-md border px-3 py-2 text-[12px]',
              terminalNotice.tone === 'error'
                ? 'border-[color:var(--wb-border)] bg-[color:var(--wb-error-weak)] text-[color:var(--wb-error)]'
                : 'border-[color:var(--wb-border)] bg-[color:var(--wb-warn-weak)] text-[color:var(--wb-warn)]'
            )}
          >
            {terminalNotice.tone === 'error' ? (
              <AlertTriangle className="h-3.5 w-3.5" />
            ) : (
              <Info className="h-3.5 w-3.5" />
            )}
            <span>{terminalNotice.message}</span>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Turn grouping
// ---------------------------------------------------------------------------

interface TurnGroup {
  turn: WorkbenchTurn;
  userMessage: AssistantMessage | null;
  assistantMessages: AssistantMessage[];
  artifacts: WorkbenchArtifact[];
  /** The plan currently attached to this turn (latest pass wins). */
  plan: WorkbenchTurn['plan'];
}

function buildTurnGroups(
  turns: WorkbenchTurn[],
  messages: AssistantMessage[],
  artifacts: WorkbenchArtifact[],
  livePlan: WorkbenchTurn['plan'],
  activeTurnId: string | null
): TurnGroup[] {
  return turns.map((turn) => {
    const turnMessages = messages.filter((m) => m.turnId === turn.turnId);
    const userMessage =
      turnMessages.find((m) => m.id.startsWith('msg-user-')) ?? null;
    const assistantMessages = turnMessages.filter((m) =>
      m.id.startsWith('msg-assist-')
    );
    const turnArtifacts = artifacts.filter((a) => a.turn_id === turn.turnId);
    // The currently-running turn mirrors the live plan so we can render the
    // most recent status without waiting for per-turn persistence.
    const plan = turn.turnId === activeTurnId ? livePlan ?? turn.plan : turn.plan;
    return {
      turn,
      userMessage,
      assistantMessages,
      artifacts: turnArtifacts,
      plan,
    };
  });
}

interface TurnBlockProps {
  group: TurnGroup;
  index: number;
  isActive: boolean;
  isLast: boolean;
  runningTask: { title: string } | null;
  currentIterationIndex: number;
  buildStatus: BuildStatus;
}

function TurnBlock({
  group,
  index,
  isActive,
  isLast,
  runningTask,
  currentIterationIndex,
  buildStatus,
}: TurnBlockProps) {
  const { turn, userMessage, assistantMessages, artifacts, plan } = group;
  const validation = turn.validation;
  const validationPassed = validation?.status === 'passed';

  const modeLabel =
    turn.mode === 'follow_up'
      ? 'Follow-up'
      : turn.mode === 'correction'
        ? 'Auto-correction'
        : 'Initial build';

  return (
    <section
      aria-label={`Turn ${index + 1}`}
      className="flex flex-col gap-3 rounded-lg border border-[color:var(--wb-border)] bg-[color:var(--wb-bg-elev)] p-3"
    >
      <header className="flex items-center justify-between text-[11px] uppercase tracking-wider text-[color:var(--wb-text-dim)]">
        <span className="flex items-center gap-2">
          <span className="rounded-full bg-[color:var(--wb-bg-hover)] px-2 py-0.5 text-[color:var(--wb-text-soft)]">
            Turn {index + 1}
          </span>
          <span className="text-[color:var(--wb-text-soft)]">{modeLabel}</span>
          {turn.iterationCount > 1 && (
            <span className="flex items-center gap-1 text-[color:var(--wb-accent)]">
              <RotateCw className="h-3 w-3" />
              {turn.iterationCount} passes
            </span>
          )}
        </span>
        <span
          className={classNames(
            'rounded-full px-2 py-0.5 text-[10px]',
            turn.status === 'completed' && 'bg-[color:var(--wb-success-weak)] text-[color:var(--wb-success)]',
            (turn.status === 'error' || turn.status === 'failed') && 'bg-[color:var(--wb-error-weak)] text-[color:var(--wb-error)]',
            turn.status === 'cancelled' && 'bg-[color:var(--wb-bg-hover)] text-[color:var(--wb-text-muted)]',
            (turn.status === 'running' || turn.status === 'reflecting' || turn.status === 'presenting') && 'bg-[color:var(--wb-accent-weak)] text-[color:var(--wb-accent)]'
          )}
        >
          {turn.status === 'cancelled' ? 'stopped' : turn.status}
        </span>
      </header>

      {userMessage && (
        <AssistantMessageCard message={userMessage} role="user" />
      )}

      {plan && <PlanTreeView plan={plan} />}

      {assistantMessages.length > 0 && (
        <Fragment>
          {assistantMessages.map((message) => (
            <AssistantMessageCard
              key={message.id}
              message={message}
              role="assistant"
            />
          ))}
        </Fragment>
      )}

      {artifacts.length > 0 && (
        <div className="flex flex-col gap-2">
          <h3 className="text-[11px] font-semibold uppercase tracking-wider text-[color:var(--wb-text-dim)]">
            Artifacts ({artifacts.length})
          </h3>
          {artifacts.map((artifact) => (
            <ArtifactCard key={artifact.id} artifact={artifact} />
          ))}
        </div>
      )}

      {validation && (
        <div
          className={classNames(
            'flex items-center gap-2 rounded-md border px-3 py-1.5 text-[11px]',
            validationPassed
              ? 'border-[color:var(--wb-success)] bg-[color:var(--wb-success-weak)] text-[color:var(--wb-success)]'
              : 'border-[color:var(--wb-warn)] bg-[color:var(--wb-warn-weak)] text-[color:var(--wb-warn)]'
          )}
        >
          {validationPassed ? (
            <CheckCircle2 className="h-3.5 w-3.5" />
          ) : (
            <AlertTriangle className="h-3.5 w-3.5" />
          )}
          <span>
            Validation: {validation.status ?? 'unknown'}
            {validation.checks && validation.checks.length > 0 && (
              <>
                {' '}— {validation.checks.filter((c) => c.passed).length}/
                {validation.checks.length} checks passing
              </>
            )}
          </span>
        </div>
      )}

      {isActive && isLast && (
        <LiveRunNotice
          buildStatus={buildStatus}
          runningTask={runningTask}
          currentIterationIndex={currentIterationIndex}
        />
      )}
    </section>
  );
}

function LiveRunNotice({
  buildStatus,
  runningTask,
  currentIterationIndex,
}: {
  buildStatus: BuildStatus;
  runningTask: { title: string } | null;
  currentIterationIndex: number;
}) {
  const Icon = buildStatus === 'presenting' ? CheckCircle2 : Loader2;
  const isSpinning = buildStatus !== 'presenting';
  return (
    <div
      className="flex items-center gap-2 rounded-md border border-dashed border-[color:var(--wb-border)] px-3 py-2 text-[12px] text-[color:var(--wb-text-soft)]"
      aria-live="polite"
    >
      <Icon
        className={classNames(
          'h-3.5 w-3.5 text-[color:var(--wb-accent)]',
          isSpinning && 'animate-spin'
        )}
      />
      <span>
        {runningTask ? (
          <>
            <span className="text-[color:var(--wb-text-dim)]">Next:&nbsp;</span>
            {runningTask.title}
          </>
        ) : (
          livePhaseCopy(buildStatus)
        )}
        {currentIterationIndex > 0 && (
          <span className="ml-2 text-[color:var(--wb-text-dim)]">
            (pass {currentIterationIndex + 1})
          </span>
        )}
      </span>
    </div>
  );
}

function livePhaseCopy(status: BuildStatus): string {
  if (status === 'starting' || status === 'queued') return 'Waiting for the run to start.';
  if (status === 'reflecting') return 'Validating generated outputs.';
  if (status === 'presenting') return 'Preparing the review handoff.';
  return 'Working through the plan.';
}

function buildTerminalNotice(
  buildStatus: BuildStatus,
  error: string | null,
  activeRun: WorkbenchRun | null
): { tone: 'warning' | 'error'; message: string } | null {
  if (buildStatus === 'cancelled') {
    return {
      tone: 'warning',
      message: activeRun?.cancel_reason ?? error ?? 'Run stopped by operator.',
    };
  }
  if (buildStatus !== 'error' && !error) return null;
  if (activeRun?.failure_reason === 'stale_interrupted') {
    return {
      tone: 'warning',
      message: activeRun.error ?? error ?? 'Recovered an interrupted run after reload.',
    };
  }
  return {
    tone: 'error',
    message: error ?? activeRun?.error ?? 'Workbench run failed.',
  };
}
