import { describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Optimize } from './Optimize';

vi.mock('../lib/api', () => ({
  useOptimizeHistory: () => ({
    data: [],
    isLoading: false,
    refetch: vi.fn(),
  }),
  useStartOptimize: () => ({
    mutate: vi.fn(),
    isPending: false,
  }),
  useTaskStatus: () => ({
    data: null,
  }),
}));

vi.mock('../lib/websocket', () => ({
  wsClient: {
    connect: vi.fn(),
    onMessage: vi.fn(() => vi.fn()),
  },
}));

vi.mock('./LiveOptimize', () => ({
  LiveOptimize: () => <div>Live Optimize Content</div>,
}));

vi.mock('./Experiments', () => ({
  Experiments: () => <div>Experiments Content</div>,
}));

vi.mock('./ChangeReview', () => ({
  ChangeReview: () => <div>Change Review Content</div>,
}));

vi.mock('./Opportunities', () => ({
  Opportunities: () => <div>Opportunities Content</div>,
}));

function renderOptimize() {
  return render(
    <MemoryRouter initialEntries={['/optimize']}>
      <Optimize />
    </MemoryRouter>
  );
}

describe('Optimize', () => {
  it('renders a tabbed hub and switches between embedded optimize views', async () => {
    const user = userEvent.setup();

    renderOptimize();

    expect(screen.getByRole('button', { name: 'Run' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Live' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Experiments' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Review' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Opportunities' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Start Optimization' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Live' }));
    expect(await screen.findByText('Live Optimize Content')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Experiments' }));
    expect(await screen.findByText('Experiments Content')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Review' }));
    expect(await screen.findByText('Change Review Content')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Opportunities' }));
    expect(await screen.findByText('Opportunities Content')).toBeInTheDocument();
  });
});
