import { LineChart, Line, ResponsiveContainer } from 'recharts';
import { ArrowDownRight, ArrowUpRight, Minus } from 'lucide-react';

interface MetricCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  trend?: 'up' | 'down' | 'neutral';
  trendValue?: string;
  sparklineData?: number[];
}

export function MetricCard({
  title,
  value,
  subtitle,
  trend,
  trendValue,
  sparklineData,
}: MetricCardProps) {
  const trendColor =
    trend === 'up' ? 'text-green-600' : trend === 'down' ? 'text-red-600' : 'text-gray-500';
  const trendIcon =
    trend === 'up' ? <ArrowUpRight className="h-3.5 w-3.5" /> : trend === 'down' ? <ArrowDownRight className="h-3.5 w-3.5" /> : <Minus className="h-3.5 w-3.5" />;

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
      <div className="flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">{title}</p>
          <p className="mt-1 text-2xl font-semibold text-gray-900 tabular-nums">{value}</p>
          <div className="mt-1 flex items-center gap-2">
            {trendValue && (
              <span className={`inline-flex items-center gap-1 text-xs font-medium ${trendColor}`}>
                {trendIcon}
                {trendValue}
              </span>
            )}
            {subtitle && <span className="text-xs text-gray-500">{subtitle}</span>}
          </div>
        </div>
        {sparklineData && sparklineData.length > 1 && (
          <div className="w-20 h-10 flex-shrink-0">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={sparklineData.map((v, i) => ({ idx: i, value: v }))}>
                <Line
                  type="monotone"
                  dataKey="value"
                  stroke={trend === 'down' ? '#dc2626' : '#3b82f6'}
                  strokeWidth={1.5}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </div>
  );
}
