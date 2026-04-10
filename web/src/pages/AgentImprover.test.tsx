import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ToastViewport } from '../components/ToastViewport';
import { AgentImprover } from './AgentImprover';

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/agent-improver']}>
        <AgentImprover />
        <ToastViewport />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

function jsonResponse(body: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(body), {
    status: init?.status ?? 200,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  });
}

function mockBuilderSession() {
  return {
    session_id: 'builder-session-123',
    mock_mode: false,
    messages: [
      {
        message_id: 'builder-user-1',
        role: 'user' as const,
        content: 'Improve the handoff logic for escalations.',
        created_at: 1,
      },
      {
        message_id: 'builder-assistant-1',
        role: 'assistant' as const,
        content: 'I tightened the escalation path and added a trust-preserving escalation policy.',
        created_at: 2,
      },
    ],
    config: {
      agent_name: 'Escalation Concierge',
      model: 'gpt-5.4-mini',
      system_prompt: 'Help customers, escalate safely, and preserve context.',
      tools: [
        {
          name: 'ticket_lookup',
          description: 'Look up the current customer ticket.',
          when_to_use: 'Use when a customer references an existing support issue.',
        },
      ],
      routing_rules: [
        {
          name: 'escalation',
          intent: 'human_help',
          description: 'Escalate when a human review is required.',
        },
      ],
      policies: [
        {
          name: 'Context preservation',
          description: 'Pass the recent customer history into escalations.',
        },
      ],
      eval_criteria: [
        {
          name: 'Safe escalation',
          description: 'Escalations retain the correct context and policy guardrails.',
        },
      ],
      metadata: {
        tone: 'calm',
        owner: 'agent-improver',
      },
    },
    stats: {
      tool_count: 1,
      policy_count: 1,
      routing_rule_count: 1,
    },
    evals: {
      case_count: 3,
      scenarios: [
        {
          name: 'Escalation request',
          description: 'Customer explicitly asks for a human after a failed automated step.',
        },
      ],
    },
    updated_at: 1234567890,
  };
}

function mockBuilderSessionWithMockMode() {
  return {
    ...mockBuilderSession(),
    mock_mode: true,
    mock_reason: 'Backend unavailable',
  };
}

