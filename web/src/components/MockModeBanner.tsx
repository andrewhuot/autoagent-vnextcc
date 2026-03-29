import { useEffect, useState } from 'react';
import { AlertTriangle } from 'lucide-react';

export function MockModeBanner() {
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    fetch('/api/health')
      .then((res) => res.json())
      .then((data) => {
        const reasons = Array.isArray(data?.mock_reasons)
          ? data.mock_reasons.filter(
              (value: unknown): value is string => typeof value === 'string' && value.trim().length > 0
            )
          : [];

        if (data?.mock_mode === true || reasons.length > 0) {
          setMessage(reasons[0] ?? 'Mock mode active - using simulated components.');
        }
      })
      .catch(() => {
        setMessage(null);
      });
  }, []);

  if (!message) return null;

  return (
    <div className="sticky top-0 z-50 flex items-center justify-center gap-2 border-b border-amber-300 bg-amber-50 px-4 py-2.5 text-sm font-medium text-amber-900">
      <AlertTriangle className="h-4 w-4" />
      <span>{message}</span>
    </div>
  );
}
