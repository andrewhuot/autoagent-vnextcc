/**
 * Composer that sits at the bottom of the conversation feed.
 *
 * Claude-Code-style — supports two modes:
 *   • "Build" — submits a build brief or follow-up that drives the agent
 *     coordinator (LLM-driven config edits + artifact generation).
 *   • "Chat" — sends the message to the candidate agent itself for testing.
 *
 * Auto-grows, supports slash commands via a floating palette, ↑/↓ history
 * recall, ⌘K focus from anywhere, and ⌘↵ / ⏎ to send. Stop appears while a
 * stream is in flight. Parent owns the actual submit handlers.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { MessageSquare, Repeat, Send, Sparkles, Square } from 'lucide-react';
import { classNames } from '../../lib/utils';
import {
  isWorkbenchBuildActive,
  useWorkbenchStore,
  type ComposerMode,
} from '../../lib/workbench-store';
import {
  filterSlashCommands,
  SlashCommandPalette,
  type SlashCommand,
} from './SlashCommandPalette';

interface ChatInputProps {
  /** Submit handler for a build / iteration brief. */
  onSubmit: (text: string) => void;
  /** Submit handler for a chat-with-agent message (test the candidate). */
  onChat?: (text: string) => void;
  /** Cancels whichever stream is currently active for the active mode. */
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

