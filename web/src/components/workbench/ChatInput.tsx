/**
 * Chat input that sits at the bottom of the conversation feed.
 *
 * Auto-grows, submits on ⌘↵, and shows a Stop affordance while a build is in
 * flight. Surfaces the multi-turn autonomous-iteration controls (auto-iterate
 * toggle + max-iteration slider) so users can opt into a Claude-Code-style
 * self-correcting loop. Parent owns the submit handler so the input stays
 * dumb about the underlying stream.
 */

import { useEffect, useRef, useState } from 'react';
import { Paperclip, Repeat, Send, Square } from 'lucide-react';
import { classNames } from '../../lib/utils';
import { isWorkbenchBuildActive, useWorkbenchStore } from '../../lib/workbench-store';

interface ChatInputProps {
  onSubmit: (text: string) => void;
  onCancel?: () => void;
  placeholder?: string;
  /**
   * Externally supplied prefill text. When this value changes to a non-empty
   * string, the composer adopts it as its current value so callers can inject
   * a draft brief (e.g. "Import from Build") without bypassing the internal
   * editable state. Users remain free to edit or clear the prefill before
   * submitting.
   */
  prefill?: string;
}

export function ChatInput({ onSubmit, onCancel, placeholder, prefill }: ChatInputProps) {
  const [value, setValue] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const lastPrefillRef = useRef<string | undefined>(undefined);

  // Adopt an externally provided prefill whenever it changes to a new
  // non-empty value. We key off the raw prefill string (not the current
  // editable value) so repeated clicks of an "Import" button with the same
  // text stay idempotent.
  useEffect(() => {
    if (prefill && prefill !== lastPrefillRef.current) {
      lastPrefillRef.current = prefill;
      setValue(prefill);
      // Focus the textarea so the user can immediately edit the imported
      // brief before sending.
      requestAnimationFrame(() => {
        textareaRef.current?.focus();
        if (textareaRef.current) {
          const end = textareaRef.current.value.length;
          textareaRef.current.setSelectionRange(end, end);
        }
      });
    }
  }, [prefill]);
  const buildStatus = useWorkbenchStore((s) => s.buildStatus);
  const cancelBuild = useWorkbenchStore((s) => s.cancelBuild);
  const autoIterate = useWorkbenchStore((s) => s.autoIterate);
  const setAutoIterate = useWorkbenchStore((s) => s.setAutoIterate);
  const maxIterations = useWorkbenchStore((s) => s.maxIterations);
  const setMaxIterations = useWorkbenchStore((s) => s.setMaxIterations);
  const turnCount = useWorkbenchStore((s) => s.turns.length);
  const isBuilding = isWorkbenchBuildActive(buildStatus);
  const isFollowUp = turnCount > 0;

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
      <div className="mb-2 flex items-center gap-3 text-[11px] text-[color:var(--wb-text-dim)]">
        <label
          className={classNames(
            'inline-flex items-center gap-1.5 rounded-md border px-2 py-1 transition',
            autoIterate
              ? 'border-[color:var(--wb-accent-border)] bg-[color:var(--wb-accent-weak)] text-[color:var(--wb-accent)]'
              : 'border-[color:var(--wb-border)] bg-[color:var(--wb-bg-elev)] text-[color:var(--wb-text-dim)]'
          )}
          title="Let the agent autonomously run corrective iterations after validation."
        >
          <Repeat className="h-3 w-3" />
          <input
            type="checkbox"
            checked={autoIterate}
            onChange={(event) => setAutoIterate(event.target.checked)}
            className="h-3 w-3 cursor-pointer accent-[color:var(--wb-accent)]"
            aria-label="Auto-iterate on validation failures"
          />
          <span>Auto-iterate</span>
        </label>
        <label className="inline-flex items-center gap-1.5">
          <span>Max passes</span>
          <input
            type="number"
            min={1}
            max={6}
            value={maxIterations}
            onChange={(event) => setMaxIterations(Number(event.target.value))}
            className="h-6 w-12 rounded border border-[color:var(--wb-border)] bg-[color:var(--wb-bg-elev)] px-1 text-center text-[11px] text-[color:var(--wb-text)]"
            aria-label="Maximum iterations per turn"
          />
        </label>
        {isFollowUp && (
          <span className="ml-auto inline-flex items-center gap-1 text-[color:var(--wb-text-soft)]">
            Follow-up to turn {turnCount}
          </span>
        )}
      </div>
      <div
        className={classNames(
          'flex items-end gap-2 rounded-lg border border-[color:var(--wb-border)] bg-[color:var(--wb-bg-elev)] px-3 py-2',
          'focus-within:border-[color:var(--wb-border-strong)]'
        )}
      >
        <button
          type="button"
          disabled
          className="mb-0.5 cursor-not-allowed rounded p-1 text-[color:var(--wb-text-muted)]"
          aria-label="Attachments unavailable"
          title="Attachments are not enabled for this harness run yet"
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
          placeholder={
            placeholder ??
            (isFollowUp
              ? 'Send a follow-up to refine the agent…'
              : 'Describe what you\u2019d like me to build')
          }
          aria-label="Build request"
          className="min-h-[22px] flex-1 resize-none bg-transparent text-[13px] leading-5 text-[color:var(--wb-text)] placeholder:text-[color:var(--wb-text-muted)] focus:outline-none"
        />
        {isBuilding ? (
          <button
            type="button"
            onClick={onCancel ?? cancelBuild}
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
              'flex items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition',
              value.trim()
                ? 'bg-[color:var(--wb-accent)] text-[color:var(--wb-accent-fg)] hover:opacity-90'
                : 'bg-[color:var(--wb-bg-hover)] text-[color:var(--wb-text-muted)]'
            )}
            aria-label="Send"
            title="Send (⌘↵)"
          >
            <Send className="h-3.5 w-3.5" />
            {value.trim() ? <span>Send</span> : null}
          </button>
        )}
      </div>
    </div>
  );
}
