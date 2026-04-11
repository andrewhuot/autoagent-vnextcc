import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ChangeReview } from './ChangeReview';

const apiMocks = vi.hoisted(() => ({
  useApplyChange: vi.fn(),
  useChangeAudit: vi.fn(),
  useChangeAuditSummary: vi.fn(),
  useChanges: vi.fn(),
  useRejectChange: vi.fn(),
  useUpdateHunkStatus: vi.fn(),
}));

vi.mock('../lib/api', () => ({
  useApplyChange: apiMocks.useApplyChange,
  useChangeAudit: apiMocks.useChangeAudit,
  useChangeAuditSummary: apiMocks.useChangeAuditSummary,
  useChanges: apiMocks.useChanges,
  useRejectChange: apiMocks.useRejectChange,
  useUpdateHunkStatus: apiMocks.useUpdateHunkStatus,
}));

describe('ChangeReview', () => {
  it('shows candidate config and source eval handoff metadata before apply', async () => {
    const user = userEvent.setup();
    apiMocks.useApplyChange.mockReturnValue({ mutate: vi.fn(), isPending: false });
    apiMocks.useRejectChange.mockReturnValue({ mutate: vi.fn(), isPending: false });
    apiMocks.useUpdateHunkStatus.mockReturnValue({ mutate: vi.fn() });
    apiMocks.useChangeAuditSummary.mockReturnValue({
      data: null,
    });
    apiMocks.useChangeAudit.mockReturnValue({
      data: null,
    });
    apiMocks.useChanges.mockReturnValue({
      data: [
        {
          id: 'card-001',
          title: 'Strengthen root prompt',
          why: 'Fix routing failures from the latest eval run',
          status: 'pending',
          diff_hunks: [
            {
              hunk_id: 'h1',
              file_path: 'prompts.root',
              old_start: 1,
              old_count: 1,
              new_start: 1,
              new_count: 1,
              content: '@@\n- old\n+ new',
              status: 'pending',
            },
          ],
          metrics_before: { quality: 0.72 },
          metrics_after: { quality: 0.84 },
          confidence: {
            score: 0.97,
            explanation: 'Fix routing failures from the latest eval run',
            evidence: ['p-value 0.0300'],
          },
          risk: 'low',
          rollout_plan: 'Review diff -> apply locally -> re-run evals -> deploy canary if metrics hold',
          created_at: '2026-04-01T12:00:00.000Z',
          updated_at: '2026-04-01T12:00:00.000Z',
          candidate_config_version: 12,
          candidate_config_path: '/workspace/.agentlab/configs/v012.yaml',
          source_eval_path: '/workspace/.agentlab/evals/run-123.json',
          experiment_card_id: 'exp-001',
        },
      ],
      isLoading: false,
      isError: false,
    });

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <ChangeReview />
      </QueryClientProvider>
    );

    await user.click(screen.getByRole('button', { name: /Strengthen root prompt/ }));

    expect(screen.getByText('Candidate handoff')).toBeInTheDocument();
    expect(screen.getByText('Candidate v12')).toBeInTheDocument();
    expect(screen.getByText('/workspace/.agentlab/configs/v012.yaml')).toBeInTheDocument();
    expect(screen.getByText('/workspace/.agentlab/evals/run-123.json')).toBeInTheDocument();
    expect(screen.getByText('Experiment exp-001')).toBeInTheDocument();
    expect(screen.getByText(/Apply sets this candidate as the local active config/)).toBeInTheDocument();
  });
});
