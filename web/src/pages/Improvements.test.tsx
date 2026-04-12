import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Improvements } from './Improvements';

const apiMocks = vi.hoisted(() => ({
  useExperiments: vi.fn(),
  useOptimizeHistory: vi.fn(),
  useUnifiedReviewStats: vi.fn(),
}));

vi.mock('../lib/api', () => ({
  useExperiments: apiMocks.useExperiments,
  useOptimizeHistory: apiMocks.useOptimizeHistory,
  useUnifiedReviewStats: apiMocks.useUnifiedReviewStats,
}));

vi.mock('./Experiments', () => ({
  Experiments: () => <div>Experiments Content</div>,
}));

vi.mock('./UnifiedReviewQueue', () => ({
  UnifiedReviewQueue: () => <div>Review Content</div>,
}));

vi.mock('./Opportunities', () => ({
  Opportunities: () => <div>Opportunities Content</div>,
}));

function renderImprovements(initialEntry = '/improvements') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Improvements />
    </MemoryRouter>
  );
}

describe('Improvements', () => {
  beforeEach(() => {
    apiMocks.useExperiments.mockReturnValue({
      data: [],
      isLoading: false,
      isError: false,
    });
    apiMocks.useOptimizeHistory.mockReturnValue({
      data: [],
      isLoading: false,
      isError: false,
    });
    apiMocks.useUnifiedReviewStats.mockReturnValue({
      data: undefined,
    });
  });

  it('renders the unified improvement workflow tabs', async () => {
    const user = userEvent.setup();

    renderImprovements();

    expect(screen.getByRole('heading', { name: 'Improvements' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Opportunities' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Experiments' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Review' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'History' })).toBeInTheDocument();
    expect(screen.getByText('Opportunities Content')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Experiments' }));
    expect(await screen.findByText('Experiments Content')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Review' }));
    expect(await screen.findByText('Review Content')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'History' }));
    expect((await screen.findAllByText('No data yet')).length).toBeGreaterThan(0);
    expect(
      screen.getByText('Expected: decisions appear after proposals are accepted or rejected.')
    ).toBeInTheDocument();
    expect(
      screen.getByText('Next: review pending improvements or run Optimize to create a proposal.')
    ).toBeInTheDocument();
  });

  it('supports deep-linking directly to a workflow tab', () => {
    renderImprovements('/improvements?tab=review');

    expect(screen.getByText('Review Content')).toBeInTheDocument();
  });

  it('frames the history tab as durable past state', () => {
    renderImprovements('/improvements?tab=history');

    expect(screen.getByText('Durable decision history')).toBeInTheDocument();
    expect(
      screen.getByText('Accepted and rejected improvements remain available here after restart.')
    ).toBeInTheDocument();
  });

  it('renders journey navigation links to Optimize and Deploy', () => {
    renderImprovements();

    const optimizeLink = screen.getByRole('link', { name: 'Back to Optimize' });
    expect(optimizeLink).toBeInTheDocument();
    expect(optimizeLink).toHaveAttribute('href', '/optimize');

    const deployLink = screen.getByRole('link', { name: /Deploy/ });
    expect(deployLink).toBeInTheDocument();
    expect(deployLink).toHaveAttribute('href', '/deploy');
  });

  it('guides operators to review proposals when the review queue has pending work', () => {
    apiMocks.useUnifiedReviewStats.mockReturnValue({
      data: {
        total_pending: 2,
        total_approved: 0,
      },
    });

    renderImprovements('/improvements?tab=review');

    const journey = screen.getByRole('region', { name: 'Operator journey' });
    expect(within(journey).getByText('Current step: Review')).toBeInTheDocument();
    expect(within(journey).getByText('Next: review proposals')).toBeInTheDocument();
    expect(within(journey).getByRole('link', { name: 'Review proposals' })).toHaveAttribute(
      'href',
      '/improvements?tab=review'
    );
  });

  it('guides operators to deploy after improvements are approved', () => {
    apiMocks.useUnifiedReviewStats.mockReturnValue({
      data: {
        total_pending: 0,
        total_approved: 1,
      },
    });

    renderImprovements();

    const journey = screen.getByRole('region', { name: 'Operator journey' });
    expect(within(journey).getByText('Current step: Review')).toBeInTheDocument();
    expect(within(journey).getByText('Next: deploy approved improvements')).toBeInTheDocument();
    expect(within(journey).getByRole('link', { name: 'Deploy approved improvements' })).toHaveAttribute(
      'href',
      '/deploy'
    );
  });
});
