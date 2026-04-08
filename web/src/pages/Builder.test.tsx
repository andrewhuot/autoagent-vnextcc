import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Builder } from './Builder';

function buildSessionPayload(overrides: Record<string, unknown> = {}) {
  return {
    session_id: 'session-123',
    mock_mode: true,
    mock_reason: 'No configured builder LLM router is available.',
    messages: [
      {
        message_id: 'assistant-intro',
        role: 'assistant',
        content: 'Describe the agent you want to build.',
        created_at: 1,
      },
      {
        message_id: 'user-1',
        role: 'user',
        content: 'Build me an airline support agent',
        created_at: 2,
      },
      {
        message_id: 'assistant-1',
        role: 'assistant',
        content: 'I drafted `Airline Customer Support Agent` with routing for cancellations and flight status.',
        created_at: 3,
      },
    ],
    config: {
      agent_name: 'Airline Customer Support Agent',
      model: 'gpt-4o',
      system_prompt: 'You are an airline support agent.',
      tools: [
        {
          name: 'flight_status_lookup',
          description: 'Fetch flight status.',
          when_to_use: 'Use when a traveler asks for flight status.',
        },
      ],
      routing_rules: [
        {
          name: 'cancellations',
          intent: 'cancellation',
          description: 'Handle cancellations.',
        },
        {
          name: 'flight_status',
          intent: 'flight_status',
          description: 'Handle flight status requests.',
        },
      ],
      policies: [
        {
          name: 'no_internal_codes',
          description: 'Never reveal internal codes.',
        },
      ],
      eval_criteria: [
        {
          name: 'correct_routing',
          description: 'Route to the correct workflow.',
        },
      ],
      metadata: {},
    },
    stats: {
      tool_count: 1,
      policy_count: 1,
      routing_rule_count: 2,
    },
    evals: null,
    updated_at: 3,
    ...overrides,
  };
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/build']}>
        <Builder />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('Builder', () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal('fetch', fetchMock);
    vi.stubGlobal(
      'URL',
      Object.assign(globalThis.URL ?? {}, {
        createObjectURL: vi.fn(() => 'blob:builder-config'),
        revokeObjectURL: vi.fn(),
      })
    );
  });

  it('renders the builder-chat workspace layout', () => {
    renderPage();

    expect(screen.getByRole('heading', { name: 'Builder' })).toBeInTheDocument();
    expect(screen.getByText('Describe the agent you want to build')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Test Agent' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'View Config' })).toBeInTheDocument();
  });

  it('sends a prompt and updates the chat and preview', async () => {
    const user = userEvent.setup();
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => buildSessionPayload(),
    });

    renderPage();

    await user.type(
      screen.getByPlaceholderText('Describe the agent you want to build...'),
      'Build me an airline support agent'
    );
    await user.click(screen.getByRole('button', { name: 'Send' }));

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/builder/chat',
      expect.objectContaining({ method: 'POST' })
    );

    expect((await screen.findAllByText(/Airline Customer Support Agent/i)).length).toBeGreaterThan(0);
    expect(screen.getByText('1 tools')).toBeInTheDocument();
    expect(screen.getByText('1 policies')).toBeInTheDocument();
    expect(screen.getByText('2 routes')).toBeInTheDocument();
  });

  it('saves the current draft before continuing to eval', async () => {
    const user = userEvent.setup();
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => buildSessionPayload(),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          agent: {
            id: 'agent-v002',
            name: 'Airline Customer Support Agent',
            model: 'gpt-4o',
            created_at: '2026-04-01T12:00:00.000Z',
            source: 'built',
            config_path: '/workspace/agents/airline.yaml',
            status: 'ready',
            config: buildSessionPayload().config,
          },
          save_result: {
            artifact_id: 'artifact-123',
            config_path: '/workspace/agents/airline.yaml',
            config_version: 2,
            eval_cases_path: '/workspace/evals/airline.yaml',
            runtime_config_path: '/workspace/runtime/airline.yaml',
            workspace_path: '/workspace',
            actual_config_yaml: 'agent_name: Airline Customer Support Agent',
          },
        }),
      });

    renderPage();

    await user.type(
      screen.getByPlaceholderText('Describe the agent you want to build...'),
      'Build me an airline support agent'
    );
    await user.click(screen.getByRole('button', { name: 'Send' }));
    expect((await screen.findAllByText(/Airline Customer Support Agent/i)).length).toBeGreaterThan(0);

    await user.click(screen.getByRole('button', { name: 'Save & Run Eval' }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenLastCalledWith(
        '/api/agents',
        expect.objectContaining({ method: 'POST' })
      );
    });
  });

  it('exports the current config from the modal config view', async () => {
    const user = userEvent.setup();
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => buildSessionPayload(),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          filename: 'airline-customer-support-agent.yaml',
          content: 'agent_name: Airline Customer Support Agent',
          content_type: 'application/x-yaml',
        }),
      });

    renderPage();

    await user.type(
      screen.getByPlaceholderText('Describe the agent you want to build...'),
      'Build me an airline support agent'
    );
    await user.click(screen.getByRole('button', { name: 'Send' }));
    expect((await screen.findAllByText(/Airline Customer Support Agent/i)).length).toBeGreaterThan(0);

    await user.click(screen.getByRole('button', { name: 'View Config' }));
    const dialog = await screen.findByRole('dialog', { name: 'Agent Configuration' });
    await user.click(within(dialog).getByRole('button', { name: 'Download Draft' }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenLastCalledWith(
        '/api/builder/export',
        expect.objectContaining({ method: 'POST' })
      );
    });
  });
});
