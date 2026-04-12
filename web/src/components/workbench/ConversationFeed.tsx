/**
 * Left-pane scrolling feed: user messages, the live plan tree, assistant
 * narration, inline artifact cards, reflection cards, and a running-task
 * spinner.
 *
 * The feed interleaves content in this order every time the user sends a
 * brief:
 *   1. User message ("Build an agent…")
 *   2. Plan tree (fills in live)
 *   3. Assistant narration (streaming text)
 *   4. One ArtifactCard per generated artifact
 *   5. Reflection cards (quality assessment from the harness)
 *   6. "Next: <task>" spinner row for the currently running task
 */

import { useEffect, useRef } from 'react';
import { Loader2 } from 'lucide-react';
import { classNames } from '../../lib/utils';
import { useWorkbenchStore } from '../../lib/workbench-store';
import { walkTasks } from '../../lib/workbench-plan';
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
  const reflections = useWorkbenchStore((s) => s.reflections);
  const iterationCount = useWorkbenchStore((s) => s.iterationCount);

  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = scrollRef.current;
    if (!container) return;
    container.scrollTop = container.scrollHeight;
  }, [messages.length, artifacts.length, plan?.status, buildStatus, reflections.length]);

  const runningTask = plan
    ? Array.from(walkTasks(plan)).find(
        (task) => (task.children ?? []).length === 0 && task.status === 'running'
      )
    : null;

  const userMessages = messages.filter((m) => m.id.startsWith('msg-user-'));
  const assistantMessages = messages.filter((m) => m.id.startsWith('msg-assist-'));

  const handleApplySuggestion = (suggestion: string) => {
    if (onApplySuggestion) {
      onApplySuggestion(suggestion);
    }
  };

  return (
    <div
      ref={scrollRef}
      className="flex-1 overflow-y-auto px-4 py-4"
      aria-label="Build conversation"
    >
      <div className="mx-auto flex max-w-2xl flex-col gap-4">
        {buildStatus === 'idle' && messages.length === 0 && (
          <div className="mt-12 text-center">
            <h2 className="text-[15px] font-semibold text-[color:var(--wb-text)]">
              Describe the agent you want to build
            </h2>
            <p className="mt-2 text-[12px] leading-5 text-[color:var(--wb-text-dim)]">
              I&rsquo;ll produce a plan, generate tools and guardrails, and render the
              source code so you can review it — all live on the right.
            </p>
          </div>
        )}

        {userMessages.map((message) => (
          <AssistantMessageCard key={message.id} message={message} role="user" />
        ))}

        {plan && <PlanTreeView plan={plan} />}

        {assistantMessages.map((message) => (
          <AssistantMessageCard key={message.id} message={message} role="assistant" />
        ))}

        {artifacts.length > 0 && (
          <div className="flex flex-col gap-2">
            <h3 className="text-[11px] font-semibold uppercase tracking-wider text-[color:var(--wb-text-dim)]">
              Artifacts
              {iterationCount > 0 && (
                <span className="ml-1.5 text-[color:var(--wb-accent)]">
                  (iteration {iterationCount})
                </span>
              )}
            </h3>
            {artifacts.map((artifact) => (
              <ArtifactCard key={artifact.id} artifact={artifact} />
            ))}
          </div>
        )}

        {/* Reflection cards from the harness reflect phase */}
        {reflections.length > 0 && (
          <div className="flex flex-col gap-2">
            {reflections.map((reflection) => (
              <ReflectionCard
                key={reflection.id}
                reflection={reflection}
                onApplySuggestion={handleApplySuggestion}
              />
            ))}
          </div>
        )}

        {runningTask && (
          <div
            className={classNames(
              'flex items-center gap-2 rounded-md border border-dashed border-[color:var(--wb-border)] px-3 py-2 text-[12px] text-[color:var(--wb-text-soft)]'
            )}
            aria-live="polite"
          >
            <Loader2 className="h-3.5 w-3.5 animate-spin text-[color:var(--wb-accent)]" />
            <span>
              <span className="text-[color:var(--wb-text-dim)]">Next:&nbsp;</span>
              {runningTask.title}
            </span>
          </div>
        )}

        {buildStatus === 'done' && plan && (
          <div className="rounded-md border border-[color:var(--wb-border)] bg-[color:var(--wb-success-weak)] px-3 py-2 text-[12px] text-[color:var(--wb-success)]">
            Build complete. Canonical model updated with the new plan.
          </div>
        )}

        {error && (
          <div className="rounded-md border border-[color:var(--wb-border)] bg-[color:var(--wb-error-weak)] px-3 py-2 text-[12px] text-[color:var(--wb-error)]">
            {error}
          </div>
        )}
      </div>
    </div>
  );
}
