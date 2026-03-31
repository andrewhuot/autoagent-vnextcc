import { useEffect, useRef, useState } from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from 'recharts';

interface ScoreChartProps {
  data: { label: string; score: number }[];
  height?: number;
}

export function ScoreChart({ data, height = 240 }: ScoreChartProps) {
  const frameRef = useRef<HTMLDivElement | null>(null);
  const [chartSize, setChartSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame) return;

    function updateSize() {
      const nextFrame = frameRef.current;
      if (!nextFrame) return;
      const nextRect = nextFrame.getBoundingClientRect();
      setChartSize({
        width: Math.max(0, Math.floor(nextRect.width)),
        height: Math.max(0, Math.floor(nextRect.height)),
      });
    }

    updateSize();
    const animationId = window.requestAnimationFrame(updateSize);

    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', updateSize);
      return () => {
        window.cancelAnimationFrame(animationId);
        window.removeEventListener('resize', updateSize);
      };
    }

    const observer = new ResizeObserver(() => updateSize());
    observer.observe(frame);

    return () => {
      window.cancelAnimationFrame(animationId);
      observer.disconnect();
    };
  }, []);

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
    <div ref={frameRef} className="w-full" style={{ height, minHeight: height, minWidth: 240 }}>
      {chartSize.width > 0 && chartSize.height > 0 ? (
        <LineChart
          width={chartSize.width}
          height={chartSize.height}
          data={data}
          margin={{ top: 8, right: 8, bottom: 0, left: -16 }}
        >
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
      ) : null}
    </div>
  );
}