export function ChatInput({ onSubmit, onChat, onCancel, placeholder, prefill }: ChatInputProps) {
  const [value, setValue] = useState('');
  const [paletteIndex, setPaletteIndex] = useState(0);
  const [historyCursor, setHistoryCursor] = useState<number | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const lastPrefillRef = useRef<string | undefined>(undefined);

  const buildStatus = useWorkbenchStore((s) => s.buildStatus);
  const chatStatus = useWorkbenchStore((s) => s.chatStatus);
  const cancelBuild = useWorkbenchStore((s) => s.cancelBuild);
  const cancelChat = useWorkbenchStore((s) => s.cancelChat);
  const autoIterate = useWorkbenchStore((s) => s.autoIterate);
  const setAutoIterate = useWorkbenchStore((s) => s.setAutoIterate);
  const maxIterations = useWorkbenchStore((s) => s.maxIterations);
  const setMaxIterations = useWorkbenchStore((s) => s.setMaxIterations);
  const turnCount = useWorkbenchStore((s) => s.turns.length);
  const composerMode = useWorkbenchStore((s) => s.composerMode);
  const setComposerMode = useWorkbenchStore((s) => s.setComposerMode);
  const setActiveWorkspaceTab = useWorkbenchStore((s) => s.setActiveWorkspaceTab);
  const composerHistory = useWorkbenchStore((s) => s.composerHistory);
  const pushComposerHistory = useWorkbenchStore((s) => s.pushComposerHistory);
  const resetChat = useWorkbenchStore((s) => s.resetChat);
  const canonicalAgents = useWorkbenchStore((s) => s.canonicalModel?.agents.length ?? 0);

  const isBuilding = isWorkbenchBuildActive(buildStatus);
  const isChatting = chatStatus === 'streaming';
  const isStreaming = composerMode === 'build' ? isBuilding : isChatting;
  const isFollowUp = turnCount > 0;
  const chatDisabled = canonicalAgents === 0;

  // Adopt an externally provided prefill whenever it changes to a new
  // non-empty value. Keyed off the raw prefill string (not the current
  // editable value) so repeated clicks of an "Import" button stay idempotent.
  useEffect(() => {
    if (prefill && prefill !== lastPrefillRef.current) {
      lastPrefillRef.current = prefill;
      setValue(prefill);
      requestAnimationFrame(() => {
        textareaRef.current?.focus();
        if (textareaRef.current) {
          const end = textareaRef.current.value.length;
          textareaRef.current.setSelectionRange(end, end);
        }
      });
    }
  }, [prefill]);

  // Auto-grow the textarea up to 200px.
  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = 'auto';
    textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`;
  }, [value]);

  const showPalette = value.startsWith('/') && !value.includes(' ');
  const filteredCommands = useMemo(
    () => (showPalette ? filterSlashCommands(value) : []),
    [showPalette, value]
  );

  // Keep the palette index in range as the user types.
  useEffect(() => {
    if (paletteIndex >= filteredCommands.length) {
      setPaletteIndex(0);
    }
  }, [filteredCommands.length, paletteIndex]);

  const dispatchSlashCommand = (cmd: SlashCommand, rest: string) => {
    setValue('');
    setPaletteIndex(0);
    setHistoryCursor(null);
    switch (cmd.name) {
      case 'build':
        setComposerMode('build');
        if (rest.trim()) onSubmit(rest.trim());
        else textareaRef.current?.focus();
        return;
      case 'chat':
        setComposerMode('chat');
        if (rest.trim() && onChat) onChat(rest.trim());
        else textareaRef.current?.focus();
        return;
      case 'config':
        setActiveWorkspaceTab('config');
        return;
      case 'agent':
        setActiveWorkspaceTab('agent');
        return;
      case 'evals':
        setActiveWorkspaceTab('evals');
        return;
      case 'reset':
        resetChat();
        return;
      case 'clear':
        // The page-level reset is owned by AgentWorkbench; emit a synthetic
        // submit with the slash so the consumer can route it.
        onSubmit('/clear');
        return;
      case 'help':
        setActiveWorkspaceTab('activity');
        return;
    }
  };

  const handleSubmit = () => {
    const trimmed = value.trim();
    if (!trimmed || isStreaming) return;

    // Slash command shortcut — applied before mode-aware send.
    if (trimmed.startsWith('/')) {
      const [head, ...rest] = trimmed.split(' ');
      const name = head.slice(1).toLowerCase();
      const cmd = filterSlashCommands('/' + name).find((c) => c.name === name);
      if (cmd) {
        dispatchSlashCommand(cmd, rest.join(' '));
        return;
      }
    }

    pushComposerHistory(trimmed);
    setHistoryCursor(null);
    setValue('');

    if (composerMode === 'chat' && onChat) {
      if (chatDisabled) return;
      onChat(trimmed);
    } else {
      onSubmit(trimmed);
    }
  };

  const recallHistory = (direction: -1 | 1) => {
    if (composerHistory.length === 0) return;
    const lastIndex = composerHistory.length - 1;
    let next: number;
    if (historyCursor === null) {
      next = direction === -1 ? lastIndex : 0;
    } else {
      next = historyCursor + direction;
    }
    if (next < 0 || next > lastIndex) {
      setHistoryCursor(null);
      setValue('');
      return;
    }
    setHistoryCursor(next);
    setValue(composerHistory[next]);
  };

  const placeholderText =
    placeholder ??
    (composerMode === 'chat'
      ? chatDisabled
        ? 'Build an agent first to start chatting'
        : 'Send a message to test the agent…'
      : isFollowUp
        ? 'Send a follow-up to refine the agent…'
        : 'Describe what you\u2019d like me to build');

  const stopHandler = () => {
    if (composerMode === 'chat') {
      if (onCancel) onCancel();
      else cancelChat();
    } else {
      if (onCancel) onCancel();
      else cancelBuild();
    }
  };

  return (
    <div className="border-t border-[color:var(--wb-border)] bg-[color:var(--wb-bg)] px-4 py-3">
      <ComposerHeader
        mode={composerMode}
        onModeChange={(m) => {
          setComposerMode(m);
          textareaRef.current?.focus();
        }}
        chatDisabled={chatDisabled}
        autoIterate={autoIterate}
        setAutoIterate={setAutoIterate}
        maxIterations={maxIterations}
        setMaxIterations={setMaxIterations}
        isFollowUp={isFollowUp}
        turnCount={turnCount}
      />

      <div
        className={classNames(
          'relative flex items-end gap-2 rounded-lg border border-[color:var(--wb-border)] bg-[color:var(--wb-bg-elev)] px-3 py-2',
          'focus-within:border-[color:var(--wb-border-strong)]',
          composerMode === 'chat'
            ? 'focus-within:ring-1 focus-within:ring-[color:var(--wb-success)]'
            : 'focus-within:ring-1 focus-within:ring-[color:var(--wb-accent)]'
        )}
      >
        {showPalette && filteredCommands.length > 0 && (
          <SlashCommandPalette
            query={value}
            selectedIndex={paletteIndex}
            onIndexChange={setPaletteIndex}
            onSelect={(cmd) => {
              const rest = value.slice(cmd.name.length + 1).trim();
              dispatchSlashCommand(cmd, rest);
            }}
          />
        )}

        <span
          className={classNames(
            'mb-1 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded text-[color:var(--wb-text-dim)]',
            composerMode === 'chat' ? 'text-[color:var(--wb-success)]' : 'text-[color:var(--wb-accent)]'
          )}
          aria-hidden
        >
          {composerMode === 'chat' ? <MessageSquare className="h-3.5 w-3.5" /> : <Sparkles className="h-3.5 w-3.5" />}
        </span>

        <textarea
          ref={textareaRef}
          rows={1}
          value={value}
          onChange={(event) => {
            setValue(event.target.value);
            if (historyCursor !== null) setHistoryCursor(null);
          }}
          onKeyDown={(event) => {
            // Slash palette navigation
            if (showPalette && filteredCommands.length > 0) {
              if (event.key === 'ArrowDown') {
                event.preventDefault();
                setPaletteIndex((i) => Math.min(filteredCommands.length - 1, i + 1));
                return;
              }
              if (event.key === 'ArrowUp') {
                event.preventDefault();
                setPaletteIndex((i) => Math.max(0, i - 1));
                return;
              }
              if (event.key === 'Tab' || (event.key === 'Enter' && !event.shiftKey)) {
                event.preventDefault();
                const cmd = filteredCommands[paletteIndex];
                if (cmd) {
                  const rest = value.slice(cmd.name.length + 1).trim();
                  dispatchSlashCommand(cmd, rest);
                }
                return;
              }
              if (event.key === 'Escape') {
                event.preventDefault();
                setValue('');
                return;
              }
            }

            // History recall — only when the textarea is empty or the cursor
            // is already in history mode, so editing a draft isn't disrupted.
            if (
              event.key === 'ArrowUp' &&
              !event.shiftKey &&
              !event.metaKey &&
              !event.ctrlKey &&
              (value.length === 0 || historyCursor !== null)
            ) {
              event.preventDefault();
              recallHistory(-1);
              return;
            }
            if (
              event.key === 'ArrowDown' &&
              !event.shiftKey &&
              !event.metaKey &&
              !event.ctrlKey &&
              historyCursor !== null
            ) {
              event.preventDefault();
              recallHistory(1);
              return;
            }

            if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
              event.preventDefault();
              handleSubmit();
            }
            if (event.key === 'Enter' && !event.shiftKey && !event.metaKey && !event.ctrlKey) {
              event.preventDefault();
              handleSubmit();
            }
          }}
          placeholder={placeholderText}
          aria-label={composerMode === 'chat' ? 'Test the agent' : 'Build request'}
          disabled={composerMode === 'chat' && chatDisabled}
          className="min-h-[22px] flex-1 resize-none bg-transparent text-[13px] leading-5 text-[color:var(--wb-text)] placeholder:text-[color:var(--wb-text-muted)] focus:outline-none disabled:cursor-not-allowed"
        />
        {isStreaming ? (
          <button
            type="button"
            onClick={stopHandler}
            className="flex h-8 w-8 items-center justify-center rounded-md bg-[color:var(--wb-error-weak)] text-[color:var(--wb-error)] hover:opacity-90"
            aria-label="Stop"
            title="Stop"
          >
            <Square className="h-3.5 w-3.5" />
          </button>
        ) : (
          <button
            type="button"
            onClick={handleSubmit}
            disabled={!value.trim() || (composerMode === 'chat' && chatDisabled)}
            className={classNames(
              'flex items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition',
              !value.trim() || (composerMode === 'chat' && chatDisabled)
                ? 'bg-[color:var(--wb-bg-hover)] text-[color:var(--wb-text-muted)]'
                : composerMode === 'chat'
                  ? 'bg-[color:var(--wb-success)] text-white hover:opacity-90'
                  : 'bg-[color:var(--wb-accent)] text-[color:var(--wb-accent-fg)] hover:opacity-90'
            )}
            aria-label="Send"
            title="Send (⌘↵)"
          >
            <Send className="h-3.5 w-3.5" />
            <span>{composerMode === 'chat' ? 'Send' : 'Send'}</span>
          </button>
        )}
      </div>

      <div className="mt-1.5 flex items-center justify-between text-[10px] text-[color:var(--wb-text-dim)]">
        <span>
          {composerMode === 'chat' ? (
            chatDisabled ? (
              <>Build an agent first — chat will reach the candidate.</>
            ) : (
              <>Chatting with the candidate agent. Replies stream live.</>
            )
          ) : (
            <>
              ⏎ to send · / for commands · ↑ recall last · ⌘K focus
            </>
          )}
        </span>
        <span className="font-mono text-[color:var(--wb-text-muted)]">
          {composerMode === 'chat' ? 'chat' : 'build'} mode
        </span>
      </div>
    </div>
  );
}

function ComposerHeader({
  mode,
  onModeChange,
  chatDisabled,
  autoIterate,
  setAutoIterate,
  maxIterations,
  setMaxIterations,
  isFollowUp,
  turnCount,
}: {
  mode: ComposerMode;
  onModeChange: (mode: ComposerMode) => void;
  chatDisabled: boolean;
  autoIterate: boolean;
  setAutoIterate: (v: boolean) => void;
  maxIterations: number;
  setMaxIterations: (n: number) => void;
  isFollowUp: boolean;
  turnCount: number;
}) {
  return (
    <div className="mb-2 flex flex-wrap items-center gap-2 text-[11px] text-[color:var(--wb-text-dim)]">
      <div
        role="tablist"
        aria-label="Composer mode"
        className="inline-flex items-center rounded-md border border-[color:var(--wb-border)] bg-[color:var(--wb-bg-elev)] p-0.5"
      >
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'build'}
          onClick={() => onModeChange('build')}
          className={classNames(
            'inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px] transition',
            mode === 'build'
              ? 'bg-[color:var(--wb-accent-weak)] text-[color:var(--wb-accent)]'
              : 'text-[color:var(--wb-text-dim)] hover:text-[color:var(--wb-text)]'
          )}
        >
          <Sparkles className="h-3 w-3" /> Build
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'chat'}
          disabled={chatDisabled}
          onClick={() => onModeChange('chat')}
          title={chatDisabled ? 'Build an agent before chatting' : 'Chat with the candidate agent'}
          className={classNames(
            'inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px] transition',
            mode === 'chat'
              ? 'bg-[color:var(--wb-success-weak)] text-[color:var(--wb-success)]'
              : 'text-[color:var(--wb-text-dim)] hover:text-[color:var(--wb-text)]',
            chatDisabled && 'cursor-not-allowed opacity-50'
          )}
        >
          <MessageSquare className="h-3 w-3" /> Chat
        </button>
      </div>

      {mode === 'build' && (
        <>
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
        </>
      )}
    </div>
  );
}
