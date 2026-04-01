import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { EvalRuns } from './EvalRuns';
import { useActiveAgentStore } from '../lib/active-agent';

let evalCompleteHandler: ((payload: unknown) => void) | null = null;

const apiMocks = vi.hoisted(() => ({
  useAgent: vi.fn(),
  useAgents: vi.fn(),
  useApplyCurriculum: vi.fn(),
  useCurriculumBatches: vi.fn(),
  useEvalRuns: vi.fn(),
  useGenerateCurriculum: vi.fn(),
  useStartEval: vi.fn(),
}));

vi.mock('../lib/api', () => ({
  useAgent: apiMocks.useAgent,
  useAgents: apiMocks.useAgents,
  useApplyCurriculum: apiMocks.useApplyCurriculum,
  useCurriculumBatches: apiMocks.useCurriculumBatches,
  useEvalRuns: apiMocks.useEvalRuns,
  useGenerateCurriculum: apiMocks.useGenerateCurriculum,
  useStartEval: apiMocks.useStartEval,
}));

vi.mock('../lib/websocket', () => ({
  wsClient: {
    onMessage: vi.fn((_type: string, handler: (payload: unknown) => void) => {
      evalCompleteHandler = handler;
      return () => undefined;
    }),
  },
}));

vi.mock('../lib/toast', () => ({
  toastError: vi.fn(),
  toastInfo: vi.fn(),
  toastSuccess: vi.fn(),
}));

function renderPage(initialEntry = '/evals') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/evals" element={<EvalRuns />} />
        <Route path="/optimize" element={<div>Optimize Page</div>} />
      </Routes>
    </MemoryRouter>
  );
}

describe('EvalRuns', () => {
  beforeEach(() => {
    evalCompleteHandler = null;
    window.sessionStorage.clear();
    useActiveAgentStore.getState().clearActiveAgent();

    apiMocks.useEvalRuns.mockReturnValue({
      data: [
        {
          run_id: 'run-mixed-1234',
          timestamp: '2026-03-31T12:00:00Z',
          status: 'completed',
          progress: 100,
          composite_score: 87.5,
          total_cases: 10,
          passed_cases: 9,
          mode: 'mixed',
        },
      ],
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
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
    apiMocks.useCurriculumBatches.mockReturnValue({
      data: { batches: [], progression: [] },
      isLoading: false,
    });
    apiMocks.useGenerateCurriculum.mockReturnValue({ mutate: vi.fn(), isPending: false });
    apiMocks.useApplyCurriculum.mockReturnValue({ mutate: vi.fn(), isPending: false });
  });

  it('uses the selected agent instead of a config version dropdown when starting an eval', async () => {
    const user = userEvent.setup();
    const mutate = vi.fn((_params, options) => {
      options?.onSuccess?.({ task_id: 'task-123456', message: 'Eval run started' });
    });
    apiMocks.useStartEval.mockReturnValue({ mutate, isPending: false });

    renderPage('/evals?agent=agent-v002&new=1');

    expect(screen.queryByText('Config Version')).not.toBeInTheDocument();
    expect((await screen.findAllByText('Order Guardian')).length).toBeGreaterThan(0);

    await user.click(screen.getByRole('button', { name: 'Start Eval' }));

    expect(mutate).toHaveBeenCalledWith(
      {
        config_path: '/workspace/configs/v002.yaml',
        category: undefined,
      },
      expect.any(Object)
    );
  });

  it('shows an optimize handoff after the selected agent finishes evaluating', async () => {
    const user = userEvent.setup();
    const mutate = vi.fn((_params, options) => {
      options?.onSuccess?.({ task_id: 'task-123456', message: 'Eval run started' });
    });
    apiMocks.useStartEval.mockReturnValue({ mutate, isPending: false });

    renderPage('/evals?agent=agent-v002&new=1');

    await user.click(screen.getByRole('button', { name: 'Start Eval' }));
    evalCompleteHandler?.({
      task_id: 'task-123456',
      composite: 0.91,
      passed: 11,
      total: 12,
    });

    await user.click(await screen.findByRole('button', { name: 'Optimize' }));
    expect(await screen.findByText('Optimize Page')).toBeInTheDocument();
  });
});
