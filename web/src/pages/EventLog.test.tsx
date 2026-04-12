import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { EventLogPage } from './EventLog';

const apiMocks = vi.hoisted(() => ({
  useUnifiedEvents: vi.fn(),
}));

vi.mock('../lib/api', () => ({
  useUnifiedEvents: apiMocks.useUnifiedEvents,
}));

describe('EventLogPage', () => {
  beforeEach(() => {
    apiMocks.useUnifiedEvents.mockReturnValue({
      data: {
        events: [
          {
            id: 'sys-1',
            event_type: 'eval_started',
            timestamp: 1776000000,
            source: 'system',
            source_label: 'System event log',
            continuity_state: 'historical',
            session_id: null,
            payload: { run_id: 'eval-1' },
          },
          {
            id: 'bld-1',
            event_type: 'task.started',
            timestamp: 1776000001,
            source: 'builder',
            source_label: 'Builder event history',
            continuity_state: 'historical',
            session_id: 'session-1',
            payload: { phase: 'plan' },
          },
        ],
        count: 2,
        sources: {
          system: { included: true, durable: true, label: 'System event log' },
          builder: { included: true, durable: true, label: 'Builder event history' },
        },
        continuity: {
          state: 'historical',
          label: 'Durable event history',
          detail: 'This timeline merges persisted system events and builder events so history remains visible after restart.',
        },
      },
      isLoading: false,
      isError: false,
    });
  });

  it('shows unified durable event source labels for restart history', () => {
    render(<EventLogPage />);

    expect(screen.getByText('Unified durable timeline')).toBeInTheDocument();
    expect(
      screen.getByText('System and builder events are merged from persisted stores so restart history remains visible.')
    ).toBeInTheDocument();
    expect(screen.getByText('system')).toBeInTheDocument();
    expect(screen.getByText('builder')).toBeInTheDocument();
    expect(screen.getByText('Durable event history')).toBeInTheDocument();
    expect(screen.getByText('System event log', { exact: true })).toBeInTheDocument();
    expect(screen.getByText('Builder event history')).toBeInTheDocument();
    expect(screen.getAllByText('historical')).toHaveLength(2);
    expect(screen.getByText('session: session-1')).toBeInTheDocument();
  });
});
