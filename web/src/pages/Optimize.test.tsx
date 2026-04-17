import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Optimize } from './Optimize';
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

const wsHandlers = new Map<string, (payload: unknown) => void>();

const apiMocks = vi.hoisted(() => ({
  useAgent: vi.fn(),
  useAgents: vi.fn(),
  useApproveReview: vi.fn(),
  useOptimizeHistory: vi.fn(),
  usePendingReviews: vi.fn(),
  useRejectReview: vi.fn(),
  useStartOptimize: vi.fn(),
  useTaskStatus: vi.fn(),
}));

const workbenchApiMocks = vi.hoisted(() => ({
  useWorkbenchBridge: vi.fn(),
}));

const toastMocks = vi.hoisted(() => ({
  toastError: vi.fn(),
  toastInfo: vi.fn(),
  toastSuccess: vi.fn(),
}));

vi.mock('../lib/api', () => ({
  useAgent: apiMocks.useAgent,
  useAgents: apiMocks.useAgents,
  useApproveReview: apiMocks.useApproveReview,
  useOptimizeHistory: apiMocks.useOptimizeHistory,
  usePendingReviews: apiMocks.usePendingReviews,
  useRejectReview: apiMocks.useRejectReview,
  useStartOptimize: apiMocks.useStartOptimize,
  useTaskStatus: apiMocks.useTaskStatus,
}));

vi.mock('../lib/workbench-api', () => ({
  useWorkbenchBridge: workbenchApiMocks.useWorkbenchBridge,
}));

vi.mock('../lib/websocket', () => ({
  wsClient: {
    connect: vi.fn(),
    onMessage: vi.fn((_type: string, handler: (payload: unknown) => void) => {
      wsHandlers.set(_type, handler);
      return () => {
        if (wsHandlers.get(_type) === handler) {
          wsHandlers.delete(_type);
        }
      };
    }),
  },
}));

vi.mock('./LiveOptimize', () => ({
  LiveOptimize: () => <div>Live Optimize Content</div>,
}));

vi.mock('../lib/toast', () => ({
  toastError: toastMocks.toastError,
  toastInfo: toastMocks.toastInfo,
  toastSuccess: toastMocks.toastSuccess,
}));

function renderOptimize(initialEntry: InitialEntry = '/optimize') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/optimize" element={<Optimize />} />
        <Route path="/evals" element={<div>Eval Page</div>} />
        <Route path="/configs" element={<div>Configs Page</div>} />
        <Route path="/improvements" element={<div>Improvements Page</div>} />
      </Routes>
    </MemoryRouter>
  );
}

