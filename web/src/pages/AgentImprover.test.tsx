import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ToastViewport } from '../components/ToastViewport';
import { AGENT_IMPROVER_STORAGE_KEY } from '../lib/agent-improver';
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

function createStorageMock() {
  const store = new Map<string, string>();

  return {
    getItem: vi.fn((key: string) => store.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => {
      store.set(key, value);
    }),
    removeItem: vi.fn((key: string) => {
      store.delete(key);
    }),
    clear: vi.fn(() => {
      store.clear();
    }),
    key: vi.fn(),
    get length() {
      return store.size;
    },
  };
}

function mockBuilderSession(overrides: Record<string, unknown> = {}) {
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
    ...overrides,
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
  let localStorageMock: ReturnType<typeof createStorageMock>;

  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
    localStorageMock = createStorageMock();
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: localStorageMock,
    });
    Object.defineProperty(window, 'sessionStorage', {
      configurable: true,
      value: createStorageMock(),
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

  it('restores a locally persisted draft when the live session is no longer available', async () => {
    const persistedSession = mockBuilderSession({
      session_id: 'restored-session',
      updated_at: 200,
    });

    localStorageMock.setItem(
      AGENT_IMPROVER_STORAGE_KEY,
      JSON.stringify({
        version: 2,
        liveSessionId: 'restored-session',
        checkpoints: [
          {
            id: 'restored-session:200',
            createdAt: 200,
            latestUserRequest: 'Improve the handoff logic for escalations.',
            session: persistedSession,
          },
        ],
        activeCheckpointIndex: 0,
        previewMessage: 'A customer needs a human after two failed refund attempts.',
        saveResult: null,
        savedAgent: null,
      })
    );

    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input) === '/api/builder/session/restored-session') {
          return jsonResponse({ detail: 'Builder session not found' }, { status: 404 });
        }
        return jsonResponse({});
      })
    );

    renderPage();

    expect(await screen.findByText('Recovered local draft')).toBeInTheDocument();
    expect(screen.getAllByText('Improve the handoff logic for escalations.').length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: 'Start new draft' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save to workspace' })).toBeDisabled();
  });

  it('supports undo and redo across locally stored draft checkpoints', async () => {
    const user = userEvent.setup();
    const firstSession = mockBuilderSession();
    const secondSession = mockBuilderSession({
      updated_at: 1234567891,
      config: {
        ...mockBuilderSession().config,
        agent_name: 'Escalation Concierge v2',
      },
    });
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === '/api/builder/chat') {
        const callCount = fetchMock.mock.calls.filter(([url]) => String(url) === '/api/builder/chat').length;
        return jsonResponse(callCount === 1 ? firstSession : secondSession);
      }
      return jsonResponse({});
    });
    vi.stubGlobal('fetch', fetchMock);

    renderPage();

    const composer = screen.getByPlaceholderText('Describe how the draft should improve next...');

    await user.type(composer, 'Improve the handoff logic for escalations.');
    await user.click(screen.getByRole('button', { name: 'Send request' }));
    await screen.findByText('Escalation Concierge');

    await user.type(composer, 'Add calmer tone guidance for high-friction conversations.');
    await user.click(screen.getByRole('button', { name: 'Send request' }));
    await screen.findByText('Escalation Concierge v2');

    await user.click(screen.getByRole('button', { name: 'Undo checkpoint' }));
    expect(screen.getByText('Viewing checkpoint 1 of 2')).toBeInTheDocument();
    expect(screen.getByText('Escalation Concierge')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save to workspace' })).toBeDisabled();

    await user.click(screen.getByRole('button', { name: 'Redo checkpoint' }));
    expect(screen.getByText('Escalation Concierge v2')).toBeInTheDocument();
  });

  it('surfaces save failures with actionable messaging from the API response', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/builder/chat') {
        return jsonResponse(mockBuilderSession());
      }
      if (url === '/api/agents') {
        return jsonResponse({ detail: 'Workspace save failed: config directory is read-only.' }, { status: 500 });
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

    await user.click(screen.getByRole('button', { name: 'Save to workspace' }));

    expect(
      (await screen.findAllByText('Workspace save failed: config directory is read-only.')).length
    ).toBeGreaterThan(0);
    expect(screen.getByText('Try saving again, or start a new draft if the live session has expired.')).toBeInTheDocument();
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
});
