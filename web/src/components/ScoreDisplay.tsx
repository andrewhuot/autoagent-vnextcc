import { classNames } from '../lib/utils';

interface ScoreDisplayProps {
  score: number;
  size?: 'sm' | 'md' | 'lg';
  showLabel?: boolean;
}

function scoreClass(score: number): string {
  if (score >= 80) return 'text-green-700';
  if (score >= 60) return 'text-amber-700';
  return 'text-red-700';
}

const sizeClass: Record<NonNullable<ScoreDisplayProps['size']>, string> = {
  sm: 'text-sm',
  md: 'text-xl',
  lg: 'text-4xl',
};

export function ScoreDisplay({ score, size = 'md', showLabel = false }: ScoreDisplayProps) {
  return (
    <div className="inline-flex items-baseline gap-2">
      <span className={classNames('font-semibold tabular-nums', sizeClass[size], scoreClass(score))}>
        {score.toFixed(1)}
      </span>
      {showLabel && <span className="text-xs uppercase tracking-wide text-gray-500">score</span>}
    </div>
  );
}
