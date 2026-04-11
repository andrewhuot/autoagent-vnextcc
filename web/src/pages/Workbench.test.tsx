import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Workbench } from './Workbench';

function renderWorkbench() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/workbench']}>
        <Workbench />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('Workbench page', () => {
  beforeEach(() => {
    // Mock fetch so the queries resolve to empty data instead of hanging
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => [],
        text: async () => '[]',
      })
    );
    // Reset zustand persisted store between tests
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders the workbench shell with conversation, composer, and inspector', () => {
    renderWorkbench();

    // Composer textarea is present
    const composer = screen.getByPlaceholderText(/Ask for a plan/i);
    expect(composer).toBeInTheDocument();
  });

  it('renders all 11 inspector tabs', () => {
    renderWorkbench();

    const expectedTabs = [
      'Preview',
      'Agent Card',
      'Source Code',
      'Tools',
      'Callbacks',
      'Guardrails',
      'Evals',
      'Trace',
      'Test Live',
      'Deploy',
      'Activity',
    ];

    for (const label of expectedTabs) {
      expect(
        screen.getByRole('button', { name: new RegExp(`^${label}$`, 'i') })
      ).toBeInTheDocument();
    }
  });
});
