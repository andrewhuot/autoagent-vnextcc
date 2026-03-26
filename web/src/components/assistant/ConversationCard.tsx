import { MessageSquare, Clock, Star, AlertCircle } from 'lucide-react';
import { useState } from 'react';
import { classNames, formatTimestamp } from '../../lib/utils';

interface Message {
  role: 'user' | 'assistant';
  content: string;
  timestamp?: number;
  is_failure?: boolean;
}

export interface ConversationData {
  conversation_id: string;
  messages: Message[];
  grade?: number;
  score?: number;
  timestamp: number;
  failure_reason?: string;
  metadata?: {
    duration_ms?: number;
    total_cost?: number;
    model?: string;
  };
}

interface ConversationCardProps {
  data: ConversationData;
}

export function ConversationCard({ data }: ConversationCardProps) {
  const [expanded, setExpanded] = useState(false);

  const gradeColor = (grade: number): string => {
    if (grade >= 80) return 'text-green-600';
    if (grade >= 60) return 'text-amber-600';
    return 'text-red-600';
  };

  const gradeBg = (grade: number): string => {
    if (grade >= 80) return 'bg-green-50';
    if (grade >= 60) return 'bg-amber-50';
    return 'bg-red-50';
  };

  const displayGrade = data.grade ?? data.score ?? 0;
  const visibleMessages = expanded ? data.messages : data.messages.slice(0, 4);
  const hasMore = data.messages.length > 4;

  return (
    <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
      {/* Header */}
      <div className="border-b border-gray-200 bg-gray-50 px-6 py-4">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <MessageSquare className="h-4 w-4 text-gray-400" />
              <span className="font-mono text-xs text-gray-500">{data.conversation_id}</span>
            </div>
            <div className="mt-2 flex items-center gap-3 text-xs text-gray-500">
              <span className="flex items-center gap-1">
                <Clock className="h-3.5 w-3.5" />
                {formatTimestamp(data.timestamp)}
              </span>
              {data.metadata?.duration_ms && (
                <span>{(data.metadata.duration_ms / 1000).toFixed(1)}s</span>
              )}
              {data.metadata?.model && (
                <span className="rounded-md bg-white px-2 py-0.5 text-xs font-mono border border-gray-200">
                  {data.metadata.model}
                </span>
              )}
            </div>
          </div>

          {/* Grade Badge */}
          {displayGrade > 0 && (
            <div className={classNames('rounded-lg px-3 py-2 flex items-center gap-2', gradeBg(displayGrade))}>
              <Star className={classNames('h-4 w-4', gradeColor(displayGrade))} />
              <span className={classNames('text-lg font-bold tabular-nums', gradeColor(displayGrade))}>
                {displayGrade.toFixed(0)}
              </span>
            </div>
          )}
        </div>

        {/* Failure Reason */}
        {data.failure_reason && (
          <div className="mt-3 flex items-start gap-2 rounded-md bg-red-50 px-3 py-2">
            <AlertCircle className="h-4 w-4 text-red-600 flex-shrink-0 mt-0.5" />
            <p className="text-xs text-red-700">{data.failure_reason}</p>
          </div>
        )}
      </div>

      {/* Transcript */}
      <div className="divide-y divide-gray-100">
        {visibleMessages.map((message, idx) => (
          <div
            key={idx}
            className={classNames(
              'px-6 py-4',
              message.is_failure && 'bg-red-50 border-l-4 border-red-400'
            )}
          >
            <div className="flex items-start gap-3">
              <div className={classNames(
                'flex-shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium',
                message.role === 'user' ? 'bg-blue-100 text-blue-700' : 'bg-gray-100 text-gray-700'
              )}>
                {message.role === 'user' ? 'User' : 'Assistant'}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm text-gray-900 whitespace-pre-wrap break-words">
                  {message.content}
                </p>
                {message.timestamp && (
                  <p className="mt-1 text-xs text-gray-400">
                    {formatTimestamp(message.timestamp)}
                  </p>
                )}
              </div>
            </div>
            {message.is_failure && (
              <div className="mt-2 ml-auto">
                <span className="inline-flex items-center gap-1 rounded-md bg-red-100 px-2 py-1 text-xs font-medium text-red-700">
                  <AlertCircle className="h-3 w-3" />
                  Failure point
                </span>
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Expand Toggle */}
      {hasMore && (
        <div className="border-t border-gray-100 bg-gray-50 px-6 py-3">
          <button
            onClick={() => setExpanded(!expanded)}
            className="text-xs font-medium text-gray-600 hover:text-gray-900"
          >
            {expanded ? 'Show less' : `Show ${data.messages.length - 4} more messages`}
          </button>
        </div>
      )}

      {/* Footer Stats */}
      {data.metadata && (
        <div className="border-t border-gray-100 bg-gray-50 px-6 py-3">
          <div className="flex items-center gap-4 text-xs text-gray-500">
            <span>{data.messages.length} messages</span>
            {data.metadata.total_cost !== undefined && (
              <span>${data.metadata.total_cost.toFixed(4)} cost</span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
