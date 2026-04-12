import { useState } from 'react';
import { Activity } from 'lucide-react';
import { useUnifiedEvents } from '../lib/api';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { PageHeader } from '../components/PageHeader';
import { formatTimestamp } from '../lib/utils';

export function EventLogPage() {
  const [eventType, setEventType] = useState('');
  const [source, setSource] = useState<'all' | 'system' | 'builder'>('all');
  const events = useUnifiedEvents({
    limit: 200,
    source,
  });
  const filteredEvents = (events.data?.events ?? []).filter((entry) => {
    const filter = eventType.trim();
    return !filter || entry.event_type.includes(filter);
  });
  const continuity = events.data?.continuity;

  return (
    <div className="space-y-6">
      <PageHeader
        title="System Event Log"
        description="Unified durable timeline for system events and builder events that remains available after restart."
      />

      <section className="rounded-lg border border-gray-200 bg-white p-4">
        <div className="mb-4">
          <p className="text-sm font-semibold text-gray-900">Unified durable timeline</p>
          <p className="mt-1 text-sm leading-6 text-gray-600">
            System and builder events are merged from persisted stores so restart history remains visible.
          </p>
        </div>
        <div className="grid gap-3 md:grid-cols-[1fr_220px]">
          <div>
            <label className="mb-1 block text-xs text-gray-500">Filter by event type</label>
            <input
              value={eventType}
              onChange={(event) => setEventType(event.target.value)}
              placeholder="candidate_promoted"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-gray-500">Source</label>
            <select
              value={source}
              onChange={(event) => setSource(event.target.value as 'all' | 'system' | 'builder')}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            >
              <option value="all">System and builder</option>
              <option value="system">System only</option>
              <option value="builder">Builder only</option>
            </select>
          </div>
        </div>
        {continuity && (
          <div className="mt-4 rounded-lg border border-sky-200 bg-sky-50 px-4 py-3">
            <p className="text-sm font-semibold text-sky-900">{continuity.label}</p>
            <p className="mt-1 text-sm leading-6 text-sky-800">{continuity.detail}</p>
          </div>
        )}
      </section>

      {events.isLoading ? (
        <LoadingSkeleton rows={8} />
      ) : filteredEvents.length > 0 ? (
        <section className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="space-y-2">
            {filteredEvents.map((entry) => (
              <div key={entry.id} className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <Activity className="h-3.5 w-3.5 text-gray-500" />
                    <p className="text-sm font-medium text-gray-900">{entry.event_type}</p>
                    <span className="rounded-full border border-gray-200 bg-white px-2 py-0.5 text-[11px] font-medium text-gray-600">
                      {entry.source}
                    </span>
                  </div>
                  <p className="text-xs text-gray-500">{formatTimestamp(entry.timestamp)}</p>
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-gray-600">
                  {entry.session_id && <span>session: {entry.session_id}</span>}
                  {entry.source_label && <span>{entry.source_label}</span>}
                  {entry.continuity_state && <span>{entry.continuity_state}</span>}
                </div>
                {Object.keys(entry.payload || {}).length > 0 && (
                  <pre className="mt-2 overflow-x-auto rounded-md border border-gray-200 bg-white p-2 text-[11px] text-gray-700">
                    {JSON.stringify(entry.payload, null, 2)}
                  </pre>
                )}
              </div>
            ))}
          </div>
        </section>
      ) : (
        <section className="rounded-lg border border-dashed border-gray-200 bg-gray-50 p-8 text-center text-sm text-gray-500">
          No events found for the current filter.
        </section>
      )}
    </div>
  );
}
