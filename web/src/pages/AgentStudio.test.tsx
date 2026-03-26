import { describe, it, expect } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AgentStudio } from './AgentStudio';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
    },
  },
});

function renderWithProviders(component: React.ReactElement) {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{component}</MemoryRouter>
    </QueryClientProvider>
  );
}

describe('AgentStudio', () => {
  it('lets a user queue natural-language agent updates and see the draft preview', async () => {
    const user = userEvent.setup();

    renderWithProviders(<AgentStudio />);

    expect(screen.getByRole('heading', { name: 'Agent Studio' })).toBeInTheDocument();

    const input = screen.getByLabelText('Describe the agent update');

    await user.clear(input);
    await user.type(input, 'Add safety guardrails to prevent PII disclosure');
    await user.click(screen.getByRole('button', { name: 'Queue update' }));

    expect(await screen.findByText(/safety/i)).toBeInTheDocument();
    expect(screen.getByText('Queued changes')).toBeInTheDocument();
  });

  it('shows initial draft on mount', () => {
    renderWithProviders(<AgentStudio />);

    expect(screen.getByText('Queued changes')).toBeInTheDocument();
    expect(screen.getByText(/Invoice-first response guardrail/i)).toBeInTheDocument();
  });

  it('allows sample prompts to be clicked', async () => {
    const user = userEvent.setup();

    renderWithProviders(<AgentStudio />);

    const sampleButton = screen.getByRole('button', {
      name: /Add safety guardrails/i,
    });

    await user.click(sampleButton);

    const textarea = screen.getByLabelText('Describe the agent update') as HTMLTextAreaElement;
    expect(textarea.value).toContain('safety');
  });
});
