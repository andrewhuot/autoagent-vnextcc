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
  useGeneratedSuites: vi.fn(),
  useStartEval: vi.fn(),
}));

vi.mock('../lib/api', () => ({
  useAgent: apiMocks.useAgent,
  useAgents: apiMocks.useAgents,
  useApplyCurriculum: apiMocks.useApplyCurriculum,
  useCurriculumBatches: apiMocks.useCurriculumBatches,
  useEvalRuns: apiMocks.useEvalRuns,
  useGenerateCurriculum: apiMocks.useGenerateCurriculum,
  useGeneratedSuites: apiMocks.useGeneratedSuites,
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
    apiMocks.useGeneratedSuites.mockReturnValue({
      data: [],
      isLoading: false,
      isError: false,
    });
    apiMocks.useGenerateCurriculum.mockReturnValue({ mutate: vi.fn(), isPending: false });
    apiMocks.useApplyCurriculum.mockReturnValue({ mutate: vi.fn(), isPending: false });
  });

  it('starts a new eval from the header action using the selected agent config path', async () => {
    const user = userEvent.setup();
    const mutate = vi.fn((_params, options) => {
      options?.onSuccess?.({ task_id: 'task-123456', message: 'Eval run started' });
    });
    apiMocks.useStartEval.mockReturnValue({ mutate, isPending: false });

    renderPage('/evals?agent=agent-v002');

    expect((await screen.findAllByText('Order Guardian')).length).toBeGreaterThan(0);
    await user.click(screen.getByRole('button', { name: 'New Eval Run' }));

    expect(mutate).toHaveBeenCalledWith(
      {
        config_path: '/workspace/configs/v002.yaml',
        category: undefined,
      },
      expect.any(Object)
    );
  });

  it('starts a new eval from the empty-state CTA when an agent is selected', async () => {
    const user = userEvent.setup();
    const mutate = vi.fn((_params, options) => {
      options?.onSuccess?.({ task_id: 'task-empty-123', message: 'Eval run started' });
    });
    apiMocks.useStartEval.mockReturnValue({ mutate, isPending: false });
    apiMocks.useEvalRuns.mockReturnValue({
      data: [],
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    renderPage('/evals?agent=agent-v002');

    await user.click(screen.getByRole('button', { name: 'Create Eval Run' }));

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

  it('renders Eval Sets and runs an accepted suite with the selected agent config', async () => {
    const user = userEvent.setup();
    const mutate = vi.fn((_params, options) => {
      options?.onSuccess?.({ task_id: 'task-suite-123', message: 'Eval run started' });
    });
    apiMocks.useStartEval.mockReturnValue({ mutate, isPending: false });
    apiMocks.useGeneratedSuites.mockReturnValue({
      data: [
        {
          suite_id: 'suite_accepted_001',
          agent_name: 'Checkout Guard',
          source_kind: 'config',
          status: 'accepted',
          mock_mode: true,
          created_at: '2026-04-01T12:30:00Z',
          updated_at: '2026-04-01T12:40:00Z',
          accepted_at: '2026-04-01T12:45:00Z',
          accepted_eval_path: 'evals/cases/generated_suite_accepted_001.yaml',
          transcript_count: 0,
          category_counts: { safety: 3, routing: 2 },
          case_count: 5,
        },
      ],
      isLoading: false,
      isError: false,
    });

    renderPage('/evals?agent=agent-v002');

    expect(screen.getByText('Eval Sets')).toBeInTheDocument();
    expect(screen.getByText('Checkout Guard')).toBeInTheDocument();
    expect(screen.getByText(/5 cases/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Run Eval' }));

    expect(mutate).toHaveBeenCalledWith(
      {
        config_path: '/workspace/configs/v002.yaml',
        generated_suite_id: 'suite_accepted_001',
      },
      expect.any(Object)
    );
  });

  it('shows the requested empty state when no eval sets exist yet', () => {
    apiMocks.useStartEval.mockReturnValue({ mutate: vi.fn(), isPending: false });
    apiMocks.useGeneratedSuites.mockReturnValue({
      data: [],
      isLoading: false,
      isError: false,
    });

    renderPage('/evals?agent=agent-v002');

    expect(screen.getByText('No eval sets yet — generate one from your agent config')).toBeInTheDocument();
  });
});
