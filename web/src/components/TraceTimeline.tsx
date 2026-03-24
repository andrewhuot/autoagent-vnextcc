import type { TraceEvent } from '../lib/types';
import { classNames } from '../lib/utils';

interface TraceTimelineProps {
  events: TraceEvent[];
}

const eventColors: Record<string, string> = {
  model_call: 'bg-blue-500',
  model_response: 'bg-blue-400',
  tool_call: 'bg-green-500',
  tool_response: 'bg-green-400',
  error: 'bg-red-500',
  agent_transfer: 'bg-purple-500',
};

const eventLabels: Record<string, string> = {
  model_call: 'Model Call',
  model_response: 'Model Response',
  tool_call: 'Tool Call',
  tool_response: 'Tool Response',
  error: 'Error',
  agent_transfer: 'Agent Transfer',
};

function formatTimestamp(epoch: number): string {
  return new Date(epoch * 1000).toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

export function TraceTimeline({ events }: TraceTimelineProps) {
  if (events.length === 0) {
    return (
      <div className="py-4 text-center text-sm text-gray-500">
        No events in this trace.
      </div>
    );
  }

  return (
    <div className="relative space-y-0">
      {events.map((event, index) => {
        const isLast = index === events.length - 1;
        const isError = event.event_type === 'error';
        const dotColor = eventColors[event.event_type] || 'bg-gray-400';

        return (
          <div key={event.event_id} className="relative flex gap-3 pb-4">
            {/* Vertical line */}
            {!isLast && (
              <div className="absolute left-[7px] top-4 h-full w-px bg-gray-200" />
            )}

            {/* Dot */}
            <div
              className={classNames(
                'relative z-10 mt-1 h-[15px] w-[15px] shrink-0 rounded-full border-2 border-white',
                dotColor
              )}
            />

            {/* Content */}
            <div
              className={classNames(
                'flex-1 rounded-lg border px-3 py-2',
                isError
                  ? 'border-red-200 bg-red-50'
                  : 'border-gray-200 bg-white'
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span
                    className={classNames(
                      'inline-block rounded px-1.5 py-0.5 text-[11px] font-medium',
                      isError
                        ? 'bg-red-100 text-red-700'
                        : event.event_type.startsWith('model')
                          ? 'bg-blue-100 text-blue-700'
                          : event.event_type.startsWith('tool')
                            ? 'bg-green-100 text-green-700'
                            : 'bg-purple-100 text-purple-700'
                    )}
                  >
                    {eventLabels[event.event_type] || event.event_type}
                  </span>
                  <span className="text-xs text-gray-500">{event.agent_path}</span>
                </div>
                <span className="text-[11px] tabular-nums text-gray-400">
                  {formatTimestamp(event.timestamp)}
                </span>
              </div>

              <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-gray-600">
                {event.latency_ms > 0 && (
                  <span>{event.latency_ms}ms</span>
                )}
                {event.tokens_in !== undefined && (
                  <span>{event.tokens_in} tok in</span>
                )}
                {event.tokens_out !== undefined && (
                  <span>{event.tokens_out} tok out</span>
                )}
                {event.tool_name && (
                  <span className="font-mono text-[11px]">{event.tool_name}</span>
                )}
                {event.error_message && (
                  <span className="text-red-600">{event.error_message}</span>
                )}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
