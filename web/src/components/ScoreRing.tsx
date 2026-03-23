import { ScoreDisplay } from './ScoreDisplay';

interface ScoreRingProps {
  score: number;
  label: string;
  sublabel?: string;
}

function ringColor(score: number): string {
  if (score >= 80) return '#16a34a';
  if (score >= 60) return '#d97706';
  return '#dc2626';
}

export function ScoreRing({ score, label, sublabel }: ScoreRingProps) {
  const radius = 58;
  const strokeWidth = 10;
  const circumference = 2 * Math.PI * radius;
  const progress = Math.max(0, Math.min(100, score));
  const dashOffset = circumference - (progress / 100) * circumference;

  return (
    <div className="flex items-center gap-6 rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
      <div className="relative h-40 w-40 shrink-0">
        <svg viewBox="0 0 150 150" className="h-full w-full -rotate-90">
          <circle cx="75" cy="75" r={radius} fill="none" stroke="#e5e7eb" strokeWidth={strokeWidth} />
          <circle
            cx="75"
            cy="75"
            r={radius}
            fill="none"
            stroke={ringColor(score)}
            strokeWidth={strokeWidth}
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={dashOffset}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <ScoreDisplay score={score} size="lg" />
          <p className="mt-1 text-xs uppercase tracking-wide text-gray-500">Health</p>
        </div>
      </div>

      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">{label}</p>
        {sublabel && <p className="mt-1 text-sm text-gray-600">{sublabel}</p>}
      </div>
    </div>
  );
}
