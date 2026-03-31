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

function renderOptimize() {
  return render(
    <MemoryRouter initialEntries={['/optimize']}>
      <Optimize />
    </MemoryRouter>
  );
}

describe('Optimize', () => {
  it('focuses the optimize page on running cycles and links to the unified improvements workflow', async () => {
    const user = userEvent.setup();

    renderOptimize();

    expect(screen.getByRole('button', { name: 'Run' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Live' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Experiments' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open Improvements' })).toHaveAttribute(
      'href',
      '/improvements'
    );
    expect(screen.getByRole('button', { name: 'Start Optimization' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Live' }));
    expect(await screen.findByText('Live Optimize Content')).toBeInTheDocument();
  });
});
