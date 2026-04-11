/**
 * Chat input that sits at the bottom of the conversation feed.
 *
 * Auto-grows, submits on ⌘↵, and shows a Stop affordance while a build is in
 * flight. Parent owns the submit handler so the input stays dumb.
 */

import { useEffect, useRef, useState } from 'react';
import { Paperclip, Send, Square } from 'lucide-react';
import { classNames } from '../../lib/utils';
import { useWorkbenchStore } from '../../lib/workbench-store';

interface ChatInputProps {
  onSubmit: (text: string) => void;
  placeholder?: string;
}

export function ChatInput({ onSubmit, placeholder = 'Describe what you\u2019d like me to build' }: ChatInputProps) {
  const [value, setValue] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const buildStatus = useWorkbenchStore((s) => s.buildStatus);
  const cancelBuild = useWorkbenchStore((s) => s.cancelBuild);
  const isBuilding = buildStatus === 'running' || buildStatus === 'starting';

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = 'auto';
    textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`;
  }, [value]);

  const handleSubmit = () => {
    const trimmed = value.trim();
    if (!trimmed || isBuilding) return;
    onSubmit(trimmed);
    setValue('');
  };

  return (
    <div className="border-t border-[color:var(--wb-border)] bg-[color:var(--wb-bg)] px-4 py-3">
      <div
        className={classNames(
          'flex items-end gap-2 rounded-lg border border-[color:var(--wb-border)] bg-[color:var(--wb-bg-elev)] px-3 py-2',
          'focus-within:border-[color:var(--wb-border-strong)]'
        )}
      >
        <button
          type="button"
          className="mb-0.5 rounded p-1 text-[color:var(--wb-text-dim)] hover:bg-[color:var(--wb-bg-hover)] hover:text-[color:var(--wb-text)]"
          aria-label="Attach"
          tabIndex={-1}
        >
          <Paperclip className="h-4 w-4" />
        </button>
        <textarea
          ref={textareaRef}
          rows={1}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
              event.preventDefault();
              handleSubmit();
            }
            if (event.key === 'Enter' && !event.shiftKey && !event.metaKey && !event.ctrlKey) {
              event.preventDefault();
              handleSubmit();
            }
          }}
          placeholder={placeholder}
          aria-label="Build request"
          className="min-h-[22px] flex-1 resize-none bg-transparent text-[13px] leading-5 text-[color:var(--wb-text)] placeholder:text-[color:var(--wb-text-muted)] focus:outline-none"
        />
        {isBuilding ? (
          <button
            type="button"
            onClick={cancelBuild}
            className="flex h-8 w-8 items-center justify-center rounded-md bg-[color:var(--wb-error-weak)] text-[color:var(--wb-error)] hover:opacity-90"
            aria-label="Stop build"
            title="Stop build"
          >
            <Square className="h-3.5 w-3.5" />
          </button>
        ) : (
          <button
            type="button"
            onClick={handleSubmit}
            disabled={!value.trim()}
            className={classNames(
              'flex h-8 w-8 items-center justify-center rounded-md transition',
              value.trim()
                ? 'bg-[color:var(--wb-accent)] text-[color:var(--wb-accent-fg)] hover:opacity-90'
                : 'bg-[color:var(--wb-bg-hover)] text-[color:var(--wb-text-muted)]'
            )}
            aria-label="Send"
            title="Send (⌘↵)"
          >
            <Send className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
    </div>
  );
}
