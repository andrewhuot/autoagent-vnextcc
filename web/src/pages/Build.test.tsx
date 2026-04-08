import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ToastViewport } from '../components/ToastViewport';
import { Build } from './Build';

function renderPage(initialEntry = '/build') {
  return renderJourney(initialEntry, <Build />);
}

function renderJourney(initialEntry = '/build', element = <Build />) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path="/build" element={element} />
          <Route path="/evals" element={<div>Eval Page</div>} />
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

function mockBuilderSession() {
  return {
    session_id: 'builder-session-123',
    mock_mode: false,
    messages: [
      {
        message_id: 'builder-user-1',
        role: 'user' as const,
        content: 'Build a refund agent',
        created_at: 1,
      },
      {
        message_id: 'builder-assistant-1',
        role: 'assistant' as const,
        content: 'I drafted a refund-focused agent with triage and escalation rules.',
        created_at: 2,
      },
    ],
    config: {
      agent_name: 'Refund Rescue',
      model: 'gpt-5.4-mini',
      system_prompt: 'Help customers with refunds, replacements, and escalation.',
      tools: [
        {
          name: 'refund_lookup',
          description: 'Look up order refund eligibility.',
          when_to_use: 'Use when a customer asks about a refund.',
        },
      ],
      routing_rules: [
        {
          name: 'refund_request',
          intent: 'refund',
          description: 'Route refund questions to the refund specialist.',
        },
      ],
      policies: [
        {
          name: 'No PII leakage',
          description: 'Never expose another customer’s information.',
        },
      ],
      eval_criteria: [
        {
          name: 'Correct routing',
          description: 'Refund questions route to the correct specialist.',
        },
      ],
      metadata: {
        tone: 'calm',
      },
    },
    stats: {
      tool_count: 1,
      policy_count: 1,
      routing_rule_count: 1,
    },
    evals: {
      case_count: 2,
      scenarios: [
        {
          name: 'Standard refund',
          description: 'Customer asks for a straightforward refund.',
        },
      ],
    },
    updated_at: 1234567890,
  };
}

function mockGeneratedConfig() {
  return {
    model: 'gpt-5.4',
    system_prompt: 'Resolve support issues safely and escalate when needed.',
    tools: [
      {
        name: 'order_lookup',
        description: 'Look up orders by order ID.',
        parameters: ['order_id'],
      },
    ],
    routing_rules: [
      {
        condition: 'refund_request',
        action: 'route_to_refunds',
        priority: 10,
      },
    ],
    policies: [
      {
        name: 'Protect customer data',
        description: 'Do not reveal customer data without verification.',
        enforcement: 'strict' as const,
      },
    ],
    eval_criteria: [
      {
        name: 'Safe escalation',
        weight: 0.5,
        description: 'Escalates when the request requires a human.',
      },
    ],
    metadata: {
      agent_name: 'Order Guardian',
      version: 'v1',
      created_from: 'prompt' as const,
    },
  };
}

