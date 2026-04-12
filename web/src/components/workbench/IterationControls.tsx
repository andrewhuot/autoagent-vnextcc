/**
 * IterationControls — panel that appears below the chat input once a build
 * is complete and the user may want to iterate.
 *
 * Features:
 *   - Collapsible list of previous iterations with their messages
 *   - "Iterate" button that pre-fills the chat input with context
 *   - Diff toggle: "Compare with v{N}" — stores the target version in the
 *     store so ArtifactViewer can render a diff tab
 */

import { useState } from 'react';
import { ChevronDown, ChevronUp, GitCompare, RotateCcw } from 'lucide-react';
import { classNames } from '../../lib/utils';
import { useWorkbenchStore } from '../../lib/workbench-store';

interface IterationControlsProps {
  /** Called when the user wants to start an iteration with the given message. */
  onIterate: (message: string) => void;
}

export function IterationControls({ onIterate }: IterationControlsProps) {
  const buildStatus = useWorkbenchStore((s) => s.buildStatus);
  const iterationHistory = useWorkbenchStore((s) => s.iterationHistory);
  const iterationCount = useWorkbenchStore((s) => s.iterationCount);
  const diffTargetVersion = useWorkbenchStore((s) => s.diffTargetVersion);
  const version = useWorkbenchStore((s) => s.version);
  const selectVersionForDiff = useWorkbenchStore((s) => s.selectVersionForDiff);

  const [historyOpen, setHistoryOpen] = useState(false);
  const [iterateMessage, setIterateMessage] = useState('');
  const [showIterateInput, setShowIterateInput] = useState(false);

  // Only render when a build has completed and we're not currently building.
  if (buildStatus !== 'done' && buildStatus !== 'idle') return null;
  // No controls needed if there's been no work yet.
  if (buildStatus === 'idle' && iterationCount === 0) return null;

  const hasPreviousVersions = version > 1;
  const diffActive = diffTargetVersion !== null;

  const handleIterateSubmit = () => {
    const trimmed = iterateMessage.trim();
    if (!trimmed) return;
    onIterate(trimmed);
    setIterateMessage('');
    setShowIterateInput(false);
  };

  const handleDiffToggle = () => {
    if (diffActive) {
      selectVersionForDiff(null);
    } else {
      // Default to comparing with the immediately previous version.
      selectVersionForDiff(Math.max(1, version - 1));
    }
  };

  return (
    <div
      className={classNames(
        'border-t border-[color:var(--wb-border)] bg-[color:var(--wb-bg)]',
        'px-4 py-2.5 text-[12px]'
      )}
      data-testid="iteration-controls"
    >
      {/* Action bar */}
      <div className="flex items-center gap-2">
        {/* Iterate button / inline input toggle */}
        {!showIterateInput ? (
          <button
            type="button"
            onClick={() => setShowIterateInput(true)}
            className={classNames(
              'flex items-center gap-1.5 rounded-md border border-[color:var(--wb-border)]',
              'bg-[color:var(--wb-bg-elev)] px-2.5 py-1 text-[11px] font-medium',
              'text-[color:var(--wb-text)] hover:bg-[color:var(--wb-bg-hover)] transition'
            )}
          >
            <RotateCcw className="h-3 w-3" />
            Iterate
          </button>
        ) : null}

        {/* Diff toggle — only useful when there are previous versions */}
        {hasPreviousVersions && (
          <button
            type="button"
            onClick={handleDiffToggle}
            className={classNames(
              'flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[11px] font-medium transition',
              diffActive
                ? 'border-[color:var(--wb-accent-border)] bg-[color:var(--wb-accent-weak)] text-[color:var(--wb-accent)]'
                : 'border-[color:var(--wb-border)] bg-[color:var(--wb-bg-elev)] text-[color:var(--wb-text-dim)] hover:text-[color:var(--wb-text)] hover:bg-[color:var(--wb-bg-hover)]'
            )}
          >
            <GitCompare className="h-3 w-3" />
            {diffActive
              ? `Comparing v${diffTargetVersion}`
              : `Compare with v${Math.max(1, version - 1)}`}
          </button>
        )}

        {/* Version selector when diff is active */}
        {diffActive && hasPreviousVersions && (
          <div className="flex items-center gap-1">
            {Array.from({ length: version - 1 }, (_, i) => i + 1).map((v) => (
              <button
                key={v}
                type="button"
                onClick={() => selectVersionForDiff(v)}
                className={classNames(
                  'rounded px-1.5 py-0.5 text-[10px] transition',
                  diffTargetVersion === v
                    ? 'bg-[color:var(--wb-accent)] text-[color:var(--wb-accent-fg)]'
                    : 'text-[color:var(--wb-text-dim)] hover:bg-[color:var(--wb-bg-hover)]'
                )}
              >
                v{v}
              </button>
            ))}
          </div>
        )}

        {/* Iteration history toggle */}
        {iterationHistory.length > 0 && (
          <button
            type="button"
            onClick={() => setHistoryOpen((o) => !o)}
            className="ml-auto flex items-center gap-1 text-[color:var(--wb-text-dim)] hover:text-[color:var(--wb-text)] transition"
          >
            {historyOpen ? (
              <ChevronUp className="h-3 w-3" />
            ) : (
              <ChevronDown className="h-3 w-3" />
            )}
            <span className="text-[11px]">
              {iterationHistory.length}{' '}
              {iterationHistory.length === 1 ? 'iteration' : 'iterations'}
            </span>
          </button>
        )}
      </div>

      {/* Inline iterate input */}
      {showIterateInput && (
        <div className="mt-2 flex items-end gap-2">
          <textarea
            rows={2}
            value={iterateMessage}
            onChange={(e) => setIterateMessage(e.target.value)}
            onKeyDown={(e) => {
              if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                e.preventDefault();
                handleIterateSubmit();
              }
              if (e.key === 'Escape') {
                setShowIterateInput(false);
                setIterateMessage('');
              }
            }}
            placeholder="Describe what to change in this iteration…"
            aria-label="Iteration message"
            className={classNames(
              'flex-1 resize-none rounded-md border border-[color:var(--wb-border)]',
              'bg-[color:var(--wb-bg-elev)] px-2.5 py-2 text-[12px]',
              'text-[color:var(--wb-text)] placeholder:text-[color:var(--wb-text-muted)]',
              'focus:border-[color:var(--wb-border-strong)] focus:outline-none',
              'leading-5'
            )}
          />
          <div className="flex shrink-0 flex-col gap-1.5">
            <button
              type="button"
              onClick={handleIterateSubmit}
              disabled={!iterateMessage.trim()}
              className={classNames(
                'rounded-md px-3 py-1.5 text-[11px] font-medium transition',
                iterateMessage.trim()
                  ? 'bg-[color:var(--wb-accent)] text-[color:var(--wb-accent-fg)] hover:opacity-90'
                  : 'bg-[color:var(--wb-bg-hover)] text-[color:var(--wb-text-muted)]'
              )}
            >
              Run
            </button>
            <button
              type="button"
              onClick={() => {
                setShowIterateInput(false);
                setIterateMessage('');
              }}
              className="rounded-md px-3 py-1.5 text-[11px] text-[color:var(--wb-text-dim)] hover:text-[color:var(--wb-text)] transition"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Iteration history */}
      {historyOpen && iterationHistory.length > 0 && (
        <ol className="mt-2 flex flex-col gap-1.5" aria-label="Iteration history">
          {iterationHistory.map((entry) => (
            <li
              key={entry.id}
              className={classNames(
                'flex items-start gap-2 rounded-md border border-[color:var(--wb-border)]',
                'bg-[color:var(--wb-bg-elev)] px-2.5 py-1.5'
              )}
            >
              <span
                className={classNames(
                  'mt-0.5 shrink-0 rounded-full px-1.5 py-0.5',
                  'bg-[color:var(--wb-accent-weak)] text-[10px] font-semibold',
                  'text-[color:var(--wb-accent)]'
                )}
              >
                #{entry.iterationNumber}
              </span>
              <span className="min-w-0 flex-1 leading-5 text-[color:var(--wb-text-soft)] line-clamp-2">
                {entry.message}
              </span>
              <span className="shrink-0 text-[10px] text-[color:var(--wb-text-muted)] tabular-nums">
                {entry.artifactCount} artifacts
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
