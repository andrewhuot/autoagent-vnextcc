import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Optimize } from './Optimize';
import { useActiveAgentStore } from '../lib/active-agent';

let optimizeCompleteHandler: ((payload: unknown) => void) | null = null;

const apiMocks = vi.hoisted(() => ({
  useAgent: vi.fn(),
  useAgents: vi.fn(),
  useOptimizeHistory: vi.fn(),
  useStartOptimize: vi.fn(),
  useTaskStatus: vi.fn(),
}));

vi.mock('../lib/api', () => ({
  useAgent: apiMocks.useAgent,
  useAgents: apiMocks.useAgents,
  useOptimizeHistory: apiMocks.useOptimizeHistory,
  useStartOptimize: apiMocks.useStartOptimize,
  useTaskStatus: apiMocks.useTaskStatus,
}));

vi.mock('../lib/websocket', () => ({
  wsClient: {
    connect: vi.fn(),
    onMessage: vi.fn((_type: string, handler: (payload: unknown) => void) => {
      optimizeCompleteHandler = handler;
      return () => undefined;
    }),
  },
}));

vi.mock('./LiveOptimize', () => ({
  LiveOptimize: () => <div>Live Optimize Content</div>,
}));

vi.mock('../lib/toast', () => ({
  toastError: vi.fn(),
  toastInfo: vi.fn(),
  toastSuccess: vi.fn(),
}));

function renderOptimize(initialEntry = '/optimize') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/optimize" element={<Optimize />} />
        <Route path="/evals" element={<div>Eval Page</div>} />
        <Route path="/improvements" element={<div>Improvements Page</div>} />
      </Routes>
    </MemoryRouter>
  );
}

describe('Optimize', () => {
  beforeEach(() => {
    optimizeCompleteHandler = null;
    window.sessionStorage.clear();
    useActiveAgentStore.getState().clearActiveAgent();

    apiMocks.useAgents.mockReturnValue({
      data: [
        {
          id: 'agent-v002',
          name: 'Order Guardian',
          model: 'gpt-5.4',
          created_at: '2026-04-01T12:00:00.000Z',
          source: 'built',
          config_path: '/workspace/configs/v002.yaml',
          status: 'candidate',
        },
      ],
      isLoading: false,
    });
    apiMocks.useAgent.mockReturnValue({
      data: {
        id: 'agent-v002',
        name: 'Order Guardian',
        model: 'gpt-5.4',
        created_at: '2026-04-01T12:00:00.000Z',
        source: 'built',
        config_path: '/workspace/configs/v002.yaml',
        status: 'candidate',
        config: {
          model: 'gpt-5.4',
          system_prompt: 'Resolve support issues safely.',
        },
      },
      isLoading: false,
    });
    apiMocks.useOptimizeHistory.mockReturnValue({
      data: [],
      isLoading: false,
      refetch: vi.fn(),
    });
    apiMocks.useTaskStatus.mockReturnValue({
      data: null,
    });
  });

  it('starts optimization against the selected agent config and keeps the tabbed layout intact', async () => {
    const user = userEvent.setup();
    const mutate = vi.fn((_params, options) => {
      options?.onSuccess?.({ task_id: 'opt-123456', message: 'Optimization started' });
    });
    apiMocks.useStartOptimize.mockReturnValue({
      mutate,
      isPending: false,
    });

    renderOptimize('/optimize?agent=agent-v002');

    expect(screen.getByRole('button', { name: 'Run' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Live' })).toBeInTheDocument();
    expect(await screen.findByText('Order Guardian')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Start Optimization' }));

    expect(mutate).toHaveBeenCalledWith(
      expect.objectContaining({
        config_path: '/workspace/configs/v002.yaml',
      }),
      expect.any(Object)
    );
  });

  it('shows a post-optimization handoff for re-eval and results review', async () => {
    const user = userEvent.setup();
    const mutate = vi.fn((_params, options) => {
      options?.onSuccess?.({ task_id: 'opt-123456', message: 'Optimization started' });
    });
    apiMocks.useStartOptimize.mockReturnValue({
      mutate,
      isPending: false,
    });

    renderOptimize('/optimize?agent=agent-v002');

    await user.click(screen.getByRole('button', { name: 'Start Optimization' }));
    optimizeCompleteHandler?.({
      task_id: 'opt-123456',
      accepted: true,
      status: 'Accepted for rollout',
    });

    await user.click(await screen.findByRole('button', { name: 'Re-eval' }));
    expect(await screen.findByText('Eval Page')).toBeInTheDocument();
  });
});