describe('AgentImprover', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
    Object.defineProperty(window, 'sessionStorage', {
      configurable: true,
      value: {
        getItem: vi.fn(() => null),
        setItem: vi.fn(),
        removeItem: vi.fn(),
      },
    });
  });

  it('renders the premium improver shell with synchronized workspace modes', () => {
    renderPage();

    expect(screen.getByRole('heading', { name: 'Agent Improver' })).toBeInTheDocument();
    expect(screen.getByText('Improvement workspace')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Summary' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: 'Config' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Preview' })).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Describe how the draft should improve next...')).toBeInTheDocument();
    expect(screen.getByText('No draft yet')).toBeInTheDocument();
  });

  it('shows improvement example buttons in initial state', () => {
    renderPage();

    expect(
      screen.getByText(/Improve the escalation path/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Tighten the refund workflow/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Add calmer tone guidance/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Strengthen the safety policy/),
    ).toBeInTheDocument();
  });

  it('shows empty state on the Summary tab before any conversation', () => {
    renderPage();

    expect(screen.getByText('No draft yet')).toBeInTheDocument();
  });

  it('shows step progression in initial Brief state', () => {
    renderPage();

    expect(screen.getByText('Brief')).toBeInTheDocument();
    expect(screen.getByText('Refine')).toBeInTheDocument();
    expect(screen.getAllByText('Inspect').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Validate')).toBeInTheDocument();
  });

  it('shows Fresh session badge before any request', () => {
    renderPage();

    expect(screen.getByText('Fresh session')).toBeInTheDocument();
  });

  it('submits an improvement request and updates the summary mode from the real builder session payload', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === '/api/builder/chat') {
        return jsonResponse(mockBuilderSession());
      }
      return jsonResponse({});
    });
    vi.stubGlobal('fetch', fetchMock);

    renderPage();

    await user.type(
      screen.getByPlaceholderText('Describe how the draft should improve next...'),
      'Improve the handoff logic for escalations.'
    );
    await user.click(screen.getByRole('button', { name: 'Send request' }));

    expect(await screen.findByText('Escalation Concierge')).toBeInTheDocument();
    expect(screen.getByText('gpt-5.4-mini')).toBeInTheDocument();
    expect(screen.getByText('1 tool')).toBeInTheDocument();
    expect(screen.getByText('3 draft evals')).toBeInTheDocument();
    expect(screen.getByText(/tightened the escalation path/i)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/builder/chat',
      expect.objectContaining({
        method: 'POST',
      })
    );
  });

  it('sends a message via the composer with Enter key', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === '/api/builder/chat') {
        return jsonResponse(mockBuilderSession());
      }
      return jsonResponse({});
    });
    vi.stubGlobal('fetch', fetchMock);

    renderPage();

    const textarea = screen.getByPlaceholderText('Describe how the draft should improve next...');
    await user.type(textarea, 'Add a scheduling tool');
    await user.keyboard('{Enter}');

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/builder/chat',
      expect.objectContaining({
        method: 'POST',
      })
    );
  });

  it('shows Fallback session badge when session is in mock mode', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(mockBuilderSessionWithMockMode())));

    renderPage();

    await user.type(
      screen.getByPlaceholderText('Describe how the draft should improve next...'),
      'Improve escalation.'
    );
    await user.click(screen.getByRole('button', { name: 'Send request' }));

    expect(await screen.findByText('Fallback session')).toBeInTheDocument();
  });

  it('shows the synced raw config and behavior preview modes for the active draft', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/builder/chat') {
        return jsonResponse(mockBuilderSession());
      }
      if (url === '/api/builder/preview') {
        return jsonResponse({
          response: 'I can escalate this to a human and attach the last two customer actions for context.',
          tool_calls: [{ name: 'ticket_lookup' }],
          latency_ms: 812,
          token_count: 186,
          specialist_used: 'escalation',
          mock_mode: false,
          mock_reasons: [],
        });
      }
      return jsonResponse({});
    });
    vi.stubGlobal('fetch', fetchMock);

    renderPage();

    await user.type(
      screen.getByPlaceholderText('Describe how the draft should improve next...'),
      'Improve the handoff logic for escalations.'
    );
    await user.click(screen.getByRole('button', { name: 'Send request' }));

    await screen.findByText('Escalation Concierge');

    await user.click(screen.getByRole('tab', { name: 'Config' }));
    expect(screen.getByTestId('agent-improver-yaml-preview')).toHaveTextContent('agent_name: Escalation Concierge');
    expect(screen.getByRole('button', { name: 'Copy draft' })).toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: 'Preview' }));
    await user.clear(screen.getByLabelText('Preview message'));
    await user.type(
      screen.getByLabelText('Preview message'),
      'A customer wants a human after two failed refund attempts.'
    );
    await user.click(screen.getByRole('button', { name: 'Run preview' }));

    expect(await screen.findByText(/attach the last two customer actions/i)).toBeInTheDocument();
    expect(screen.getByText('Live preview')).toBeInTheDocument();
    expect(screen.getByText('Tool: ticket_lookup')).toBeInTheDocument();
  });

  // --- New tests for UX hardening ---

  it('has proper tablist and tabpanel ARIA roles', () => {
    renderPage();

    expect(screen.getByRole('tablist', { name: 'Inspector views' })).toBeInTheDocument();
    const summaryTab = screen.getByRole('tab', { name: 'Summary' });
    expect(summaryTab).toHaveAttribute('aria-controls', 'panel-summary');
    expect(screen.getByRole('tabpanel')).toHaveAttribute('id', 'panel-summary');
  });

  it('shows step progression with accessibility labels', () => {
    renderPage();

    const nav = screen.getByRole('navigation', { name: 'Improvement progress' });
    expect(nav).toBeInTheDocument();
    expect(within(nav).getByText('Brief').closest('span[aria-current="step"]')).toBeInTheDocument();
  });

  it('hides example buttons after a session is established', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(mockBuilderSession())));

    renderPage();

    expect(screen.getByText('Try an example')).toBeInTheDocument();

    await user.type(
      screen.getByPlaceholderText('Describe how the draft should improve next...'),
      'Test improvement'
    );
    await user.click(screen.getByRole('button', { name: 'Send request' }));

    await screen.findByText('Escalation Concierge');
    expect(screen.queryByText('Try an example')).not.toBeInTheDocument();
  });

  it('shows New session button after session is created', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(mockBuilderSession())));

    renderPage();

    expect(screen.queryByRole('button', { name: 'Start a new session' })).not.toBeInTheDocument();

    await user.type(
      screen.getByPlaceholderText('Describe how the draft should improve next...'),
      'Test improvement'
    );
    await user.click(screen.getByRole('button', { name: 'Send request' }));

    await screen.findByText('Escalation Concierge');
    expect(screen.getByRole('button', { name: 'Start a new session' })).toBeInTheDocument();
  });

  it('shows reset confirmation dialog when New session clicked with unsaved work', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(mockBuilderSession())));

    renderPage();

    await user.type(
      screen.getByPlaceholderText('Describe how the draft should improve next...'),
      'Test improvement'
    );
    await user.click(screen.getByRole('button', { name: 'Send request' }));

    await screen.findByText('Escalation Concierge');

    await user.click(screen.getByRole('button', { name: 'Start a new session' }));

    expect(screen.getByRole('dialog', { name: 'Confirm reset' })).toBeInTheDocument();
    expect(screen.getByText('Start over?')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Keep working' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Discard and reset' })).toBeInTheDocument();
  });

  it('dismisses reset dialog when Keep working is clicked', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(mockBuilderSession())));

    renderPage();

    await user.type(
      screen.getByPlaceholderText('Describe how the draft should improve next...'),
      'Test'
    );
    await user.click(screen.getByRole('button', { name: 'Send request' }));
    await screen.findByText('Escalation Concierge');

    await user.click(screen.getByRole('button', { name: 'Start a new session' }));
    await user.click(screen.getByRole('button', { name: 'Keep working' }));

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByText('Escalation Concierge')).toBeInTheDocument();
  });

  it('resets session when Discard and reset is clicked', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(mockBuilderSession())));

    renderPage();

    await user.type(
      screen.getByPlaceholderText('Describe how the draft should improve next...'),
      'Test'
    );
    await user.click(screen.getByRole('button', { name: 'Send request' }));
    await screen.findByText('Escalation Concierge');

    await user.click(screen.getByRole('button', { name: 'Start a new session' }));
    await user.click(screen.getByRole('button', { name: 'Discard and reset' }));

    expect(screen.queryByText('Escalation Concierge')).not.toBeInTheDocument();
    expect(screen.getByText('Fresh session')).toBeInTheDocument();
    expect(screen.getByText('No draft yet')).toBeInTheDocument();
  });

  it('allows dismissing error messages', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === '/api/builder/chat') {
        return new Response('Service unavailable', { status: 503 });
      }
      return jsonResponse({});
    });
    vi.stubGlobal('fetch', fetchMock);

    renderPage();

    const textarea = screen.getByPlaceholderText('Describe how the draft should improve next...');
    await user.type(textarea, 'Test');
    await user.click(screen.getByRole('button', { name: 'Send request' }));

    // Wait for the async error to propagate and find by text instead
    expect(await screen.findByText('Something went wrong')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Dismiss error' }));

    await waitFor(() => {
      expect(screen.queryByText('Something went wrong')).not.toBeInTheDocument();
    });
  });

  it('labels user messages as "You" instead of "Request"', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(mockBuilderSession())));

    renderPage();

    await user.type(
      screen.getByPlaceholderText('Describe how the draft should improve next...'),
      'Test'
    );
    await user.click(screen.getByRole('button', { name: 'Send request' }));

    await screen.findByText('Escalation Concierge');
    expect(screen.getByText('You')).toBeInTheDocument();
  });

  it('shows keyboard shortcut hints in the composer', () => {
    renderPage();

    expect(screen.getByText(/Press Enter to send/)).toBeInTheDocument();
  });

  it('shows conversation area with log role for screen readers', () => {
    renderPage();

    expect(screen.getByRole('log', { name: 'Conversation history' })).toBeInTheDocument();
  });

  it('shows clearer copy for first-run state vs active session state', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(mockBuilderSession())));

    renderPage();

    // First-run copy
    expect(screen.getByText('Start with an improvement')).toBeInTheDocument();
    expect(screen.getByText('Waiting for first draft')).toBeInTheDocument();

    await user.type(
      screen.getByPlaceholderText('Describe how the draft should improve next...'),
      'Test'
    );
    await user.click(screen.getByRole('button', { name: 'Send request' }));

    await screen.findByText('Escalation Concierge');

    // Active session copy
    expect(screen.getByText('Refine your agent')).toBeInTheDocument();
    expect(screen.getByText('Review and validate')).toBeInTheDocument();
  });
});
