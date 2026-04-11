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
        <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[color:var(--wb-accent-weak)] text-[11px] font-semibold text-[color:var(--wb-accent)]">
          U
        </div>
        <div
          className={classNames(
            'min-w-0 flex-1 rounded-lg border border-[color:var(--wb-user-bubble-border)] bg-[color:var(--wb-user-bubble-bg)] px-3 py-2 text-[13px] leading-5 text-[color:var(--wb-text)]'
          )}
        >
          {message.text}
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-start gap-2">
      <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[color:var(--wb-bg-hover)] text-[11px] font-semibold text-[color:var(--wb-text-soft)]">
        AI
      </div>
      <div className="min-w-0 flex-1 text-[13px] leading-5 text-[color:var(--wb-text-soft)]">{message.text}</div>
    </div>
  );
}
