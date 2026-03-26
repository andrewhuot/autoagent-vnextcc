import { BarChart, Bar, XAxis, YAxis, ResponsiveContainer, Cell } from 'recharts';
import { TrendingUp, TrendingDown } from 'lucide-react';
import { classNames } from '../../lib/utils';

export interface MetricComparison {
  name: string;
  baseline: number;
  candidate: number;
  delta: number;
  p_value?: number;
}

export interface MetricsData {
  title: string;
  metrics: MetricComparison[];
  confidence_interval?: {
    lower: number;
    upper: number;
  };
  overall_p_value?: number;
  is_significant?: boolean;
}

interface MetricsCardProps {
  data: MetricsData;
}

export function MetricsCard({ data }: MetricsCardProps) {
  const getBarColor = (delta: number): string => {
    if (delta > 0) return '#16a34a';
    if (delta < 0) return '#dc2626';
    return '#9ca3af';
  };

  const chartData = data.metrics.map((metric) => ({
    name: metric.name,
    baseline: metric.baseline * 100,
    candidate: metric.candidate * 100,
    delta: metric.delta * 100,
  }));

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h3 className="text-sm font-medium text-gray-900">{data.title}</h3>
          {data.is_significant !== undefined && (
            <p className="mt-1 flex items-center gap-1.5 text-xs">
              {data.is_significant ? (
                <span className="text-green-600 font-medium">Statistically significant</span>
              ) : (
                <span className="text-gray-500">Not statistically significant</span>
              )}
              {data.overall_p_value !== undefined && (
                <span className="text-gray-400">
                  (p = {data.overall_p_value.toFixed(4)})
                </span>
              )}
            </p>
          )}
        </div>
      </div>

      {/* Comparison Chart */}
      <div className="mt-6 h-64">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chartData} layout="horizontal">
            <XAxis type="number" domain={[0, 100]} fontSize={11} />
            <YAxis type="category" dataKey="name" fontSize={11} width={100} />
            <Bar dataKey="baseline" fill="#e5e7eb" radius={[0, 4, 4, 0]} />
            <Bar dataKey="candidate" radius={[0, 4, 4, 0]}>
              {chartData.map((entry, index) => (
                <Cell key={`cell-${index}`} fill={getBarColor(entry.delta)} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Metrics Table */}
      <div className="mt-6 border-t border-gray-100 pt-4">
        <div className="space-y-3">
          {data.metrics.map((metric) => (
            <div key={metric.name} className="flex items-center justify-between">
              <div className="flex-1">
                <p className="text-xs font-medium text-gray-700">{metric.name}</p>
                <div className="mt-1 flex items-center gap-3 text-xs">
                  <span className="text-gray-500">
                    Baseline: <span className="font-medium tabular-nums">{(metric.baseline * 100).toFixed(1)}%</span>
                  </span>
                  <span className="text-gray-400">→</span>
                  <span className="text-gray-500">
                    Candidate: <span className="font-medium tabular-nums">{(metric.candidate * 100).toFixed(1)}%</span>
                  </span>
                </div>
              </div>
              <div className="flex items-center gap-2">
                {metric.p_value !== undefined && (
                  <span className="text-xs text-gray-400 tabular-nums">
                    p={metric.p_value.toFixed(3)}
                  </span>
                )}
                <div className={classNames(
                  'flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-medium tabular-nums',
                  metric.delta > 0 ? 'bg-green-50 text-green-700' :
                  metric.delta < 0 ? 'bg-red-50 text-red-700' :
                  'bg-gray-50 text-gray-500'
                )}>
                  {metric.delta > 0 ? (
                    <TrendingUp className="h-3.5 w-3.5" />
                  ) : metric.delta < 0 ? (
                    <TrendingDown className="h-3.5 w-3.5" />
                  ) : null}
                  {metric.delta > 0 ? '+' : ''}
                  {(metric.delta * 100).toFixed(1)}%
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Confidence Interval */}
      {data.confidence_interval && (
        <div className="mt-4 border-t border-gray-100 pt-4">
          <p className="text-xs font-medium uppercase tracking-wide text-gray-500">95% Confidence Interval</p>
          <div className="mt-2 flex items-center gap-2">
            <div className="flex-1">
              <div className="h-2 rounded-full bg-gray-100 relative">
                <div
                  className="absolute h-full rounded-full bg-blue-500"
                  style={{
                    left: `${data.confidence_interval.lower * 100}%`,
                    right: `${100 - (data.confidence_interval.upper * 100)}%`,
                  }}
                />
              </div>
            </div>
            <span className="text-xs text-gray-600 tabular-nums">
              [{(data.confidence_interval.lower * 100).toFixed(1)}%, {(data.confidence_interval.upper * 100).toFixed(1)}%]
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
