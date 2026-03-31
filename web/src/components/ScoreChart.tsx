import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';

interface ScoreChartProps {
  data: { label: string; score: number }[];
  height?: number;
}

export function ScoreChart({ data, height = 240 }: ScoreChartProps) {
  if (data.length === 0) {
    return (
      <div
        className="flex items-center justify-center text-sm text-gray-400 bg-gray-50 rounded-lg border border-gray-200"
        style={{ height }}
      >
        No data to display
      </div>
    );
  }

  return (
    <div style={{ height, minHeight: height, minWidth: 240 }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" vertical={false} />
          <XAxis
            dataKey="label"
            tick={{ fontSize: 11, fill: '#9ca3af' }}
            axisLine={{ stroke: '#e5e7eb' }}
            tickLine={false}
          />
          <YAxis
            domain={[0, 100]}
            tick={{ fontSize: 11, fill: '#9ca3af' }}
            axisLine={{ stroke: '#e5e7eb' }}
            tickLine={false}
          />
          <Tooltip
            contentStyle={{
              fontSize: 12,
              border: '1px solid #e5e7eb',
              borderRadius: 6,
              boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
            }}
          />
          <Line
            type="monotone"
            dataKey="score"
            stroke="#6b7280"
            strokeWidth={1.5}
            dot={{ r: 2.5, fill: '#6b7280', stroke: '#fff', strokeWidth: 2 }}
            activeDot={{ r: 4 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
