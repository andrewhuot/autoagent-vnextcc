import { AlertTriangle, TrendingDown, TrendingUp, Minus, Target } from 'lucide-react';
import { LineChart, Line, ResponsiveContainer } from 'recharts';
import { classNames } from '../../lib/utils';

export interface DiagnosisData {
  root_cause: string;
  description: string;
  impact_score: number;
  affected_conversations: number;
  trend: 'increasing' | 'stable' | 'decreasing';
  trend_data?: number[];
  fix_confidence: 'high' | 'medium' | 'low';
  fix_summary?: string;
}

interface DiagnosisCardProps {
  data: DiagnosisData;
}

export function DiagnosisCard({ data }: DiagnosisCardProps) {
  const impactColor = (score: number): string => {
    if (score >= 75) return 'text-red-600';
    if (score >= 50) return 'text-amber-600';
    return 'text-yellow-600';
  };

  const impactBg = (score: number): string => {
    if (score >= 75) return 'bg-red-50';
    if (score >= 50) return 'bg-amber-50';
    return 'bg-yellow-50';
  };

  const confidenceColor = (confidence: string): string => {
    if (confidence === 'high') return 'bg-green-50 text-green-700';
    if (confidence === 'medium') return 'bg-amber-50 text-amber-700';
    return 'bg-red-50 text-red-700';
  };

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

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-6">
      {/* Header */}
      <div className="flex items-start gap-3">
        <div className={classNames('rounded-lg p-2', impactBg(data.impact_score))}>
          <AlertTriangle className={classNames('h-5 w-5', impactColor(data.impact_score))} />
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-medium text-gray-900">{data.root_cause}</h3>
          <p className="mt-1 text-sm text-gray-600">{data.description}</p>
        </div>
      </div>

      {/* Impact Score */}
      <div className="mt-4 flex items-center justify-between">
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium uppercase tracking-wide text-gray-500">
              Impact Score
            </span>
            <span className={classNames('text-2xl font-bold tabular-nums', impactColor(data.impact_score))}>
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

        {/* Trend Chart */}
        {data.trend_data && data.trend_data.length > 1 && (
          <div className="ml-6 w-24 h-16">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={data.trend_data.map((v, i) => ({ idx: i, value: v }))}>
                <Line
                  type="monotone"
                  dataKey="value"
                  stroke={data.trend === 'increasing' ? '#dc2626' : data.trend === 'decreasing' ? '#16a34a' : '#9ca3af'}
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {/* Stats Grid */}
      <div className="mt-4 grid grid-cols-2 gap-4 border-t border-gray-100 pt-4">
        <div>
          <p className="text-xs text-gray-500">Affected Conversations</p>
          <p className="mt-1 text-xl font-semibold text-gray-900">{data.affected_conversations.toLocaleString()}</p>
        </div>
        <div>
          <div className="flex items-center gap-1.5">
            {trendIcon()}
            <p className="text-xs text-gray-500">{trendLabel()}</p>
          </div>
          <p className="mt-1 text-xl font-semibold text-gray-900">
            {data.trend === 'stable' ? 'No change' : data.trend === 'increasing' ? 'Worsening' : 'Improving'}
          </p>
        </div>
      </div>

      {/* Fix Confidence */}
      <div className="mt-4 border-t border-gray-100 pt-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Target className="h-4 w-4 text-gray-400" />
            <span className="text-xs font-medium text-gray-500">Fix Confidence</span>
          </div>
          <span className={classNames('rounded-md px-2.5 py-1 text-xs font-medium uppercase', confidenceColor(data.fix_confidence))}>
            {data.fix_confidence}
          </span>
        </div>
        {data.fix_summary && (
          <p className="mt-2 text-xs text-gray-600">{data.fix_summary}</p>
        )}
      </div>
    </div>
  );
}
