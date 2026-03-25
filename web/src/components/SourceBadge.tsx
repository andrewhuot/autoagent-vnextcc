import { Database, Wifi } from 'lucide-react';
import { classNames } from '../lib/utils';

interface SourceBadgeProps {
  source?: 'mock' | 'live';
}

export function SourceBadge({ source = 'live' }: SourceBadgeProps) {
  const isMock = source === 'mock';

  return (
    <span
      className={classNames(
        'inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium',
        isMock
          ? 'bg-amber-50 text-amber-700 border border-amber-200'
          : 'bg-green-50 text-green-700 border border-green-200'
      )}
    >
      {isMock ? <Database className="h-2.5 w-2.5" /> : <Wifi className="h-2.5 w-2.5" />}
      {isMock ? 'mock' : 'live'}
    </span>
  );
}
