interface LoadingStateProps {
  lines?: number;
}

export function LoadingState({ lines = 4 }: LoadingStateProps) {
  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
        {Array.from({ length: lines }).map((_, index) => (
          <div
            key={index}
            className="mb-3 h-4 animate-pulse rounded bg-gray-100 last:mb-0"
            style={{ width: `${92 - index * 8}%` }}
          />
        ))}
      </div>
    </div>
  );
}
