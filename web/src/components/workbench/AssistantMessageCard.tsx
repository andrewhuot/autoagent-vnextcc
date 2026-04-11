/**
 * One chat bubble in the conversation feed. Assistant messages are plain
 * text; user messages render as a subtle blue card matching the reference.
 */

import { classNames } from '../../lib/utils';
import type { AssistantMessage } from '../../lib/workbench-store';

interface AssistantMessageCardProps {
  message: AssistantMessage;
  role: 'user' | 'assistant';
}

export function AssistantMessageCard({ message, role }: AssistantMessageCardProps) {
  if (role === 'user') {
    return (
      <div className="flex items-start gap-2">
        <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[color:var(--wb-accent)]/20 text-[11px] font-semibold text-[color:var(--wb-accent)]">
          U
        </div>
        <div
          className={classNames(
            'min-w-0 flex-1 rounded-lg border border-[color:var(--wb-border)] bg-white/[0.02] px-3 py-2 text-[13px] leading-5 text-neutral-100'
          )}
        >
          {message.text}
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-start gap-2">
      <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-white/5 text-[11px] font-semibold text-neutral-300">
        AI
      </div>
      <div className="min-w-0 flex-1 text-[13px] leading-5 text-neutral-200">{message.text}</div>
    </div>
  );
}
