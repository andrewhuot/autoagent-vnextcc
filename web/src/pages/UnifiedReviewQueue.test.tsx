import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { UnifiedReviewQueue } from './UnifiedReviewQueue';

const apiMocks = vi.hoisted(() => ({
  useUnifiedReviews: vi.fn(),
  useApproveUnifiedReview: vi.fn(),
  useRejectUnifiedReview: vi.fn(),
  useChangeAudit: vi.fn(),
  useVerifyImprovement: vi.fn(),
}));

vi.mock('../lib/api', () => ({
  useUnifiedReviews: apiMocks.useUnifiedReviews,
  useApproveUnifiedReview: apiMocks.useApproveUnifiedReview,
  useRejectUnifiedReview: apiMocks.useRejectUnifiedReview,
  useChangeAudit: apiMocks.useChangeAudit,
  useVerifyImprovement: apiMocks.useVerifyImprovement,
}));

describe('UnifiedReviewQueue', () => {
  beforeEach(() => {
    apiMocks.useUnifiedReviews.mockReturnValue({
      data: [
        {
          id: 'attempt-123',
          source: 'optimizer',
          status: 'pending',
          title: 'Improve refund routing',
          description: 'Tighten the routing threshold for refund conversations.',
          score_before: 0.72,
          score_after: 0.84,
          score_delta: 0.12,
          risk_class: 'medium',
          diff_summary: '- threshold: 0.40\n+ threshold: 0.55',
          created_at: '2026-04-01T12:00:00.000Z',
          strategy: 'bandit',
          operator_family: 'routing',
          has_detailed_audit: false,
          patch_bundle: null,
          verification: null,
        },
        {
          id: 'card-456',
          source: 'change_card',
          status: 'pending',
          title: 'Add fallback verification',
          description: 'Require email plus ZIP before account access.',
          score_before: 0.81,
          score_after: 0.87,
          score_delta: 0.06,
          risk_class: 'low',
          diff_summary: '- old\n+ new',
          created_at: '2026-04-01T13:00:00.000Z',
          strategy: null,
          operator_family: null,
          has_detailed_audit: true,
          patch_bundle: null,
          verification: null,
        },
      ],
      isLoading: false,
      isError: false,
    });
    apiMocks.useApproveUnifiedReview.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    });
    apiMocks.useRejectUnifiedReview.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    });
    apiMocks.useChangeAudit.mockReturnValue({ data: null });
    apiMocks.useVerifyImprovement.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    });
  });

  it('shows a verify action for optimizer proposals only', async () => {
    render(<UnifiedReviewQueue />);

    await userEvent.setup().click(screen.getByRole('button', { name: /Improve refund routing/i }));
    expect(screen.getByRole('button', { name: 'Verify candidate' })).toBeInTheDocument();

    await userEvent.setup().click(screen.getByRole('button', { name: /Add fallback verification/i }));
    expect(screen.queryByRole('button', { name: 'Verify candidate' })).not.toBeInTheDocument();
  });

  it('runs verification before approval when requested', async () => {
    const verifyMutate = vi.fn();
    apiMocks.useVerifyImprovement.mockReturnValue({
      mutate: verifyMutate,
      isPending: false,
    });

    render(<UnifiedReviewQueue />);

    await userEvent.setup().click(screen.getByRole('button', { name: /Improve refund routing/i }));
    await userEvent.setup().click(screen.getByRole('button', { name: 'Verify candidate' }));

    expect(verifyMutate).toHaveBeenCalledWith({ attemptId: 'attempt-123' });
  });
});
