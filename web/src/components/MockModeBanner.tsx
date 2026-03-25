import { useEffect, useState } from 'react';
import { AlertTriangle } from 'lucide-react';

export function MockModeBanner() {
  const [isMockMode, setIsMockMode] = useState(false);

  useEffect(() => {
    // Check if we're in mock mode by checking if the API returns mock data
    fetch('/api/health')
      .then((res) => res.json())
      .then((data) => {
        // Check for mock mode indicator in response
        if (data?.mock_mode === true || data?.source === 'mock') {
          setIsMockMode(true);
        }
      })
      .catch(() => {
        // If API fails, assume we're potentially in mock mode
        // This is conservative - real apps would have better detection
      });
  }, []);

  if (!isMockMode) return null;

  return (
    <div className="sticky top-0 z-50 flex items-center justify-center gap-2 border-b border-amber-300 bg-amber-50 px-4 py-2.5 text-sm font-medium text-amber-900">
      <AlertTriangle className="h-4 w-4" />
      <span>Mock Mode Active - using simulated data</span>
    </div>
  );
}
