import { beforeEach, describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { HarnessMetricsBar } from './HarnessMetricsBar';
import { useWorkbenchStore } from '../../lib/workbench-store';

function renderBar() {
  return render(
    <div className="workbench-root">
      <HarnessMetricsBar />
    </div>
  );
}

describe('HarnessMetricsBar', () => {
  beforeEach(() => {
    useWorkbenchStore.getState().reset();
  });

  it('renders nothing when idle with no metrics', () => {
    renderBar();
    expect(screen.queryByLabelText('Harness metrics')).toBeNull();
  });

  it('renders when build is starting even without metrics data', () => {
    useWorkbenchStore.getState().beginBuild('Build something');
    renderBar();
    expect(screen.getByLabelText('Harness metrics')).toBeInTheDocument();
  });

  it('shows the current phase label', () => {
    useWorkbenchStore.getState().dispatchEvent({
      event: 'harness.metrics',
      data: { steps_completed: 2, total_steps: 8, tokens_used: 500, cost_usd: 0, elapsed_ms: 0, current_phase: 'planning' },
    });
    renderBar();
    expect(screen.getByLabelText('Harness metrics')).toBeInTheDocument();
    expect(screen.getByText('Planning')).toBeInTheDocument();
  });

  it('shows step progress text', () => {
    useWorkbenchStore.getState().dispatchEvent({
      event: 'harness.metrics',
      data: { steps_completed: 3, total_steps: 8, tokens_used: 0, cost_usd: 0, elapsed_ms: 0, current_phase: 'executing' },
    });
    renderBar();
    expect(screen.getByText('3/8 steps')).toBeInTheDocument();
  });

  it('formats tokens as k suffix when >= 1000', () => {
    useWorkbenchStore.getState().dispatchEvent({
      event: 'harness.metrics',
      data: { steps_completed: 0, total_steps: 0, tokens_used: 2400, cost_usd: 0, elapsed_ms: 0, current_phase: 'idle' },
    });
    renderBar();
    expect(screen.getByText('2.4k tokens')).toBeInTheDocument();
  });

  it('formats cost in dollars', () => {
    useWorkbenchStore.getState().dispatchEvent({
      event: 'harness.metrics',
      data: { steps_completed: 0, total_steps: 0, tokens_used: 0, cost_usd: 0.02, elapsed_ms: 0, current_phase: 'idle' },
    });
    renderBar();
    expect(screen.getByText('$0.02')).toBeInTheDocument();
  });

  it('formats elapsed time in seconds', () => {
    useWorkbenchStore.getState().dispatchEvent({
      event: 'harness.metrics',
      data: { steps_completed: 0, total_steps: 0, tokens_used: 0, cost_usd: 0, elapsed_ms: 12000, current_phase: 'idle' },
    });
    renderBar();
    expect(screen.getByText('12s')).toBeInTheDocument();
  });

  it('formats elapsed time in minutes and seconds', () => {
    useWorkbenchStore.getState().dispatchEvent({
      event: 'harness.metrics',
      data: { steps_completed: 0, total_steps: 0, tokens_used: 0, cost_usd: 0, elapsed_ms: 92000, current_phase: 'idle' },
    });
    renderBar();
    expect(screen.getByText('1m 32s')).toBeInTheDocument();
  });

  it('shows an iteration badge when iterationCount > 0', () => {
    useWorkbenchStore.getState().dispatchEvent({
      event: 'harness.metrics',
      data: { steps_completed: 0, total_steps: 0, tokens_used: 0, cost_usd: 0, elapsed_ms: 0, current_phase: 'idle' },
    });
    useWorkbenchStore.getState().startIteration('Second pass');
    renderBar();
    expect(screen.getByText('Iteration 1')).toBeInTheDocument();
  });

  it('does not show step progress bar when totalSteps is 0', () => {
    useWorkbenchStore.getState().dispatchEvent({
      event: 'harness.metrics',
      data: { steps_completed: 0, total_steps: 0, tokens_used: 100, cost_usd: 0, elapsed_ms: 0, current_phase: 'planning' },
    });
    renderBar();
    // "X/Y steps" text should not appear.
    expect(screen.queryByText(/steps/)).toBeNull();
  });
});
