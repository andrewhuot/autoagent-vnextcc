import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { EvalRuns } from './EvalRuns';
import { useActiveAgentStore } from '../lib/active-agent';

type InitialEntry =
  | string
  | {
      pathname: string;
      search?: string;
      hash?: string;
      state?: unknown;
      key?: string;
    };

let evalCompleteHandler: ((payload: unknown) => void) | null = null;

const apiMocks = vi.hoisted(() => ({
  useAgent: vi.fn(),
  useAgents: vi.fn(),
  useApplyCurriculum: vi.fn(),
  useCurriculumBatches: vi.fn(),
  useEvalRuns: vi.fn(),
  useGenerateCurriculum: vi.fn(),
  useGenerateEvals: vi.fn(),
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
  useGenerateEvals: apiMocks.useGenerateEvals,
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

function renderPage(initialEntry: InitialEntry = '/evals') {
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
    apiMocks.useGenerateEvals.mockReturnValue({ mutate: vi.fn(), isPending: false });
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
    await user.click(screen.getByRole('button', { name: 'Set Up Eval Run' }));
    expect(screen.getByRole('heading', { name: 'Start New Evaluation' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Start Eval' }));

    expect(mutate).toHaveBeenCalledWith(
      {
        config_path: '/workspace/configs/v002.yaml',
        category: undefined,
        require_live: true,
      },
      expect.any(Object)
    );
  });

  it('starts a first eval with the Build-generated eval cases path from navigation state', async () => {
    const user = userEvent.setup();
    const mutate = vi.fn((_params, options) => {
      options?.onSuccess?.({ task_id: 'task-build-123', message: 'Eval run started' });
    });
    apiMocks.useStartEval.mockReturnValue({ mutate, isPending: false });
    apiMocks.useEvalRuns.mockReturnValue({
      data: [],
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    renderPage({
      pathname: '/evals',
      search: '?agent=agent-v002&new=1',
      state: {
        agent: {
          id: 'agent-v002',
          name: 'Order Guardian',
          model: 'gpt-5.4',
          created_at: '2026-04-01T12:00:00.000Z',
          source: 'built',
          config_path: '/workspace/configs/v002.yaml',
          status: 'candidate',
        },
        open: 'run',
        evalCasesPath: '/workspace/evals/cases/generated_build.yaml',
      },
    });

    await screen.findByRole('heading', { name: 'Start First Evaluation' });
    expect(screen.getByText('/workspace/evals/cases/generated_build.yaml')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Run First Eval' }));

    expect(mutate).toHaveBeenCalledWith(
      {
        config_path: '/workspace/configs/v002.yaml',
        category: undefined,
        dataset_path: '/workspace/evals/cases/generated_build.yaml',
        require_live: true,
        split: 'all',
      },
      expect.any(Object)
    );
  });

  it('shows setup guidance before an eval is selected or complete', async () => {
    apiMocks.useStartEval.mockReturnValue({ mutate: vi.fn(), isPending: false });
    apiMocks.useEvalRuns.mockReturnValue({
      data: [],
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    renderPage('/evals?agent=agent-v002');

    const journey = await screen.findByRole('region', { name: 'Operator journey' });
    expect(within(journey).getByText('Current step: Eval')).toBeInTheDocument();
    expect(within(journey).getByText('Next: run eval')).toBeInTheDocument();
    expect(within(journey).queryByText('Next: optimize candidate')).not.toBeInTheDocument();
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

    await user.click(screen.getByRole('button', { name: 'Set Up First Eval' }));
    expect(screen.getByRole('heading', { name: 'Start First Evaluation' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Run First Eval' }));

    expect(mutate).toHaveBeenCalledWith(
      {
        config_path: '/workspace/configs/v002.yaml',
        category: undefined,
        require_live: true,
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

    const journey = await screen.findByRole('region', { name: 'Operator journey' });
    expect(within(journey).getByText('Current step: Eval')).toBeInTheDocument();
    expect(within(journey).getByText('Next: optimize candidate')).toBeInTheDocument();
    expect(within(journey).getByRole('link', { name: 'Optimize candidate' })).toHaveAttribute(
      'href',
      '/optimize?agent=agent-v002&evalRunId=task-123456'
    );

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
        require_live: true,
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

  it('shows a first-run form instead of a duplicate empty-state CTA when build opens the create flow', () => {
    apiMocks.useStartEval.mockReturnValue({ mutate: vi.fn(), isPending: false });
    apiMocks.useEvalRuns.mockReturnValue({
      data: [],
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    renderPage('/evals?agent=agent-v002&new=1');

    expect(screen.getByRole('heading', { name: 'Start First Evaluation' })).toBeInTheDocument();
    expect(screen.getByText('Saved draft from Build')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Set Up First Eval' })).not.toBeInTheDocument();
  });

  it('explains interrupted eval runs as restart-stopped historical work', () => {
    apiMocks.useStartEval.mockReturnValue({ mutate: vi.fn(), isPending: false });
    apiMocks.useEvalRuns.mockReturnValue({
      data: [
        {
          run_id: 'run-interrupted-1234',
          timestamp: '2026-04-12T14:00:00Z',
          status: 'interrupted',
          progress: 42,
          composite_score: 0,
          total_cases: 0,
          passed_cases: 0,
          mode: 'live',
          continuity: {
            state: 'interrupted',
            label: 'Interrupted by restart',
            detail: 'This task was pending or running when the server restarted. It did not finish; rerun it to continue.',
            is_live: false,
            is_historical: true,
            can_rerun: true,
          },
        },
      ],
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    renderPage('/evals?agent=agent-v002');

    expect(screen.getByText('Interrupted by restart')).toBeInTheDocument();
    expect(
      screen.getByText('This task was pending or running when the server restarted. It did not finish; rerun it to continue.')
    ).toBeInTheDocument();
    expect(screen.getByText('Durable history')).toBeInTheDocument();
  });

  it('explains Agent Improver handoff when opening the eval generator', async () => {
    apiMocks.useStartEval.mockReturnValue({ mutate: vi.fn(), isPending: false });

    renderPage('/evals?agent=agent-v002&generator=1&from=agent-improver');

    expect(await screen.findByText('AI Eval Generation')).toBeInTheDocument();
    expect(screen.getByText('Agent Improver handoff')).toBeInTheDocument();
    expect(screen.getByText(/Generate a formal eval suite from the saved Agent Improver config/)).toBeInTheDocument();
  });

  it('gives the inline eval setup form an accessible close label', async () => {
    const user = userEvent.setup();
    apiMocks.useStartEval.mockReturnValue({ mutate: vi.fn(), isPending: false });

    renderPage('/evals?agent=agent-v002');

    await user.click(screen.getByRole('button', { name: 'Set Up Eval Run' }));

    expect(screen.getByRole('button', { name: 'Close new evaluation form' })).toBeInTheDocument();
  });

  it('avoids rendering a redundant bottom empty state when eval sets are already visible', () => {
    apiMocks.useStartEval.mockReturnValue({ mutate: vi.fn(), isPending: false });

    renderPage('/evals');

    expect(screen.getByText('Eval Sets')).toBeInTheDocument();
    expect(screen.queryByText('Pick an agent to start evaluating')).not.toBeInTheDocument();
  });
});
