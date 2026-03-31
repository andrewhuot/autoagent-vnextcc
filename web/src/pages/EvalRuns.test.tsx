import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { render, screen } from '@testing-library/react';
import { EvalRuns } from './EvalRuns';

const apiMocks = vi.hoisted(() => ({
  useApplyCurriculum: vi.fn(),
  useConfigs: vi.fn(),
  useCurriculumBatches: vi.fn(),
  useEvalRuns: vi.fn(),
  useGenerateCurriculum: vi.fn(),
  useStartEval: vi.fn(),
}));

vi.mock('../lib/api', () => ({
  useApplyCurriculum: apiMocks.useApplyCurriculum,
  useConfigs: apiMocks.useConfigs,
  useCurriculumBatches: apiMocks.useCurriculumBatches,
  useEvalRuns: apiMocks.useEvalRuns,
  useGenerateCurriculum: apiMocks.useGenerateCurriculum,
  useStartEval: apiMocks.useStartEval,
}));

vi.mock('../lib/websocket', () => ({
  wsClient: {
    onMessage: vi.fn(() => () => undefined),
  },
}));

vi.mock('../lib/toast', () => ({
  toastError: vi.fn(),
  toastInfo: vi.fn(),
  toastSuccess: vi.fn(),
}));

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/evals']}>
      <EvalRuns />
    </MemoryRouter>
  );
}

describe('EvalRuns', () => {
  beforeEach(() => {
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
    apiMocks.useConfigs.mockReturnValue({ data: [], isLoading: false });
    apiMocks.useCurriculumBatches.mockReturnValue({
      data: { batches: [], progression: [] },
      isLoading: false,
    });
    apiMocks.useStartEval.mockReturnValue({ mutate: vi.fn(), isPending: false });
    apiMocks.useGenerateCurriculum.mockReturnValue({ mutate: vi.fn(), isPending: false });
    apiMocks.useApplyCurriculum.mockReturnValue({ mutate: vi.fn(), isPending: false });
  });

  it('shows an eval mode badge for each run', () => {
    renderPage();

    expect(screen.getByText('mixed')).toBeInTheDocument();
  });
});
