import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AgentWorkbench } from './AgentWorkbench';

function renderWorkbench() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/workbench']}>
        <Routes>
          <Route path="/workbench" element={<AgentWorkbench />} />
          <Route path="/evals" element={<div>Eval Runs</div>} />
          <Route path="/traces" element={<div>Traces</div>} />
          <Route path="/deploy" element={<div>Deploy</div>} />
        </Routes>
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

function mockWorkbenchProject(version = 1) {
  return {
    project_id: 'wb-123',
    name: 'Airline Support Workbench',
    target: 'portable',
    environment: 'draft',
    version,
    draft_badge: version === 1 ? 'Draft v1' : `Draft v${version}`,
    model: {
      project: { name: 'Airline Support Workbench', description: 'Airline support agent' },
      agents: [
        {
          id: 'root',
          name: 'Airline Support Agent',
          role: 'Help travelers with booking changes and cancellations.',
          model: 'gpt-5.4-mini',
          instructions: 'Help travelers safely.',
          sub_agents: [],
        },
      ],
      tools: version > 1
        ? [
            {
              id: 'tool-flight-status-lookup',
              name: 'flight_status_lookup',
              description: 'Look up flight status.',
              type: 'function_tool',
            },
          ]
        : [],
      callbacks: version > 1
        ? [{ id: 'callback-after-response-summary', name: 'after_response_summary', hook: 'after_response' }]
        : [],
      guardrails: version > 1
        ? [{ id: 'guardrail-pii', name: 'PII Protection', rule: 'Never expose private data.' }]
        : [],
      eval_suites: version > 1
        ? [{ id: 'eval-delayed-flights', name: 'Delayed Flights', cases: [{ id: 'case-1', input: 'My flight is delayed.' }] }]
        : [],
      environments: [{ id: 'draft', name: 'Draft', target: 'portable' }],
      deployments: [],
    },
    compatibility: [
      {
        object_id: 'tool-flight-status-lookup',
        label: 'flight_status_lookup',
        target: 'portable',
        status: 'portable',
        reason: 'Function tools export to ADK and CX.',
      },
    ],
    exports: {
      adk: { target: 'adk', files: { 'agent.py': 'root_agent = Agent(...)', 'tools.py': 'def flight_status_lookup(): pass' } },
      cx: { target: 'cx', files: { 'agent.json': '{"displayName":"Airline Support Agent"}' } },
    },
    last_test: version > 1
      ? { status: 'passed', checks: [{ name: 'canonical_model_present', passed: true, detail: 'Model exists.' }] }
      : null,
    versions: [
      {
        version: 1,
        created_at: '2026-04-11T00:00:00Z',
        summary: 'Initial project draft',
      },
    ],
    activity: [],
  };
}

describe('AgentWorkbench', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });

  it('renders the two-pane workbench and all MVP truth tabs', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({
      project: mockWorkbenchProject(),
    }));

    renderWorkbench();

    expect(await screen.findByRole('heading', { name: 'Agent Builder Workbench' })).toBeInTheDocument();
    expect(screen.getByText('Conversation on the left. Truth on the right.')).toBeInTheDocument();
    expect(screen.getByTestId('workbench-left-pane')).toBeInTheDocument();
    expect(screen.getByTestId('workbench-right-pane')).toBeInTheDocument();

    for (const tabName of [
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
      'Activity / Diff',
    ]) {
      expect(screen.getByRole('tab', { name: tabName })).toBeInTheDocument();
    }
  });

  it('shows a change plan before apply and then records the automatic test result', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.mocked(fetch);
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ project: mockWorkbenchProject() }))
      .mockResolvedValueOnce(jsonResponse({
        project: mockWorkbenchProject(),
        plan: {
          plan_id: 'plan-123',
          status: 'planned',
          summary: 'Add a flight status lookup tool and guardrail.',
          requires_approval: true,
          operations: [
            { operation: 'add_tool', target: 'tools', label: 'flight_status_lookup', compatibility_status: 'portable' },
            { operation: 'add_guardrail', target: 'guardrails', label: 'PII Protection', compatibility_status: 'portable' },
          ],
        },
      }))
      .mockResolvedValueOnce(jsonResponse({
        project: mockWorkbenchProject(2),
        plan: {
          plan_id: 'plan-123',
          status: 'applied',
          summary: 'Applied plan.',
          requires_approval: false,
          operations: [],
        },
      }));

    renderWorkbench();

    await user.type(
      await screen.findByLabelText('Workbench request'),
      'Add a flight status tool and a PII guardrail'
    );
    await user.click(screen.getByRole('button', { name: 'Plan' }));

    const planCard = await screen.findByTestId('workbench-change-plan');
    expect(within(planCard).getByText('Add a flight status lookup tool and guardrail.')).toBeInTheDocument();
    expect(within(planCard).getByText('flight_status_lookup')).toBeInTheDocument();
    expect(screen.queryByText('canonical_model_present')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Apply plan' }));

    expect(await screen.findByText('Automatic test passed')).toBeInTheDocument();
    expect(screen.getByText('canonical_model_present')).toBeInTheDocument();
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith('/api/workbench/apply', expect.objectContaining({ method: 'POST' }));
    });
  });
});