describe('Build', () => {
  beforeEach(() => {
    const storage = new Map<string, string>();
    const localStorageMock = {
      getItem: vi.fn((key: string) => storage.get(key) ?? null),
      setItem: vi.fn((key: string, value: string) => {
        storage.set(key, value);
      }),
      removeItem: vi.fn((key: string) => {
        storage.delete(key);
      }),
      clear: vi.fn(() => {
        storage.clear();
      }),
    };

    vi.stubGlobal('fetch', vi.fn());
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: localStorageMock,
    });
  });

  it('shows the unified tab shell and defaults to the prompt workspace', () => {
    renderPage();

    expect(screen.getByRole('heading', { name: 'Build' })).toBeInTheDocument();
    expect(screen.getByText('Choose the workspace that fits this demo.')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Prompt' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: 'Transcript' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Builder Chat' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Saved Artifacts' })).toBeInTheDocument();
    expect(screen.getByLabelText('Agent description')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'XML Instruction Studio' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Form View' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByLabelText('Instruction role')).toBeInTheDocument();
    expect(screen.getByLabelText('Primary goal')).toBeInTheDocument();
  });

  it('switches to the builder chat workspace without losing the builder controls', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole('tab', { name: 'Builder Chat' }));

    expect(screen.getByRole('heading', { name: 'Builder' })).toBeInTheDocument();
    expect(
      screen.getByText(
        /describe the agent you want to build, preview the runtime behavior, and carry the saved draft straight into evals/i
      )
    ).toBeInTheDocument();
    expect(screen.getByText('Conversational Builder')).toBeInTheDocument();
    expect(screen.getByText('How this builder demo works')).toBeInTheDocument();
    expect(screen.getByTestId('builder-composer')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Test Agent' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'View Config' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save & Run Eval' })).toBeInTheDocument();
  });

  it('moves builder config into a modal and makes testing the main right-panel workflow', async () => {
    const user = userEvent.setup();
    const builderSession = mockBuilderSession();
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === '/api/builder/chat') {
          return jsonResponse(builderSession);
        }
        return jsonResponse({});
      })
    );

    renderPage();

    await user.click(screen.getByRole('tab', { name: 'Builder Chat' }));
    await user.clear(screen.getByTestId('builder-composer'));
    await user.type(screen.getByTestId('builder-composer'), 'Build a refund agent');
    await user.click(screen.getByTestId('builder-send'));

    expect(await screen.findByRole('heading', { name: 'Test Agent' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Live Config' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'View Config' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save to Workspace' })).toBeInTheDocument();
    expect(
      screen.getByText('Next: save this draft, then open Eval Runs with the same config preselected.')
    ).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'View Config' }));

    const dialog = await screen.findByRole('dialog', { name: 'Agent Configuration' });
    expect(within(dialog).getByRole('button', { name: 'Copy YAML' })).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Download Draft' })).toBeInTheDocument();
    expect(within(dialog).getByTestId('yaml-preview')).toBeInTheDocument();

    await user.click(within(dialog).getByRole('button', { name: 'JSON' }));
    expect(within(dialog).getByTestId('builder-config-preview')).toBeInTheDocument();

    await user.click(within(dialog).getByRole('button', { name: 'Close configuration modal' }));
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: 'Agent Configuration' })).not.toBeInTheDocument();
    });
  });

  it('opens a deep-linked build tab from the route query string with intelligence framing', () => {
    renderPage('/build?tab=transcript');

    expect(screen.getByRole('tab', { name: 'Transcript' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('heading', { name: 'Intelligence Studio' })).toBeInTheDocument();
    expect(screen.getByText('Start from Transcripts')).toBeInTheDocument();
  });

  it('lists persisted build artifacts in the saved artifacts tab', async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(
      'agentlab.build-artifacts.v1',
      JSON.stringify([
        {
          artifact_id: 'artifact-123',
          title: 'Airline Support Agent',
          summary: 'Generated from a prompt',
          source: 'prompt',
          status: 'complete',
          created_at: '2026-03-29T12:00:00.000Z',
          updated_at: '2026-03-29T12:00:00.000Z',
          config_yaml: 'agent_name: Airline Support Agent',
        },
      ])
    );

    renderPage();

    await user.click(screen.getByRole('tab', { name: 'Saved Artifacts' }));

    expect(screen.getAllByRole('heading', { name: 'Saved Artifacts' }).length).toBeGreaterThan(0);
    expect(screen.getByText('Airline Support Agent')).toBeInTheDocument();
    expect(screen.getByText('Generated from a prompt')).toBeInTheDocument();
  });

  it('switches the XML instruction studio into form mode', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole('button', { name: 'Form View' }));

    expect(screen.getByRole('button', { name: 'Form View' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByLabelText('Instruction role')).toBeInTheDocument();
    expect(screen.getByLabelText('Primary goal')).toBeInTheDocument();
  });

  it('shows inline XML validation feedback when the raw editor becomes malformed', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole('button', { name: 'Raw XML' }));

    const editor = screen.getByLabelText('XML instruction editor');
    await user.clear(editor);
    await user.type(editor, '<role>Broken</role><persona>');

    expect(screen.getByText(/XML parse error/i)).toBeInTheDocument();
  });

  it('can insert a guide example into the XML editor from the examples library', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole('button', { name: 'Raw XML' }));
    await user.click(screen.getByRole('button', { name: 'Weather Routing Guide' }));

    const editor = screen.getByLabelText('XML instruction editor') as HTMLTextAreaElement;
    expect(editor.value).toContain('<role>The main Weather Agent coordinating multiple agents.</role>');
    expect(editor.value).toContain('Begin example');
  });

  it('moves the generated draft config into a modal and promotes testing in refine mode', async () => {
    const user = userEvent.setup();
    const generatedConfig = mockGeneratedConfig();
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === '/api/intelligence/generate-agent') {
          return jsonResponse(generatedConfig);
        }
        return jsonResponse({});
      })
    );

    renderPage();

    await user.type(screen.getByLabelText('Agent description'), 'Build an order support agent');
    await user.click(screen.getByRole('button', { name: 'Generate Agent' }));

    expect(await screen.findByRole('heading', { name: 'Conversational Refinement' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Test Agent' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Live Build Draft' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'View Config' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save & Generate Evals' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save & Run Eval' })).toBeInTheDocument();
    expect(
      screen.getByText(
        'Save this draft first, then choose whether to generate evals or run them immediately from the same config.'
      )
    ).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'View Config' }));

    const dialog = await screen.findByRole('dialog', { name: 'Agent Configuration' });
    expect(within(dialog).getByRole('button', { name: 'Copy YAML' })).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Download Draft' })).toBeInTheDocument();
    expect(within(dialog).getByTestId('yaml-preview')).toBeInTheDocument();

    await user.click(within(dialog).getByRole('button', { name: 'JSON' }));
    expect(within(dialog).getByTestId('builder-config-preview')).toBeInTheDocument();
  });

  it('saves a generated agent and exposes a continue-to-eval handoff', async () => {
    const user = userEvent.setup();
    const generatedConfig = mockGeneratedConfig();
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url === '/api/intelligence/generate-agent') {
          return jsonResponse(generatedConfig);
        }
        if (url === '/api/agents' && init?.method === 'POST') {
          return jsonResponse(
            {
              agent: {
                id: 'agent-v002',
                name: 'Order Guardian',
                model: 'gpt-5.4',
                created_at: '2026-04-01T12:00:00.000Z',
                source: 'built',
                config_path: '/tmp/workspace/configs/v002.yaml',
                status: 'candidate',
              },
              save_result: {
                artifact_id: 'artifact-456',
                config_path: '/tmp/workspace/configs/v002.yaml',
                config_version: 2,
                eval_cases_path: '/tmp/workspace/evals/cases/generated_build.yaml',
                runtime_config_path: '/tmp/workspace/agentlab.yaml',
                workspace_path: '/tmp/workspace',
                actual_config_yaml: 'model: gpt-5.4\n',
              },
            },
            { status: 201 }
          );
        }
        return jsonResponse({});
      })
    );

    renderJourney();

    await user.type(screen.getByLabelText('Agent description'), 'Build an order support agent');
    await user.click(screen.getByRole('button', { name: 'Generate Agent' }));
    await screen.findByRole('heading', { name: 'Conversational Refinement' });

    await user.click(screen.getByRole('button', { name: 'Save to Workspace' }));

    expect(await screen.findByRole('button', { name: 'Continue to Eval' })).toBeInTheDocument();
    expect(screen.getAllByText('/tmp/workspace/configs/v002.yaml').length).toBeGreaterThan(0);
  });

  it('auto-saves the current draft before navigating into an eval run', async () => {
    const user = userEvent.setup();
    const generatedConfig = mockGeneratedConfig();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/intelligence/generate-agent') {
        return jsonResponse(generatedConfig);
      }
      if (url === '/api/agents' && init?.method === 'POST') {
        return jsonResponse(
          {
            agent: {
              id: 'agent-v002',
              name: 'Order Guardian',
              model: 'gpt-5.4',
              created_at: '2026-04-01T12:00:00.000Z',
              source: 'built',
              config_path: '/tmp/workspace/configs/v002.yaml',
              status: 'candidate',
            },
            save_result: {
              artifact_id: 'artifact-456',
              config_path: '/tmp/workspace/configs/v002.yaml',
              config_version: 2,
              eval_cases_path: '/tmp/workspace/evals/cases/generated_build.yaml',
              runtime_config_path: '/tmp/workspace/agentlab.yaml',
              workspace_path: '/tmp/workspace',
              actual_config_yaml: 'model: gpt-5.4\n',
            },
          },
          { status: 201 }
        );
      }
      return jsonResponse({});
    });
    vi.stubGlobal('fetch', fetchMock);

    renderJourney();

    await user.type(screen.getByLabelText('Agent description'), 'Build an order support agent');
    await user.click(screen.getByRole('button', { name: 'Generate Agent' }));
    await screen.findByRole('heading', { name: 'Conversational Refinement' });

    await user.click(screen.getByRole('button', { name: 'Save & Run Eval' }));

    expect(await screen.findByText('Eval Page')).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/agents',
      expect.objectContaining({
        method: 'POST',
      })
    );
  });
});
