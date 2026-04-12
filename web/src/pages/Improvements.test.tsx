import { describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Improvements } from './Improvements';

vi.mock('../lib/api', () => ({
  useExperiments: () => ({
    data: [],
    isLoading: false,
    isError: false,
  }),
  useOptimizeHistory: () => ({
    data: [],
    isLoading: false,
    isError: false,
  }),
  useUnifiedReviewStats: () => ({
    data: undefined,
  }),
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
    expect(await screen.findByText('No completed improvements yet.')).toBeInTheDocument();
  });

  it('supports deep-linking directly to a workflow tab', () => {
    renderImprovements('/improvements?tab=review');

    expect(screen.getByText('Review Content')).toBeInTheDocument();
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
});