describe('Optimize', () => {
  beforeEach(() => {
    wsHandlers.clear();
    window.sessionStorage.clear();
    useActiveAgentStore.getState().clearActiveAgent();
    toastMocks.toastError.mockReset();
    toastMocks.toastInfo.mockReset();
    toastMocks.toastSuccess.mockReset();

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
    apiMocks.usePendingReviews.mockReturnValue({
      data: [],
      isLoading: false,
      refetch: vi.fn(),
    });
    apiMocks.useApproveReview.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    });
    apiMocks.useRejectReview.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    });
    apiMocks.useTaskStatus.mockReturnValue({
      data: null,
      refetch: vi.fn(),
    });
    workbenchApiMocks.useWorkbenchBridge.mockReturnValue({
      data: null,
      isLoading: false,
      isError: false,
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
    expect((await screen.findAllByText('Order Guardian')).length).toBeGreaterThan(0);

    await user.click(screen.getByRole('button', { name: 'Start Optimization' }));

    expect(mutate).toHaveBeenCalledWith(
      expect.objectContaining({
        config_path: '/workspace/configs/v002.yaml',
        require_human_approval: true,
      }),
      expect.any(Object)
    );
  });

  it('passes the selected eval run id through to the optimize request when launched from Eval Runs', async () => {
    const user = userEvent.setup();
    const mutate = vi.fn((_params, options) => {
      options?.onSuccess?.({ task_id: 'opt-eval-123', message: 'Optimization started' });
    });
    apiMocks.useStartOptimize.mockReturnValue({
      mutate,
      isPending: false,
    });

    renderOptimize({
      pathname: '/optimize',
      search: '?agent=agent-v002',
      state: { evalRunId: 'eval-run-1234' },
    });

    await user.click(screen.getByRole('button', { name: 'Start Optimization' }));

    expect(mutate).toHaveBeenCalledWith(
      expect.objectContaining({
        config_path: '/workspace/configs/v002.yaml',
        eval_run_id: 'eval-run-1234',
        require_eval_evidence: true,
      }),
      expect.any(Object)
    );
  });

  it('passes evalRunId from the URL through to the optimize request', async () => {
    const user = userEvent.setup();
    const mutate = vi.fn((_params, options) => {
      options?.onSuccess?.({ task_id: 'opt-query-123', message: 'Optimization started' });
    });
    apiMocks.useStartOptimize.mockReturnValue({
      mutate,
      isPending: false,
    });

    renderOptimize('/optimize?agent=agent-v002&evalRunId=eval-run-query');

    await user.click(screen.getByRole('button', { name: 'Start Optimization' }));

    expect(mutate).toHaveBeenCalledWith(
      expect.objectContaining({
        config_path: '/workspace/configs/v002.yaml',
        eval_run_id: 'eval-run-query',
        require_eval_evidence: true,
      }),
      expect.any(Object)
    );
  });

  it('explains that Workbench candidates must run Eval before Optimize', () => {
    apiMocks.useStartOptimize.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    });
    workbenchApiMocks.useWorkbenchBridge.mockReturnValue({
      data: {
        bridge: {
          kind: 'workbench_eval_optimize',
          schema_version: 1,
          journey_id: 'journey-wb-test',
          candidate: {
            candidate_id: 'candidate-wb-test',
            project_id: 'wb-test',
            run_id: 'run-wb-test',
            version: 3,
            target: 'portable',
            environment: 'draft',
            agent_name: 'Airline Support Agent',
            validation_status: 'passed',
            review_gate_status: 'review_required',
            generated_config_hash: 'sha256:abc',
            config_path: '/workspace/configs/workbench-v003.yaml',
            eval_cases_path: '/workspace/evals/cases/generated_build.yaml',
            export_targets: ['adk', 'cx'],
          },
          evaluation: {
            status: 'ready',
            readiness_state: 'ready_for_eval',
            label: 'Ready for Eval',
            description: 'The Workbench candidate is saved and ready for an Eval run.',
            primary_action_label: 'Open Eval with this candidate',
            primary_action_target: '/evals?new=1&from=workbench&workbenchProjectId=wb-test',
            start_endpoint: '/api/eval/run',
            blocking_reasons: [],
            request: {
              config_path: '/workspace/configs/workbench-v003.yaml',
              dataset_path: '/workspace/evals/cases/generated_build.yaml',
              split: 'all',
            },
          },
          optimization: {
            status: 'awaiting_eval_run',
            readiness_state: 'awaiting_eval_run',
            label: 'Run Eval before Optimize',
            description: 'Optimize is waiting for a completed Eval run for this saved Workbench candidate.',
            primary_action_label: 'Open Eval with this candidate',
            primary_action_target: '/evals?new=1&from=workbench&workbenchProjectId=wb-test',
            requires_eval_run: true,
            request_template: {
              window: 100,
              force: true,
              require_human_approval: true,
              require_eval_evidence: true,
              config_path: '/workspace/configs/workbench-v003.yaml',
              eval_run_id: null,
              mode: 'standard',
              objective: 'Improve failures.',
              guardrails: [],
              research_algorithm: '',
              budget_cycles: 10,
              budget_dollars: 50,
            },
            start_endpoint: '/api/optimize/run',
            blocking_reasons: ['Run Eval first; Optimize requires a completed eval run.'],
          },
        },
      },
      isLoading: false,
      isError: false,
    });

    renderOptimize('/optimize?from=workbench&workbenchProjectId=wb-test');

    expect(screen.getByText('Run Eval first')).toBeInTheDocument();
    expect(
      screen.getByText('Airline Support Agent is saved, but Optimize needs a completed Eval run from this Workbench candidate.')
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open Eval with this candidate' })).toHaveAttribute(
      'href',
      '/evals?new=1&from=workbench&workbenchProjectId=wb-test'
    );
    expect(screen.getByRole('button', { name: 'Start Optimization' })).toBeDisabled();
  });

  it('starts Optimize from a Workbench candidate after Eval is complete', async () => {
    const user = userEvent.setup();
    const mutate = vi.fn((_params, options) => {
      options?.onSuccess?.({ task_id: 'opt-workbench-123', message: 'Optimization started' });
    });
    apiMocks.useStartOptimize.mockReturnValue({
      mutate,
      isPending: false,
    });
    workbenchApiMocks.useWorkbenchBridge.mockReturnValue({
      data: {
        bridge: {
          kind: 'workbench_eval_optimize',
          schema_version: 1,
          journey_id: 'journey-wb-test',
          candidate: {
            candidate_id: 'candidate-wb-test',
            project_id: 'wb-test',
            run_id: 'run-wb-test',
            version: 3,
            target: 'portable',
            environment: 'draft',
            agent_name: 'Airline Support Agent',
            validation_status: 'passed',
            review_gate_status: 'review_required',
            generated_config_hash: 'sha256:abc',
            config_path: '/workspace/configs/workbench-v003.yaml',
            eval_cases_path: '/workspace/evals/cases/generated_build.yaml',
            export_targets: ['adk', 'cx'],
          },
          evaluation: {
            status: 'ready',
            readiness_state: 'ready_for_eval',
            label: 'Ready for Eval',
            description: 'The Workbench candidate is saved and ready for an Eval run.',
            primary_action_label: 'Open Eval with this candidate',
            primary_action_target: '/evals?new=1&from=workbench&workbenchProjectId=wb-test',
            start_endpoint: '/api/eval/run',
            blocking_reasons: [],
            request: {
              config_path: '/workspace/configs/workbench-v003.yaml',
              dataset_path: '/workspace/evals/cases/generated_build.yaml',
              split: 'all',
            },
          },
          optimization: {
            status: 'ready',
            readiness_state: 'ready_for_optimize',
            label: 'Ready for Optimize',
            description: 'Eval has run for this Workbench candidate, so Optimize can use that failure context.',
            primary_action_label: 'Start Optimize from Eval run',
            primary_action_target: '/optimize?from=workbench&workbenchProjectId=wb-test&evalRunId=eval-workbench-123',
            requires_eval_run: true,
            request_template: {
              window: 100,
              force: true,
              require_human_approval: true,
              require_eval_evidence: true,
              config_path: '/workspace/configs/workbench-v003.yaml',
              eval_run_id: 'eval-workbench-123',
              mode: 'standard',
              objective: 'Improve failures.',
              guardrails: [],
              research_algorithm: '',
              budget_cycles: 10,
              budget_dollars: 50,
            },
            start_endpoint: '/api/optimize/run',
            blocking_reasons: [],
          },
        },
      },
      isLoading: false,
      isError: false,
    });

    renderOptimize('/optimize?from=workbench&workbenchProjectId=wb-test&evalRunId=eval-workbench-123');

    expect(screen.getByText('Workbench Eval context ready')).toBeInTheDocument();
    expect(screen.getByText(/eval-work/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Start Optimization' }));

    expect(mutate).toHaveBeenCalledWith(
      expect.objectContaining({
        config_path: '/workspace/configs/workbench-v003.yaml',
        eval_run_id: 'eval-workbench-123',
        require_eval_evidence: true,
      }),
      expect.any(Object)
    );
  });

  it('warns before starting a new run when a review is already pending', async () => {
    const user = userEvent.setup();
    const mutate = vi.fn((_params, options) => {
      options?.onSuccess?.({ task_id: 'opt-123456', message: 'Optimization started' });
    });
    apiMocks.useStartOptimize.mockReturnValue({
      mutate,
      isPending: false,
    });
    apiMocks.usePendingReviews.mockReturnValue({
      data: [
        {
          attempt_id: 'attempt-pending',
          proposed_config: { prompts: { root: 'new' } },
          current_config: { prompts: { root: 'old' } },
          config_diff: '- root: old\n+ root: new',
          score_before: 72,
          score_after: 84,
          change_description: 'Strengthen root prompt',
          reasoning: 'Improve routing clarity and answer quality',
          created_at: '2026-04-01T12:00:00.000Z',
          strategy: 'simple',
          selected_operator_family: 'prompts',
          governance_notes: ['Protected safety floor at 99%.'],
          deploy_strategy: 'immediate',
        },
      ],
      isLoading: false,
      refetch: vi.fn(),
    });

    renderOptimize('/optimize?agent=agent-v002');

    await user.click(screen.getByRole('button', { name: 'Start Optimization' }));

    expect(mutate).toHaveBeenCalledWith(
      expect.objectContaining({
        require_human_approval: true,
      }),
      expect.any(Object)
    );
    expect(
      toastMocks.toastInfo.mock.calls.some(
        ([title, description]) =>
          String(title).includes('Pending review') &&
          String(description).includes('awaiting human review')
      )
    ).toBe(true);
  });

  it('guides operators to review proposals only when proposals are pending', () => {
    apiMocks.useStartOptimize.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    });
    apiMocks.usePendingReviews.mockReturnValue({
      data: [
        {
          attempt_id: 'attempt-pending',
          proposed_config: { prompts: { root: 'new' } },
          current_config: { prompts: { root: 'old' } },
          config_diff: '- root: old\n+ root: new',
          score_before: 72,
          score_after: 84,
          change_description: 'Strengthen root prompt',
          reasoning: 'Improve routing clarity and answer quality',
          created_at: '2026-04-01T12:00:00.000Z',
          strategy: 'simple',
          selected_operator_family: 'prompts',
          governance_notes: ['Protected safety floor at 99%.'],
          deploy_strategy: 'immediate',
        },
      ],
      isLoading: false,
      refetch: vi.fn(),
    });

    renderOptimize('/optimize?agent=agent-v002&evalRunId=eval-run-1234');

    const journey = screen.getByRole('region', { name: 'Operator journey' });
    expect(within(journey).getByText('Current step: Optimize')).toBeInTheDocument();
    expect(within(journey).getByText('Next: review proposals')).toBeInTheDocument();
    expect(within(journey).getByRole('link', { name: 'Review proposals' })).toHaveAttribute(
      'href',
      '/improvements?tab=review'
    );
  });

  it('does not show review guidance before an optimize proposal exists', () => {
    apiMocks.useStartOptimize.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    });

    renderOptimize('/optimize?agent=agent-v002&evalRunId=eval-run-1234');

    const journey = screen.getByRole('region', { name: 'Operator journey' });
    expect(within(journey).getByText('Current step: Optimize')).toBeInTheDocument();
    expect(within(journey).getByText('Next: start optimization')).toBeInTheDocument();
    expect(within(journey).queryByText('Next: review proposals')).not.toBeInTheDocument();
  });

  it('shows a prominent live progress section with step label and elapsed time', async () => {
    const user = userEvent.setup();
    const mutate = vi.fn((_params, options) => {
      options?.onSuccess?.({ task_id: 'opt-123456', message: 'Optimization started' });
    });
    const createdAt = new Date(Date.now() - 35_000).toISOString();

    apiMocks.useStartOptimize.mockReturnValue({
      mutate,
      isPending: false,
    });
    apiMocks.useTaskStatus.mockImplementation((taskId: string | null) => ({
      data: taskId
        ? {
            task_id: taskId,
            task_type: 'optimize',
            status: 'running',
            progress: 35,
            result: null,
            error: null,
            created_at: createdAt,
            updated_at: createdAt,
          }
        : null,
      refetch: vi.fn(),
    }));

    renderOptimize('/optimize?agent=agent-v002');

    await user.click(screen.getByRole('button', { name: 'Start Optimization' }));

    expect((await screen.findAllByText('Generating candidates...')).length).toBeGreaterThan(0);
    expect(screen.getByText(/3\ds elapsed/)).toBeInTheDocument();
    expect(screen.getByRole('progressbar', { name: 'Optimization progress' })).toHaveAttribute(
      'aria-valuenow',
      '35'
    );
  });

  it('keeps advanced settings collapsed until the operator expands them', async () => {
    const user = userEvent.setup();
    apiMocks.useStartOptimize.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    });

    renderOptimize('/optimize?agent=agent-v002');

    await user.click(screen.getByRole('button', { name: 'Research' }));

    expect(screen.queryByLabelText('Objective')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /advanced settings/i }));

    expect(screen.getByLabelText('Objective')).toBeInTheDocument();
  });

  it('shows inline accepted results with diff, governance notes, and next actions', async () => {
    const user = userEvent.setup();
    const mutate = vi.fn((_params, options) => {
      options?.onSuccess?.({ task_id: 'opt-123456', message: 'Optimization started' });
    });
    apiMocks.useStartOptimize.mockReturnValue({
      mutate,
      isPending: false,
    });
    apiMocks.useTaskStatus.mockImplementation((taskId: string | null) => ({
      data: taskId
        ? {
            task_id: taskId,
            task_type: 'optimize',
            status: 'completed',
            progress: 100,
            result: {
              accepted: true,
              status_message: 'Accepted for rollout',
              change_description: 'Raised tool confidence threshold for routing.',
              config_diff: ['- tool_confidence: 0.42', '+ tool_confidence: 0.58'].join('\n'),
              score_before: 0.72,
              score_after: 0.84,
              deploy_message: 'Deployed as active config v12.',
              search_strategy: 'bandit',
              selected_operator_family: 'routing',
              governance_notes: ['Protected safety floor at 99%.'],
              global_dimensions: {
                task_success_rate: 0.84,
                safety_compliance: 0.99,
              },
            },
            error: null,
            created_at: '2026-04-01T12:00:00.000Z',
            updated_at: '2026-04-01T12:01:00.000Z',
          }
        : null,
      refetch: vi.fn(),
    }));

    renderOptimize('/optimize?agent=agent-v002');

    await user.click(screen.getByRole('button', { name: 'Start Optimization' }));

    expect(await screen.findByText('Accepted for rollout')).toBeInTheDocument();
    expect(screen.getByText('Raised tool confidence threshold for routing.')).toBeInTheDocument();
    expect(screen.getByText('Protected safety floor at 99%.')).toBeInTheDocument();
    expect(screen.getByText('Deployed as active config v12.')).toBeInTheDocument();
    expect(screen.getByText('- tool_confidence: 0.42')).toBeInTheDocument();
    expect(screen.getByText('+ tool_confidence: 0.58')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Re-run Eval to verify' }));
    expect(await screen.findByText('Eval Page')).toBeInTheDocument();
  });

  it('explains the blocked optimize state when no agent is selected', () => {
    apiMocks.useStartOptimize.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    });

    renderOptimize('/optimize');

    expect(screen.getByText('Blocked')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Pick an agent to optimize' })).toBeInTheDocument();
    expect(
      screen.getByText('Next: Open Build to create a saved config, or select an existing agent from the library.')
    ).toBeInTheDocument();
  });

  it('shows richer history rows and expandable attempt details', async () => {
    const user = userEvent.setup();
    apiMocks.useStartOptimize.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    });
    apiMocks.useOptimizeHistory.mockReturnValue({
      data: [
        {
          attempt_id: 'attempt-accepted',
          timestamp: '2026-04-01T12:00:00.000Z',
          change_description: 'Tightened escalation threshold for risky refund requests.',
          config_diff: ['- escalation_threshold: 0.71', '+ escalation_threshold: 0.63'].join('\n'),
          config_section: 'routing',
          status: 'accepted',
          score_before: 72,
          score_after: 81,
          score_delta: 9,
          significance_p_value: 0.03,
          significance_delta: 0.09,
          significance_n: 41,
          health_context: '{"failure_family":"refund_risk","error_rate":0.14}',
        },
        {
          attempt_id: 'attempt-noop',
          timestamp: '2026-04-01T11:30:00.000Z',
          change_description: 'Candidate failed acceptance checks and made no config changes.',
          config_diff: '',
          config_section: 'prompting',
          status: 'rejected_noop',
          score_before: 72,
          score_after: 72,
          score_delta: 0,
          significance_p_value: 1,
          significance_delta: 0,
          significance_n: 0,
          health_context: '{"failure_family":"tool_error"}',
        },
      ],
      isLoading: false,
      refetch: vi.fn(),
    });

    renderOptimize('/optimize?agent=agent-v002');

    expect(screen.getByText('+9.0')).toBeInTheDocument();
    expect(screen.getAllByText('No config change').length).toBeGreaterThan(0);

    await user.click(screen.getByRole('button', { name: /tightened escalation threshold/i }));

    expect(await screen.findByText('Deployment status')).toBeInTheDocument();
    expect(screen.getAllByText('Deployed to the active config').length).toBeGreaterThan(0);
    expect(screen.getByText('41 paired eval cases')).toBeInTheDocument();
    expect(screen.getByText('- escalation_threshold: 0.71')).toBeInTheDocument();
    expect(screen.getByText('+ escalation_threshold: 0.63')).toBeInTheDocument();
  });

  it('renders pending review cards above history with reasoning, governance notes, and diff', () => {
    apiMocks.useStartOptimize.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    });
    apiMocks.usePendingReviews.mockReturnValue({
      data: [
        {
          attempt_id: 'attempt-pending',
          proposed_config: { prompts: { root: 'new' } },
          current_config: { prompts: { root: 'old' } },
          config_diff: '- root: old\n+ root: new',
          score_before: 72,
          score_after: 84,
          change_description: 'Strengthen root prompt',
          reasoning: 'Improve routing clarity and answer quality',
          created_at: '2026-04-01T12:00:00.000Z',
          strategy: 'simple',
          selected_operator_family: 'prompts',
          governance_notes: ['Protected safety floor at 99%.'],
          deploy_strategy: 'immediate',
        },
      ],
      isLoading: false,
      refetch: vi.fn(),
    });

    renderOptimize('/optimize?agent=agent-v002');

    expect(screen.getByText('Pending Reviews')).toBeInTheDocument();
    expect(screen.getByText('Strengthen root prompt')).toBeInTheDocument();
    expect(screen.getByText('Improve routing clarity and answer quality')).toBeInTheDocument();
    expect(screen.getByText('Protected safety floor at 99%.')).toBeInTheDocument();
    expect(screen.getByText('- root: old')).toBeInTheDocument();
    expect(screen.getByText('+ root: new')).toBeInTheDocument();
  });

  it('approves a pending review and shows a success toast', async () => {
    const user = userEvent.setup();
    const approveMutate = vi.fn((_params, options) => {
      options?.onSuccess?.({
        status: 'approved',
        attempt_id: 'attempt-pending',
        message: 'Pending review approved and deployed',
        deploy_message: 'Deployed as active config v12.',
      });
    });
    apiMocks.useStartOptimize.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    });
    apiMocks.usePendingReviews.mockReturnValue({
      data: [
        {
          attempt_id: 'attempt-pending',
          proposed_config: { prompts: { root: 'new' } },
          current_config: { prompts: { root: 'old' } },
          config_diff: '- root: old\n+ root: new',
          score_before: 72,
          score_after: 84,
          change_description: 'Strengthen root prompt',
          reasoning: 'Improve routing clarity and answer quality',
          created_at: '2026-04-01T12:00:00.000Z',
          strategy: 'simple',
          selected_operator_family: 'prompts',
          governance_notes: ['Protected safety floor at 99%.'],
          deploy_strategy: 'immediate',
        },
      ],
      isLoading: false,
      refetch: vi.fn(),
    });
    apiMocks.useApproveReview.mockReturnValue({
      mutate: approveMutate,
      isPending: false,
    });

    renderOptimize('/optimize?agent=agent-v002');

    await user.click(screen.getByRole('button', { name: 'Approve & Deploy' }));

    expect(approveMutate).toHaveBeenCalledWith(
      { attemptId: 'attempt-pending' },
      expect.any(Object)
    );
    expect(toastMocks.toastSuccess).toHaveBeenCalledWith(
      'Review approved',
      'Deployed as active config v12.'
    );
  });

  it('rejects a pending review and shows an info toast', async () => {
    const user = userEvent.setup();
    const rejectMutate = vi.fn((_params, options) => {
      options?.onSuccess?.({
        status: 'rejected',
        attempt_id: 'attempt-pending',
        message: 'Pending review rejected and discarded',
        deploy_message: null,
      });
    });
    apiMocks.useStartOptimize.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    });
    apiMocks.usePendingReviews.mockReturnValue({
      data: [
        {
          attempt_id: 'attempt-pending',
          proposed_config: { prompts: { root: 'new' } },
          current_config: { prompts: { root: 'old' } },
          config_diff: '- root: old\n+ root: new',
          score_before: 72,
          score_after: 84,
          change_description: 'Strengthen root prompt',
          reasoning: 'Improve routing clarity and answer quality',
          created_at: '2026-04-01T12:00:00.000Z',
          strategy: 'simple',
          selected_operator_family: 'prompts',
          governance_notes: ['Protected safety floor at 99%.'],
          deploy_strategy: 'immediate',
        },
      ],
      isLoading: false,
      refetch: vi.fn(),
    });
    apiMocks.useRejectReview.mockReturnValue({
      mutate: rejectMutate,
      isPending: false,
    });

    renderOptimize('/optimize?agent=agent-v002');

    await user.click(screen.getByRole('button', { name: 'Reject' }));

    expect(rejectMutate).toHaveBeenCalledWith(
      { attemptId: 'attempt-pending' },
      expect.any(Object)
    );
    expect(toastMocks.toastInfo).toHaveBeenCalledWith(
      'Review rejected',
      'Pending review rejected and discarded'
    );
  });
});
