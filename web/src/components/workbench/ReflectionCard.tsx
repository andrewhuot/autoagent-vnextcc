/**
 * ReflectionCard — shown inline in the conversation feed after a task group
 * completes. Displays the quality score as a small ring, any suggestions,
 * and an "Apply suggestion" button that triggers an iteration.
 */

import { Sparkles } from 'lucide-react';
import { classNames, scoreColor } from '../../lib/utils';
import type { ReflectionEntry } from '../../lib/workbench-api';

// ---------------------------------------------------------------------------
// Score ring (SVG)
// ---------------------------------------------------------------------------

interface ScoreRingProps {
  score: number;
}

function ScoreRing({ score }: ScoreRingProps) {
  const radius = 16;
  const circumference = 2 * Math.PI * radius;
  const clamped = Math.max(0, Math.min(100, score));
  const dashOffset = circumference * (1 - clamped / 100);

  let strokeColor = '#dc2626'; // red
  if (clamped >= 80) strokeColor = '#059669'; // emerald
  else if (clamped >= 60) strokeColor = '#d97706'; // amber

  return (
    <svg
      width="40"
      height="40"
      viewBox="0 0 40 40"
      aria-hidden="true"
      className="shrink-0"
    >
      {/* Track */}
      <circle
        cx="20"
        cy="20"
        r={radius}
        fill="none"
        stroke="var(--wb-bg-hover)"
        strokeWidth="3"
      />
      {/* Fill */}
      <circle
        cx="20"
        cy="20"
        r={radius}
        fill="none"
        stroke={strokeColor}
        strokeWidth="3"
        strokeLinecap="round"
        strokeDasharray={circumference}
        strokeDashoffset={dashOffset}
        transform="rotate(-90 20 20)"
        style={{ transition: 'stroke-dashoffset 0.5s ease-in-out' }}
      />
      {/* Label */}
      <text
        x="20"
        y="24"
        textAnchor="middle"
        fontSize="10"
        fontWeight="600"
        fill="var(--wb-text)"
        fontFamily="var(--font-sans)"
      >
        {clamped}
      </text>
    </svg>
  );
}

function normalizeQualityScore(score: number): number {
  if (!Number.isFinite(score)) return 0;
  const scaled = score >= 0 && score <= 1 ? score * 100 : score;
  return Math.round(Math.max(0, Math.min(100, scaled)));
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface ReflectionCardProps {
  reflection: ReflectionEntry;
  /** Called when the user clicks "Apply suggestion" with the suggestion text. */
  onApplySuggestion: (suggestion: string) => void;
}

export function ReflectionCard({ reflection, onApplySuggestion }: ReflectionCardProps) {
  const { qualityScore, suggestions } = reflection;
  const displayScore = normalizeQualityScore(qualityScore);

  return (
    <div
      className={classNames(
        'rounded-lg border border-[color:var(--wb-border)]',
        'bg-[color:var(--wb-bg-elev)] p-3'
      )}
      data-testid="reflection-card"
    >
      {/* Header row */}
      <div className="flex items-center gap-3">
        <ScoreRing score={displayScore} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <Sparkles className="h-3 w-3 text-[color:var(--wb-accent)]" />
            <span className="text-[12px] font-semibold text-[color:var(--wb-text)]">
              Reflection
            </span>
          </div>
          <p className={classNames('text-[11px]', scoreColor(displayScore))}>
            Quality score: {displayScore}/100
          </p>
        </div>
      </div>

      {/* Suggestions */}
      {suggestions.length > 0 && (
        <ul className="mt-2.5 flex flex-col gap-1.5">
          {suggestions.map((suggestion, index) => (
            <li
              key={index}
              className={classNames(
                'flex items-start justify-between gap-2',
                'rounded-md border border-[color:var(--wb-border)]',
                'bg-[color:var(--wb-bg)] px-2.5 py-2'
              )}
            >
              <span className="flex-1 text-[12px] leading-5 text-[color:var(--wb-text-soft)]">
                {suggestion}
              </span>
              <button
                type="button"
                onClick={() => onApplySuggestion(suggestion)}
                className={classNames(
                  'shrink-0 rounded-md border border-[color:var(--wb-accent-border)]',
                  'bg-[color:var(--wb-accent-weak)] px-2 py-0.5',
                  'text-[10px] font-medium text-[color:var(--wb-accent)]',
                  'hover:bg-[color:var(--wb-accent)] hover:text-[color:var(--wb-accent-fg)] transition'
                )}
              >
                Apply
              </button>
            </li>
          ))}
        </ul>
      )}

      {suggestions.length === 0 && (
        <p className="mt-2 text-[11px] text-[color:var(--wb-text-dim)]">
          No suggestions — the output looks good.
        </p>
      )}
    </div>
  );
}
