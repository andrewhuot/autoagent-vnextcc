import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { MetricCard } from './MetricCard';
import { ScoreChart } from './ScoreChart';

describe('responsive chart containers', () => {
  it('gives ScoreChart a minimum render box for Recharts', () => {
    const { container } = render(
      <ScoreChart
        height={180}
        data={[
          { label: 'A', score: 55 },
          { label: 'B', score: 72 },
        ]}
      />
    );

    const frame = container.firstElementChild as HTMLElement | null;
    expect(frame).not.toBeNull();
    expect(frame?.style.minWidth).toBe('240px');
    expect(frame?.style.minHeight).toBe('180px');
  });

  it('gives MetricCard sparklines a minimum render box for Recharts', () => {
    const { container } = render(
      <MetricCard
        title="Latency"
        value="120ms"
        sparklineData={[120, 110, 105, 98]}
        trend="down"
        trendValue="-18%"
      />
    );

    const sparklineFrame = container.querySelector('.w-16.h-8') as HTMLElement | null;
    expect(sparklineFrame).not.toBeNull();
    expect(sparklineFrame?.style.minWidth).toBe('64px');
    expect(sparklineFrame?.style.minHeight).toBe('32px');
  });
});
