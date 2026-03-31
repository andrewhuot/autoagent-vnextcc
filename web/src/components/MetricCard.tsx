import { LineChart, Line, ResponsiveContainer } from 'recharts';
import { ArrowDownRight, ArrowUpRight, Minus } from 'lucide-react';
import { useEffect, useState } from 'react';

interface MetricCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  trend?: 'up' | 'down' | 'neutral';
  trendValue?: string;
  sparklineData?: number[];
  glow?: boolean;
}

export function MetricCard({
  title,
  value,
  subtitle,
  trend,
  trendValue,
  sparklineData,
  glow = false,
}: MetricCardProps) {
  const [shouldGlow, setShouldGlow] = useState(false);

  useEffect(() => {
    if (glow) {
      setShouldGlow(true);
      const timer = setTimeout(() => {
        setShouldGlow(false);
      }, 1500);
      return () => clearTimeout(timer);
    }
  }, [glow]);

  const trendColor =
    trend === 'up' ? 'text-green-600' : trend === 'down' ? 'text-red-500' : 'text-gray-400';
  const trendIcon =
    trend === 'up' ? <ArrowUpRight className="h-3 w-3" /> : trend === 'down' ? <ArrowDownRight className="h-3 w-3" /> : <Minus className="h-3 w-3" />;

  return (
    <div className={`rounded-lg border border-gray-200 bg-white p-4 ${shouldGlow ? 'metric-card-glow' : ''}`}>
      <div className="flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <p className="text-xs text-gray-500">{title}</p>
          <p className="mt-1 text-2xl font-semibold tabular-nums text-gray-900">{value}</p>
          <div className="mt-1 flex items-center gap-2">
            {trendValue && (
              <span className={`inline-flex items-center gap-0.5 text-xs ${trendColor}`}>
                {trendIcon}
                {trendValue}
              </span>
            )}
            {subtitle && <span className="text-xs text-gray-400">{subtitle}</span>}
          </div>
        </div>
        {sparklineData && sparklineData.length > 1 && (
          <div className="w-16 h-8 flex-shrink-0" style={{ minWidth: 64, minHeight: 32 }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={sparklineData.map((v, i) => ({ idx: i, value: v }))}>
                <Line
                  type="monotone"
                  dataKey="value"
                  stroke={trend === 'down' ? '#ef4444' : '#6b7280'}
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
