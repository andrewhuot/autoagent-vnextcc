import { Clock3 } from 'lucide-react';
import { StatusBadge } from './StatusBadge';
import { formatTimestamp, statusVariant } from '../lib/utils';

interface TimelineEntryProps {
  timestamp: string;
  title: string;
  description?: string;
  status: string;
}

export function TimelineEntry({ timestamp, title, description, status }: TimelineEntryProps) {
  return (
    <div className="relative pl-6">
      <span className="absolute left-0 top-2 h-2 w-2 rounded-full bg-blue-500" />
      <div className="rounded-lg border border-gray-200 bg-white px-4 py-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-sm font-semibold text-gray-900">{title}</p>
            {description && <p className="mt-1 text-sm text-gray-600">{description}</p>}
          </div>
          <StatusBadge variant={statusVariant(status)} label={status.replaceAll('_', ' ')} />
        </div>
        <div className="mt-2 flex items-center gap-1 text-xs text-gray-500">
          <Clock3 className="h-3 w-3" />
          <span>{formatTimestamp(timestamp)}</span>
        </div>
      </div>
    </div>
  );
}
