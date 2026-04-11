import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ResultsExplorer } from './ResultsExplorer';

const apiMocks = vi.hoisted(() => ({
  useResultRuns: vi.fn(),
  useResultsRun: vi.fn(),
  useResultsDiff: vi.fn(),
  useAddResultAnnotation: vi.fn(),
  useExportEvalResults: vi.fn(),
}));

let annotateSpy: ReturnType<typeof vi.fn>;

vi.mock('../lib/api', () => ({
  useResultRuns: apiMocks.useResultRuns,
  useResultsRun: apiMocks.useResultsRun,
  useResultsDiff: apiMocks.useResultsDiff,
  useAddResultAnnotation: apiMocks.useAddResultAnnotation,
  useExportEvalResults: apiMocks.useExportEvalResults,
}));

vi.mock('../lib/toast', () => ({
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
}));

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/results/run-api']}>
      <Routes>
        <Route path="/results/:runId" element={<ResultsExplorer />} />
        <Route path="/results" element={<ResultsExplorer />} />
      </Routes>
    </MemoryRouter>
  );
}

describe('ResultsExplorer', () => {
  beforeEach(() => {
    annotateSpy = vi.fn();
    const exportRun = vi.fn();

    apiMocks.useResultRuns.mockReturnValue({
      data: {
        runs: [
          {
            run_id: 'run-api',
            timestamp: '2026-03-31T12:00:00Z',
            mode: 'mock',
            config_snapshot: { variant: 'candidate' },
            summary: {
              total: 2,
              passed: 1,
              failed: 1,
              metrics: {
                quality: { mean: 0.7, median: 0.7, std: 0.25, min: 0.45, max: 0.95, histogram: [0, 0, 0, 0, 1, 0, 0, 0, 0, 1] },
                composite: { mean: 0.83, median: 0.83, std: 0.12, min: 0.71, max: 0.95, histogram: [0, 0, 0, 0, 0, 0, 1, 0, 0, 1] },
              },
            },
          },
          {
            run_id: 'run-baseline',
            timestamp: '2026-03-30T12:00:00Z',
            mode: 'mock',
            config_snapshot: { variant: 'baseline' },
            summary: {
              total: 2,
              passed: 2,
              failed: 0,
              metrics: {
                quality: { mean: 0.82, median: 0.82, std: 0.1, min: 0.72, max: 0.92, histogram: [0, 0, 0, 0, 0, 0, 0, 1, 0, 1] },
                composite: { mean: 0.88, median: 0.88, std: 0.06, min: 0.82, max: 0.94, histogram: [0, 0, 0, 0, 0, 0, 0, 0, 1, 1] },
              },
            },
          },
        ],
        count: 2,
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    apiMocks.useResultsRun.mockReturnValue({
      data: {
        run_id: 'run-api',
        timestamp: '2026-03-31T12:00:00Z',
        mode: 'mock',
        config_snapshot: { variant: 'candidate' },
        summary: {
          total: 2,
          passed: 1,
          failed: 1,
          metrics: {
            quality: { mean: 0.7, median: 0.7, std: 0.25, min: 0.45, max: 0.95, histogram: [0, 0, 0, 0, 1, 0, 0, 0, 0, 1] },
            composite: { mean: 0.83, median: 0.83, std: 0.12, min: 0.71, max: 0.95, histogram: [0, 0, 0, 0, 0, 0, 1, 0, 0, 1] },
            safety: { mean: 1, median: 1, std: 0, min: 1, max: 1, histogram: [0, 0, 0, 0, 0, 0, 0, 0, 0, 2] },
          },
        },
        examples: [
          {
            example_id: 'case-orders',
            category: 'happy_path',
            input: { user_message: 'Where is my order?' },
            expected: { expected_specialist: 'orders' },
            actual: { response: 'Your order is on the way.', specialist_used: 'orders' },
            scores: {
              quality: { value: 0.95, reasoning: '' },
              composite: { value: 0.95, reasoning: '' },
            },
            passed: true,
            failure_reasons: [],
            annotations: [],
          },
          {
            example_id: 'case-routing',
            category: 'regression',
            input: { user_message: 'Connect me with billing' },
            expected: { expected_specialist: 'billing' },
            actual: { response: 'Support can help with that.', specialist_used: 'support' },
            scores: {
              quality: { value: 0.45, reasoning: 'routing mismatch' },
              composite: { value: 0.71, reasoning: 'routing mismatch' },
            },
            passed: false,
            failure_reasons: ['routing mismatch'],
            annotations: [
              {
                author: 'qa',
                timestamp: '2026-03-31T14:00:00Z',
                type: 'comment',
                content: 'Needs billing-specific routing rule.',
                score_override: null,
              },
            ],
          },
        ],
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    apiMocks.useResultsDiff.mockReturnValue({
      data: {
        baseline_run_id: 'run-baseline',
        candidate_run_id: 'run-api',
        new_failures: 1,
        new_passes: 0,
        changed_examples: [
          {
            example_id: 'case-routing',
            before_passed: true,
            after_passed: false,
            score_delta: -0.19,
          },
        ],
      },
      isLoading: false,
      isError: false,
    });

    apiMocks.useAddResultAnnotation.mockReturnValue({
      mutate: annotateSpy,
      isPending: false,
    });

    apiMocks.useExportEvalResults.mockReturnValue({
      mutate: exportRun,
      isPending: false,
    });
  });

  it('renders explorer summary, filters failures, drills in, annotates, and shows run diff', async () => {
    const user = userEvent.setup();
    renderPage();

    expect(screen.getByRole('heading', { name: 'Results Explorer' })).toBeInTheDocument();
    expect(screen.getByText('50.0%')).toBeInTheDocument();
    expect(screen.getAllByText('routing mismatch').length).toBeGreaterThan(0);

    await user.selectOptions(screen.getByLabelText('Outcome filter'), 'fail');

    expect(screen.queryByText('Where is my order?')).not.toBeInTheDocument();
    expect(screen.getByText('Connect me with billing')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Inspect case-routing' }));

    expect(screen.getByText(/Support can help with that\./)).toBeInTheDocument();

    await user.type(screen.getByLabelText('Annotation'), 'False positive after manual review.');
    await user.click(screen.getByRole('button', { name: 'Save annotation' }));

    expect(annotateSpy).toHaveBeenCalledWith(
      {
        runId: 'run-api',
        exampleId: 'case-routing',
        author: 'web',
        type: 'comment',
        content: 'False positive after manual review.',
        score_override: null,
      },
      expect.any(Object)
    );

    await user.selectOptions(screen.getByLabelText('Compare to'), 'run-baseline');

    expect(screen.getByText('New failures')).toBeInTheDocument();
    expect(screen.getAllByText('case-routing').length).toBeGreaterThan(0);
  });

  it('renders journey navigation: back to evals and forward to compare/optimize', () => {
    renderPage();

    const backLink = screen.getByRole('link', { name: /Back to Eval Runs/ });
    expect(backLink).toBeInTheDocument();
    expect(backLink).toHaveAttribute('href', '/evals');

    expect(screen.getByRole('link', { name: /Compare Configs/ })).toHaveAttribute('href', '/compare');

    const optimizeLink = screen.getByRole('link', { name: /Optimize Agent/ });
    expect(optimizeLink).toBeInTheDocument();
    expect(optimizeLink).toHaveAttribute('href', expect.stringContaining('/optimize'));
  });
});
