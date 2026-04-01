import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { render, screen, waitFor } from '@testing-library/react';
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
  return render(
    <MemoryRouter initialEntries={['/build']}>
      <Builder />
    </MemoryRouter>
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

  it('renders the single-screen builder layout', () => {
    renderPage();

    expect(screen.getByRole('heading', { name: 'Builder' })).toBeInTheDocument();
    expect(screen.getByText('Describe the agent you want to build')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Live Config' })).toBeInTheDocument();
    expect(screen.getByText('Download Config')).toBeInTheDocument();
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

  it('runs eval generation from the preview action', async () => {
    const user = userEvent.setup();
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => buildSessionPayload(),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () =>
          buildSessionPayload({
            evals: {
              case_count: 4,
              scenarios: [
                { name: 'routing', description: 'Route correctly.' },
                { name: 'safety', description: 'Protect internal codes.' },
              ],
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

    await user.click(screen.getByRole('button', { name: 'Run Eval' }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenLastCalledWith(
        '/api/builder/chat',
        expect.objectContaining({ method: 'POST' })
      );
    });
    expect(await screen.findByText('4 draft evals')).toBeInTheDocument();
  });

  it('exports the current config from the preview action', async () => {
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

    await user.click(screen.getByRole('button', { name: 'Download Config' }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenLastCalledWith(
        '/api/builder/export',
        expect.objectContaining({ method: 'POST' })
      );
    });
  });
});
