interface LoadingSkeletonProps {
  rows?: number;
  className?: string;
}

export function LoadingSkeleton({ rows = 5, className }: LoadingSkeletonProps) {
  return (
    <div className={className || ''}>
      <div className="space-y-3 rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
        {Array.from({ length: rows }).map((_, index) => (
          <div key={index} className="h-4 animate-pulse rounded bg-gray-100" style={{ width: `${90 - index * 8}%` }} />
        ))}
      </div>
    </div>
  );
}
