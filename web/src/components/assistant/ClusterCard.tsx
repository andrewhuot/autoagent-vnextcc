import { AlertCircle, TrendingUp, TrendingDown, Minus, MessageSquare, ExternalLink } from 'lucide-react';
import { LineChart, Line, ResponsiveContainer } from 'recharts';
import { classNames } from '../../lib/utils';

export interface ClusterData {
  cluster_id: string;
  title: string;
  description: string;
  impact_score: number;
  rank: number;
  conversation_count: number;
  severity: 'critical' | 'high' | 'medium' | 'low';
  trend: 'increasing' | 'stable' | 'decreasing';
  trend_data?: number[];
  example_conversation_ids: string[];
  root_cause?: string;
  suggested_fix?: string;
}

interface ClusterCardProps {
  data: ClusterData;
  onViewConversation?: (conversationId: string) => void;
}

export function ClusterCard({ data, onViewConversation }: ClusterCardProps) {
  const severityConfig = {
    critical: { color: 'text-red-700', bg: 'bg-red-50', border: 'border-red-200' },
    high: { color: 'text-amber-700', bg: 'bg-amber-50', border: 'border-amber-200' },
    medium: { color: 'text-yellow-700', bg: 'bg-yellow-50', border: 'border-yellow-200' },
    low: { color: 'text-gray-700', bg: 'bg-gray-50', border: 'border-gray-200' },
  };

  const config = severityConfig[data.severity];

  const trendIcon = () => {
    if (data.trend === 'increasing') return <TrendingUp className="h-4 w-4 text-red-600" />;
    if (data.trend === 'decreasing') return <TrendingDown className="h-4 w-4 text-green-600" />;
    return <Minus className="h-4 w-4 text-gray-400" />;
  };

  const trendLabel = () => {
    if (data.trend === 'increasing') return 'Increasing';
    if (data.trend === 'decreasing') return 'Decreasing';
    return 'Stable';
  };

  const trendColor = () => {
    if (data.trend === 'increasing') return 'text-red-600';
    if (data.trend === 'decreasing') return 'text-green-600';
    return 'text-gray-600';
  };

  return (
    <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
      {/* Header */}
      <div className="border-b border-gray-200 px-6 py-4">
        <div className="flex items-start gap-3">
          <div className={classNames('rounded-lg p-2', config.bg)}>
            <AlertCircle className={classNames('h-5 w-5', config.color)} />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="rounded-md bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">
                #{data.rank}
              </span>
              <span className={classNames('rounded-md border px-2 py-0.5 text-xs font-medium uppercase', config.bg, config.color, config.border)}>
                {data.severity}
              </span>
            </div>
            <h3 className="mt-2 text-sm font-medium text-gray-900">{data.title}</h3>
            <p className="mt-1 text-sm text-gray-600">{data.description}</p>
          </div>
        </div>
      </div>

      {/* Impact & Trend */}
      <div className="border-b border-gray-100 px-6 py-4">
        <div className="grid grid-cols-2 gap-6">
          {/* Impact Score */}
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-gray-500">Impact Score</p>
            <div className="mt-2 flex items-baseline gap-2">
              <span className={classNames(
                'text-2xl font-bold tabular-nums',
                data.impact_score >= 75 ? 'text-red-600' :
                data.impact_score >= 50 ? 'text-amber-600' : 'text-yellow-600'
              )}>
                {data.impact_score}
              </span>
              <span className="text-sm text-gray-400">/ 100</span>
            </div>
            <div className="mt-2 h-2 overflow-hidden rounded-full bg-gray-100">
              <div
                className={classNames(
                  'h-full rounded-full transition-all duration-500',
                  data.impact_score >= 75 ? 'bg-red-500' :
                  data.impact_score >= 50 ? 'bg-amber-500' : 'bg-yellow-500'
                )}
                style={{ width: `${data.impact_score}%` }}
              />
            </div>
          </div>

          {/* Trend */}
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-gray-500">Trend</p>
            <div className="mt-2 flex items-center gap-2">
              {trendIcon()}
              <span className={classNames('text-lg font-semibold', trendColor())}>
                {trendLabel()}
              </span>
            </div>
            {data.trend_data && data.trend_data.length > 1 && (
              <div className="mt-2 h-12 rounded-lg bg-gray-50">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={data.trend_data.map((v, i) => ({ idx: i, value: v }))}>
                    <Line
                      type="monotone"
                      dataKey="value"
                      stroke={
                        data.trend === 'increasing' ? '#dc2626' :
                        data.trend === 'decreasing' ? '#16a34a' : '#9ca3af'
                      }
                      strokeWidth={2}
                      dot={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Stats */}
      <div className="border-b border-gray-100 px-6 py-4">
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-2">
            <MessageSquare className="h-4 w-4 text-gray-400" />
            <span className="text-sm text-gray-600">
              <span className="font-semibold text-gray-900">{data.conversation_count.toLocaleString()}</span>
              {' '}conversations affected
            </span>
          </div>
        </div>
      </div>

      {/* Root Cause */}
      {data.root_cause && (
        <div className="border-b border-gray-100 px-6 py-4">
          <p className="text-xs font-medium uppercase tracking-wide text-gray-500">Root Cause</p>
          <p className="mt-2 text-sm text-gray-900">{data.root_cause}</p>
        </div>
      )}

      {/* Suggested Fix */}
      {data.suggested_fix && (
        <div className="border-b border-gray-100 bg-blue-50 px-6 py-4">
          <p className="text-xs font-medium uppercase tracking-wide text-blue-700">Suggested Fix</p>
          <p className="mt-2 text-sm text-blue-900">{data.suggested_fix}</p>
        </div>
      )}

      {/* Example Conversations */}
      {data.example_conversation_ids.length > 0 && (
        <div className="px-6 py-4">
          <p className="text-xs font-medium uppercase tracking-wide text-gray-500 mb-3">
            Example Conversations
          </p>
          <div className="space-y-2">
            {data.example_conversation_ids.map((convId) => (
              <button
                key={convId}
                onClick={() => onViewConversation?.(convId)}
                className="flex items-center justify-between w-full rounded-md border border-gray-200 bg-white px-3 py-2 text-left transition hover:border-gray-300 hover:bg-gray-50"
              >
                <span className="font-mono text-xs text-gray-600">{convId}</span>
                <ExternalLink className="h-3.5 w-3.5 text-gray-400" />
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
