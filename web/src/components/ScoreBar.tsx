import { scoreBgColor } from '../lib/utils';

interface ScoreBarProps {
  label: string;
  score: number;
  maxScore?: number;
}

export function ScoreBar({ label, score, maxScore = 100 }: ScoreBarProps) {
  const pct = Math.min((score / maxScore) * 100, 100);
  const bgColor = scoreBgColor(score);

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-sm">
        <span className="text-gray-600">{label}</span>
        <span className="font-medium text-gray-900">{score.toFixed(1)}</span>
      </div>
      <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-300 ${bgColor}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
