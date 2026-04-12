import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { AgentWorkbench } from './AgentWorkbench';
import { useWorkbenchStore } from '../lib/workbench-store';

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
          <Route path="/evals" element={<EvalLocationProbe />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

function EvalLocationProbe() {
  const location = useLocation();
  const state = location.state as { agent?: { name?: string; config_path?: string } } | null;
  return (
    <div>
      <p>Eval Page</p>
      <p>{location.search}</p>
      <p>{state?.agent?.name ?? 'No handoff agent'}</p>
      <p>{state?.agent?.config_path ?? 'No handoff config'}</p>
    </div>
  );
}

/**
 * Build a mock fetch that satisfies the three requests the page issues on
 * mount (default project, plan snapshot) plus an optional SSE body on the
 * fourth call (POST /api/workbench/build/stream).
 */
function installMockFetch(opts: {
  projectId?: string;
  planSnapshot?: Record<string, unknown>;
  streamBody?: string;
  bridgeResponse?: Record<string, unknown>;
} = {}) {
  const projectId = opts.projectId ?? 'wb-test';
  const defaultProject = {
    project: {
      project_id: projectId,
      name: 'Airline Support Workbench',
      target: 'portable',
      environment: 'draft',
      version: 1,
      draft_badge: 'Draft v1',
      model: {
        project: { name: 'Airline Support Workbench', description: 'Airline support agent' },
        agents: [
          {
            id: 'root',
            name: 'Airline Support Agent',
            role: 'Help travelers',
            model: 'gpt-5.4-mini',
            instructions: 'Help travelers safely.',
            sub_agents: [],
          },
        ],
        tools: [],
        callbacks: [],
        guardrails: [],
        eval_suites: [],
        environments: [{ id: 'draft', name: 'Draft', target: 'portable' }],
        deployments: [],
      },
      compatibility: [],
      exports: { adk: { target: 'adk', files: {} }, cx: { target: 'cx', files: {} } },
      last_test: null,
      versions: [{ version: 1, created_at: '2026-04-11T00:00:00Z', summary: 'Initial' }],
      activity: [],
    },
    exports: { adk: { target: 'adk', files: {} }, cx: { target: 'cx', files: {} } },
    activity: [],
  };
  const planSnapshot = opts.planSnapshot ?? {
    project_id: projectId,
    name: 'Airline Support Workbench',
    target: 'portable',
    environment: 'draft',
    version: 1,
    build_status: 'idle',
    plan: null,
    artifacts: [],
    model: defaultProject.project.model,
    exports: defaultProject.exports,
    compatibility: [],
    last_brief: '',
  };

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString();
    const method = init?.method ?? 'GET';
    if (url.endsWith('/api/workbench/projects/default') && method === 'GET') {
      return new Response(JSON.stringify(defaultProject), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    if (url.includes('/plan') && !url.endsWith('/plan')) {
      return new Response(JSON.stringify(planSnapshot), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    if (url.endsWith('/plan')) {
      return new Response(JSON.stringify(planSnapshot), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    if (url.endsWith('/api/workbench/build/stream')) {
      return new Response(opts.streamBody ?? '', {
        status: 200,
        headers: { 'Content-Type': 'text/event-stream' },
      });
    }
    if (url.endsWith('/api/workbench/build/iterate')) {
      return new Response('', {
        status: 200,
        headers: { 'Content-Type': 'text/event-stream' },
      });
    }
    if (url.includes('/api/workbench/projects/') && url.endsWith('/bridge/eval')) {
      return new Response(JSON.stringify(opts.bridgeResponse ?? {}), {
        status: 201,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    return new Response(JSON.stringify({}), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

describe('AgentWorkbench', () => {
  beforeEach(() => {
    useWorkbenchStore.getState().reset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('hydrates the default project and shows the empty preview state', async () => {
    installMockFetch();
    renderWorkbench();

    // Top bar renders the project name.
    expect(
      await screen.findByRole('heading', { name: 'Airline Support Workbench' })
    ).toBeInTheDocument();

    // Empty preview copy from the reference mockup.
    expect(
      screen.getByText('No artifacts yet')
    ).toBeInTheDocument();

    // Chat input is rendered.
    expect(screen.getByLabelText('Build request')).toBeInTheDocument();

    const journey = screen.getByRole('region', { name: 'Operator journey' });
    expect(within(journey).getByText('Current step: Workbench')).toBeInTheDocument();
    expect(within(journey).getByText('Next: build candidate')).toBeInTheDocument();
    expect(within(journey).queryByText('Next: run eval')).not.toBeInTheDocument();
  });

  it('renders a plan tree and artifacts from the store', async () => {
    installMockFetch();
    renderWorkbench();

    // Wait for the initial hydration flow to settle.
    await screen.findByText('No artifacts yet');

    // Inject a hydrated snapshot — the UI should render plan + artifacts.
    useWorkbenchStore.getState().hydrate({
      projectId: 'wb-test',
      projectName: 'Airline Support Workbench',
      target: 'portable',
      environment: 'draft',
      version: 2,
      buildStatus: 'idle',
      plan: {
        id: 'task-root',
        title: 'Build Airline Support agent',
        description: 'Brief',
        status: 'done',
        children: [
          {
            id: 'task-plan',
            title: 'Plan the agent',
            status: 'done',
            children: [
              {
                id: 'task-role',
                title: 'Define role and capabilities',
                status: 'done',
                children: [],
                artifact_ids: ['art-role'],
                log: [],
                parent_id: 'task-plan',
                started_at: null,
                completed_at: null,
              },
            ],
            artifact_ids: [],
            log: [],
            parent_id: 'task-root',
            started_at: null,
            completed_at: null,
          },
        ],
        artifact_ids: [],
        log: [],
        parent_id: null,
        started_at: null,
        completed_at: null,
      },
      artifacts: [
        {
          id: 'art-role',
          task_id: 'task-role',
          category: 'agent',
          name: 'Airline Support Role',
          summary: 'Defined role and scope.',
          preview: '# Airline Support Agent\n',
          source: '# Airline Support Agent\n',
          language: 'markdown',
          created_at: '2026-04-11T00:00:00Z',
          version: 1,
        },
      ],
    });

    expect(await screen.findByText('Plan the agent')).toBeInTheDocument();
    expect(screen.getByText('Define role and capabilities')).toBeInTheDocument();
    // The artifact shows up both in the left-pane ArtifactCard and as the
    // active preview filename in the right pane — that's intentional.
    expect(screen.getAllByText('Airline Support Role').length).toBeGreaterThanOrEqual(1);
    // Multi-turn feed renders artifacts under a per-turn "Artifacts (n)" heading.
    // "Artifacts" also appears in the workspace tab bar, so use getAllByText.
    expect(screen.getAllByText(/^Artifacts\b/).length).toBeGreaterThanOrEqual(1);
  });

  it('recommends eval only when the Workbench candidate is ready', async () => {
    installMockFetch({
      planSnapshot: {
        project_id: 'wb-test',
        name: 'Airline Support Workbench',
        target: 'portable',
        environment: 'draft',
        version: 2,
        build_status: 'done',
        plan: null,
        artifacts: [],
        model: {
          project: { name: 'Airline Support Workbench', description: 'Airline support agent' },
          agents: [
            {
              id: 'root',
              name: 'Airline Support Agent',
              role: 'Help travelers',
              model: 'gpt-5.4-mini',
              instructions: 'Help travelers safely.',
              sub_agents: [],
            },
          ],
          tools: [],
          callbacks: [],
          guardrails: [],
          eval_suites: [],
          environments: [{ id: 'draft', name: 'Draft', target: 'portable' }],
          deployments: [],
        },
        exports: { adk: { target: 'adk', files: {} }, cx: { target: 'cx', files: {} } },
        compatibility: [],
        last_test: { run_id: 'test-1', status: 'passed', created_at: '2026-04-11T00:00:00Z', checks: [], trace: [] },
        last_brief: 'Build an airline support agent',
        run_summary: {
          run_id: 'run-ready',
          status: 'completed',
          phase: 'presenting',
          mode: 'initial',
          provider: 'mock',
          model: 'gpt-5.4-mini',
          changes: [],
          recommended_action: 'Run eval before optimizing.',
        },
      },
    });

    renderWorkbench();

    const journey = await screen.findByRole('region', { name: 'Operator journey' });
    expect(within(journey).getByText('Current step: Workbench')).toBeInTheDocument();
    expect(within(journey).getByText('Next: run eval')).toBeInTheDocument();
    expect(within(journey).getByRole('link', { name: 'Run eval' })).toHaveAttribute(
      'href',
      '/evals?new=1'
    );
  });

  it('pushes the user message immediately when the chat input is submitted', async () => {
    installMockFetch({
      streamBody:
        'event: plan.ready\ndata: {"project_id":"wb-test","plan":{"id":"task-root","title":"Build Sales agent","status":"running","description":"","children":[{"id":"task-a","title":"Plan","status":"running","children":[],"artifact_ids":[],"log":[],"parent_id":"task-root","started_at":null,"completed_at":null}],"artifact_ids":[],"log":[],"parent_id":null,"started_at":null,"completed_at":null}}\n\n',
    });

    const user = userEvent.setup();
    renderWorkbench();

    // Wait for the initial hydrate to finish.
    await screen.findByText('No artifacts yet');

    const textarea = screen.getByLabelText('Build request');
    await user.type(textarea, 'Build me a sales qualification agent{Enter}');

    // User message is optimistically rendered before any stream events.
    expect(
      await screen.findByText('Build me a sales qualification agent')
    ).toBeInTheDocument();

    await waitFor(() => {
      // Plan tree from the mocked stream was dispatched into the store.
      expect(useWorkbenchStore.getState().plan?.title).toBe('Build Sales agent');
    });
  });

  it('opens the review gate from the header when a completed run has handoff state', async () => {
    const user = userEvent.setup();
    const model = {
      project: { name: 'Airline Support Workbench', description: 'Airline support agent' },
      agents: [
        {
          id: 'root',
          name: 'Airline Support Agent',
          role: 'Help travelers',
          model: 'gpt-5.4-mini',
          instructions: 'Help travelers safely.',
          sub_agents: [],
        },
      ],
      tools: [],
      callbacks: [],
      guardrails: [],
      eval_suites: [],
      environments: [{ id: 'draft', name: 'Draft', target: 'portable' }],
      deployments: [],
    };
    installMockFetch({
      planSnapshot: {
        project_id: 'wb-test',
        name: 'Airline Support Workbench',
        target: 'portable',
        environment: 'draft',
        version: 2,
        build_status: 'completed',
        plan: null,
        artifacts: [],
        messages: [],
        model,
        exports: { generated_config: {}, adk: { target: 'adk', files: {} }, cx: { target: 'cx', files: {} } },
        compatibility: [],
        last_test: null,
        activity: [],
        active_run: {
          run_id: 'run-1',
          project_id: 'wb-test',
          brief: 'Build airline support',
          target: 'portable',
          environment: 'draft',
          status: 'completed',
          phase: 'presenting',
          started_version: 1,
          completed_version: 2,
          created_at: '2026-04-11T00:00:00Z',
          updated_at: '2026-04-11T00:00:01Z',
          completed_at: '2026-04-11T00:00:02Z',
          error: null,
          events: [],
          messages: [],
          validation: null,
          presentation: {
            run_id: 'run-1',
            version: 2,
            summary: 'Built 3 canonical changes.',
            artifact_ids: [],
            active_artifact_id: null,
            generated_outputs: ['agent.py'],
            validation_status: 'passed',
            next_actions: ['Review candidate before promotion.'],
            review_gate: {
              status: 'review_required',
              promotion_status: 'draft',
              requires_human_review: true,
              blocking_reasons: [],
              checks: [
                {
                  name: 'human_review',
                  status: 'required',
                  required: true,
                  detail: 'Human review is required before promotion.',
                },
              ],
            },
            handoff: {
              project_id: 'wb-test',
              run_id: 'run-1',
              turn_id: 'turn-1',
              version: 2,
              review_gate_status: 'review_required',
              active_artifact_id: null,
              last_event_sequence: 12,
              next_operator_action: 'Review candidate and run evals before promotion.',
              resume_prompt: 'Resume Workbench project wb-test at Draft v2.',
            },
          },
        },
        runs: [],
        last_brief: 'Build airline support',
        conversation: [],
        turns: [],
      },
    });
    renderWorkbench();

    const reviewButton = await screen.findByRole('button', { name: 'Review required' });
    expect(reviewButton).toBeEnabled();
    await user.click(reviewButton);

    expect(screen.getByText('Review gate')).toBeInTheDocument();
    expect(screen.getByText('Session handoff')).toBeInTheDocument();
    expect(screen.getByText('Resume Workbench project wb-test at Draft v2.')).toBeInTheDocument();
  });

  it('materializes an eval-ready workbench candidate and opens Eval with prefilled context', async () => {
    const user = userEvent.setup();
    const bridge = {
      kind: 'workbench_eval_optimize',
      schema_version: 1,
      candidate: {
        project_id: 'wb-test',
        run_id: 'run-1',
        version: 2,
        target: 'portable',
        environment: 'draft',
        agent_name: 'Airline Support Agent',
        validation_status: 'passed',
        review_gate_status: 'review_required',
        generated_config_hash: 'sha256:abc123',
        config_path: '/workspace/configs/v003.yaml',
        eval_cases_path: '/workspace/evals/cases/generated_build.yaml',
        export_targets: ['adk', 'cx'],
      },
      evaluation: {
        status: 'ready',
        readiness_state: 'ready_for_eval',
        label: 'Ready for Eval',
        description: 'The Workbench candidate is saved and ready for an Eval run.',
        primary_action_label: 'Open Eval with this candidate',
        primary_action_target: '/evals?source=workbench&new=1',
        request: {
          config_path: '/workspace/configs/v003.yaml',
          split: 'all',
        },
        start_endpoint: '/api/eval/run',
        blocking_reasons: [],
      },
      optimization: {
        status: 'awaiting_eval_run',
        readiness_state: 'awaiting_eval_run',
        label: 'Run Eval before Optimize',
        description: 'Optimize is waiting for a completed Eval run for this saved Workbench candidate.',
        primary_action_label: 'Open Eval with this candidate',
        primary_action_target: '/evals?source=workbench&new=1',
        requires_eval_run: true,
        request_template: {
          config_path: '/workspace/configs/v003.yaml',
          eval_run_id: null,
          window: 100,
          force: true,
          require_human_approval: true,
          mode: 'standard',
          objective: 'Improve failures from the Workbench candidate eval run.',
          guardrails: ['Preserve Workbench validation and target compatibility.'],
          research_algorithm: '',
          budget_cycles: 10,
          budget_dollars: 50,
        },
        start_endpoint: '/api/optimize/run',
        blocking_reasons: ['Run Eval first; Optimize requires a completed eval run.'],
      },
    };
    installMockFetch({
      planSnapshot: {
        project_id: 'wb-test',
        name: 'Airline Support Workbench',
        target: 'portable',
        environment: 'draft',
        version: 2,
        build_status: 'completed',
        plan: null,
        artifacts: [],
        messages: [],
        model: {
          project: { name: 'Airline Support Workbench', description: 'Airline support agent' },
          agents: [],
          tools: [],
          callbacks: [],
          guardrails: [],
          eval_suites: [],
          environments: [],
          deployments: [],
        },
        exports: { generated_config: {}, adk: { target: 'adk', files: {} }, cx: { target: 'cx', files: {} } },
        compatibility: [],
        last_test: null,
        activity: [],
        active_run: {
          run_id: 'run-1',
          project_id: 'wb-test',
          brief: 'Build airline support',
          target: 'portable',
          environment: 'draft',
          status: 'completed',
          phase: 'presenting',
          started_version: 1,
          completed_version: 2,
          created_at: '2026-04-11T00:00:00Z',
          updated_at: '2026-04-11T00:00:01Z',
          completed_at: '2026-04-11T00:00:02Z',
          error: null,
          events: [],
          messages: [],
          validation: null,
          presentation: {
            run_id: 'run-1',
            version: 2,
            summary: 'Built 3 canonical changes.',
            artifact_ids: [],
            active_artifact_id: null,
            generated_outputs: ['agent.py'],
            validation_status: 'passed',
            next_actions: ['Review candidate before promotion.'],
            improvement_bridge: {
              ...bridge,
              candidate: {
                ...bridge.candidate,
                config_path: null,
                eval_cases_path: null,
              },
              evaluation: {
                ...bridge.evaluation,
                status: 'needs_saved_config',
                readiness_state: 'needs_materialization',
                label: 'Save candidate before Eval',
                primary_action_label: 'Save candidate and open Eval',
                request: null,
                blocking_reasons: ['Materialize the Workbench candidate config before starting Eval.'],
              },
            },
          },
        },
        runs: [],
        last_brief: 'Build airline support',
        conversation: [],
        turns: [],
      },
      bridgeResponse: {
        bridge,
        save_result: {
          config_path: '/workspace/configs/v003.yaml',
          eval_cases_path: '/workspace/evals/cases/generated_build.yaml',
        },
        eval_request: bridge.evaluation.request,
        optimize_request_template: bridge.optimization.request_template,
        next: {
          start_eval_endpoint: '/api/eval/run',
          start_optimize_endpoint: '/api/optimize/run',
          optimize_requires_eval_run: true,
        },
      },
    });

    const fetchMock = vi.mocked(fetch);
    renderWorkbench();

    await user.click(await screen.findByRole('button', { name: 'Save candidate and open Eval' }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/workbench/projects/wb-test/bridge/eval',
        expect.objectContaining({ method: 'POST' })
      );
    });
    expect(await screen.findByText('Eval Page')).toBeInTheDocument();
    expect(screen.getByText('Airline Support Agent')).toBeInTheDocument();
    expect(screen.getByText('/workspace/configs/v003.yaml')).toBeInTheDocument();
    expect(screen.getByText(/\?source=workbench/)).toHaveTextContent('configPath=%2Fworkspace%2Fconfigs%2Fv003.yaml');
  });

  it('labels an interrupted hydrated run as restored historical work', async () => {
    installMockFetch({
      planSnapshot: {
        project_id: 'wb-test',
        name: 'Airline Support Workbench',
        target: 'portable',
        environment: 'draft',
        version: 2,
        build_status: 'interrupted',
        plan: null,
        artifacts: [],
        messages: [],
        model: null,
        exports: { generated_config: {}, adk: { target: 'adk', files: {} }, cx: { target: 'cx', files: {} } },
        compatibility: [],
        last_test: null,
        activity: [],
        active_run: {
          run_id: 'run-interrupted',
          project_id: 'wb-test',
          brief: 'Build airline support',
          target: 'portable',
          environment: 'draft',
          status: 'interrupted',
          phase: 'executing',
          started_version: 1,
          completed_version: null,
          created_at: '2026-04-12T13:00:00Z',
          updated_at: '2026-04-12T13:05:00Z',
          completed_at: null,
          error: 'Recovered after restart before the run completed.',
          failure_reason: 'stale_interrupted',
          events: [],
          messages: [],
          validation: null,
          presentation: null,
        },
        runs: [],
        last_brief: 'Build airline support',
        conversation: [],
        turns: [
          {
            turn_id: 'turn-1',
            brief: 'Build airline support',
            mode: 'initial',
            status: 'interrupted',
            created_at: '2026-04-12T13:00:00Z',
            artifact_ids: [],
            iterations: [],
            plan: null,
          },
        ],
      },
    });

    renderWorkbench();

    expect(await screen.findByText('Interrupted')).toBeInTheDocument();
    expect(screen.getByText('Historical snapshot')).toBeInTheDocument();
    expect(screen.getByText('Interrupted run restored after restart')).toBeInTheDocument();
    expect(screen.getByText('Recovered after restart before the run completed.')).toBeInTheDocument();
  });

  it('passes manual iteration budget controls to the iterate stream', async () => {
    const user = userEvent.setup();
    const fetchMock = installMockFetch();
    renderWorkbench();

    await screen.findByText('No artifacts yet');
    useWorkbenchStore.setState({
      projectId: 'wb-test',
      buildStatus: 'done',
      iterationCount: 1,
      maxIterations: 5,
      version: 2,
    });

    await user.click(await screen.findByRole('button', { name: 'Iterate' }));
    await user.type(screen.getByLabelText('Iteration message'), 'Tighten the tool evidence');
    await user.click(screen.getByRole('button', { name: 'Run' }));

    await waitFor(() => {
      const iterateCall = fetchMock.mock.calls.find(([input]) =>
        String(input).endsWith('/api/workbench/build/iterate')
      );
      expect(iterateCall).toBeTruthy();
      const body = JSON.parse(String(iterateCall?.[1]?.body ?? '{}'));
      expect(body.max_iterations).toBe(5);
      expect(body.environment).toBe('draft');
    });
  });
});
