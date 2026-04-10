import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ToastViewport } from '../components/ToastViewport';
import { AGENT_IMPROVER_STORAGE_KEY } from '../lib/agent-improver';
import { AgentImprover } from './AgentImprover';

function EvalRouteProbe() {
  const location = useLocation();
  const state = (location.state ?? {}) as Record<string, unknown>;

  return (
    <div>
      <p>Eval route reached</p>
      <p data-testid="eval-search">{location.search}</p>
      <p data-testid="eval-open">{String(state.open ?? '')}</p>
      <p data-testid="eval-source">{String(state.source ?? '')}</p>
      <p data-testid="eval-draft-count">{String(state.draftEvalCount ?? '')}</p>
    </div>
  );
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
      <MemoryRouter initialEntries={['/agent-improver']}>
        <Routes>
          <Route path="/agent-improver" element={<AgentImprover />} />
          <Route path="/evals" element={<EvalRouteProbe />} />
        </Routes>
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

function mockBuilderSessionWithRateLimit() {
  return {
    ...mockBuilderSession(),
    mock_mode: true,
    mock_reason: 'HTTP Error 429: Too Many Requests',
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

  // --- Core rendering and interaction tests ---

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

    expect(screen.getByText(/Improve the escalation path/)).toBeInTheDocument();
    expect(screen.getByText(/Tighten the refund workflow/)).toBeInTheDocument();
    expect(screen.getByText(/Add calmer tone guidance/)).toBeInTheDocument();
    expect(screen.getByText(/Strengthen the safety policy/)).toBeInTheDocument();
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

  // --- Checkpoint persistence and recovery tests (from Codex) ---

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
  });

  // --- Accessibility tests (from Claude) ---

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

  it('shows conversation area with log role for screen readers', () => {
    renderPage();

    expect(screen.getByRole('log', { name: 'Conversation history' })).toBeInTheDocument();
  });

  // --- First-run vs active copy tests (from Claude) ---

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

  it('shows clearer copy for first-run state vs active session state', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(mockBuilderSession())));

    renderPage();

    expect(screen.getByText('Start with an improvement')).toBeInTheDocument();
    expect(screen.getByText('Waiting for first draft')).toBeInTheDocument();

    await user.type(
      screen.getByPlaceholderText('Describe how the draft should improve next...'),
      'Test'
    );
    await user.click(screen.getByRole('button', { name: 'Send request' }));

    await screen.findByText('Escalation Concierge');

    expect(screen.getByText('Refine your agent')).toBeInTheDocument();
    expect(screen.getByText('Review and validate')).toBeInTheDocument();
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

  // --- 429 / Rate-limit UX tests ---

  it('shows "Rate limited session" badge when session has a 429 mock_reason', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(mockBuilderSessionWithRateLimit())));

    renderPage();

    await user.type(
      screen.getByPlaceholderText('Describe how the draft should improve next...'),
      'Improve escalation.'
    );
    await user.click(screen.getByRole('button', { name: 'Send request' }));

    expect(await screen.findByText('Rate limited session')).toBeInTheDocument();
  });

  it('shows rate-limit fallback notice with actionable guidance for 429 errors', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(mockBuilderSessionWithRateLimit())));

    renderPage();

    await user.type(
      screen.getByPlaceholderText('Describe how the draft should improve next...'),
      'Improve escalation.'
    );
    await user.click(screen.getByRole('button', { name: 'Send request' }));

    const notice = await screen.findByTestId('fallback-notice');
    expect(notice).toBeInTheDocument();
    expect(within(notice).getByText(/rate-limiting/i)).toBeInTheDocument();
    expect(within(notice).getAllByText(/retry/i).length).toBeGreaterThanOrEqual(1);
  });

  it('shows a "Retry last request" button in rate-limit fallback notice', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(mockBuilderSessionWithRateLimit())));

    renderPage();

    await user.type(
      screen.getByPlaceholderText('Describe how the draft should improve next...'),
      'Improve escalation.'
    );
    await user.click(screen.getByRole('button', { name: 'Send request' }));

    expect(await screen.findByRole('button', { name: 'Retry last request' })).toBeInTheDocument();
  });

  it('retries the last rate-limited request against the live builder session', async () => {
    const user = userEvent.setup();
    const retrySession = mockBuilderSession({
      updated_at: 1234567891,
      mock_mode: false,
      config: {
        ...mockBuilderSession().config,
        agent_name: 'Escalation Concierge Live',
      },
    });
    const fetchMock = vi.fn(async (...args: [RequestInfo | URL, RequestInit?]) => {
      const [input] = args;
      if (String(input) === '/api/builder/chat') {
        const callCount = fetchMock.mock.calls.filter(([url]) => String(url) === '/api/builder/chat').length;
        return jsonResponse(callCount === 1 ? mockBuilderSessionWithRateLimit() : retrySession);
      }
      return jsonResponse({});
    });
    vi.stubGlobal('fetch', fetchMock);

    renderPage();

    await user.type(
      screen.getByPlaceholderText('Describe how the draft should improve next...'),
      'Improve escalation.'
    );
    await user.click(screen.getByRole('button', { name: 'Send request' }));
    expect(await screen.findByRole('button', { name: 'Retry last request' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Retry last request' }));

    expect(await screen.findByText('Escalation Concierge Live')).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const retryBody = JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body));
    expect(retryBody).toEqual({
      message: 'Improve the handoff logic for escalations.',
      session_id: 'builder-session-123',
    });
  });

  it('shows rate-limit-specific footer notice instead of raw error text', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(mockBuilderSessionWithRateLimit())));

    renderPage();

    await user.type(
      screen.getByPlaceholderText('Describe how the draft should improve next...'),
      'Improve escalation.'
    );
    await user.click(screen.getByRole('button', { name: 'Send request' }));

    await screen.findByText('Escalation Concierge');
    expect(screen.getByText('Provider rate limited')).toBeInTheDocument();
    expect(screen.getAllByText(/fallback data/i).length).toBeGreaterThanOrEqual(1);
  });

  it('can ask the improver to generate an eval plan for the current draft', async () => {
    const user = userEvent.setup();
    const draftWithoutEvals = mockBuilderSession({ evals: null });
    const draftWithEvals = mockBuilderSession({
      updated_at: 1234567891,
      evals: {
        case_count: 2,
        scenarios: [
          {
            name: 'Escalation context',
            description: 'Verify human handoff includes recent customer actions.',
          },
          {
            name: 'Policy guardrail',
            description: 'Verify account changes are refused before verification.',
          },
        ],
      },
    });
    const fetchMock = vi.fn(async (...args: [RequestInfo | URL, RequestInit?]) => {
      const [input] = args;
      if (String(input) === '/api/builder/chat') {
        const callCount = fetchMock.mock.calls.filter(([url]) => String(url) === '/api/builder/chat').length;
        return jsonResponse(callCount === 1 ? draftWithoutEvals : draftWithEvals);
      }
      return jsonResponse({});
    });
    vi.stubGlobal('fetch', fetchMock);

    renderPage();

    await user.type(
      screen.getByPlaceholderText('Describe how the draft should improve next...'),
      'Improve escalation.'
    );
    await user.click(screen.getByRole('button', { name: 'Send request' }));
    await screen.findByText('Escalation Concierge');

    await user.click(screen.getByRole('button', { name: 'Generate eval plan' }));

    expect(await screen.findByText('Escalation context')).toBeInTheDocument();
    expect(screen.getByText(/Verify human handoff includes recent customer actions/)).toBeInTheDocument();
    const evalRequestBody = JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body));
    expect(evalRequestBody.session_id).toBe('builder-session-123');
    expect(evalRequestBody.message).toMatch(/generate evals/i);
  });

  it('shows "Rate limited" in summary pill for 429 sessions', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(mockBuilderSessionWithRateLimit())));

    renderPage();

    await user.type(
      screen.getByPlaceholderText('Describe how the draft should improve next...'),
      'Improve escalation.'
    );
    await user.click(screen.getByRole('button', { name: 'Send request' }));

    await screen.findByText('Escalation Concierge');
    expect(screen.getByText('Rate limited')).toBeInTheDocument();
  });

  it('saves and carries drafts with eval plans into the eval generator', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/builder/chat') {
        return jsonResponse(mockBuilderSession());
      }
      if (url === '/api/agents') {
        return jsonResponse({
          agent: {
            id: 'agent-v002',
            config_version: 2,
            name: 'Escalation Concierge',
            model: 'gpt-5.4-mini',
            created_at: '2026-04-10T12:00:00.000Z',
            source: 'built',
            config_path: '/workspace/configs/v002.yaml',
            status: 'candidate',
            config: mockBuilderSession().config,
          },
          save_result: {
            artifact_id: 'artifact-123',
            config_path: '/workspace/configs/v002.yaml',
            config_version: 2,
            eval_cases_path: '/workspace/evals/generated_build.yaml',
            runtime_config_path: '/workspace/agentlab.yaml',
            workspace_path: '/workspace',
            actual_config_yaml: 'agent_name: Escalation Concierge',
          },
        });
      }
      return jsonResponse({});
    });
    vi.stubGlobal('fetch', fetchMock);

    renderPage();

    await user.type(
      screen.getByPlaceholderText('Describe how the draft should improve next...'),
      'Improve escalation.'
    );
    await user.click(screen.getByRole('button', { name: 'Send request' }));
    await screen.findByText('Escalation Concierge');

    await user.click(screen.getByRole('button', { name: 'Save and open Eval Generator' }));

    expect(await screen.findByText('Eval route reached')).toBeInTheDocument();
    expect(screen.getByTestId('eval-search')).toHaveTextContent('agent=agent-v002');
    expect(screen.getByTestId('eval-search')).toHaveTextContent('generator=1');
    expect(screen.getByTestId('eval-open')).toHaveTextContent('generate');
    expect(screen.getByTestId('eval-source')).toHaveTextContent('agent-improver');
    expect(screen.getByTestId('eval-draft-count')).toHaveTextContent('3');
  });

  it('shows generic fallback badge for non-429 mock reasons', async () => {
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

  // --- New session / reset dialog tests (from Claude) ---

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

  // --- Dismissible error tests (from Claude) ---

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

    expect(await screen.findByText('Something went wrong')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Dismiss error' }));

    await waitFor(() => {
      expect(screen.queryByText('Something went wrong')).not.toBeInTheDocument();
    });
  });
});
