import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
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
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
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
  iterateBody?: string;
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

  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input.toString();
    if (url.endsWith('/api/workbench/projects/default')) {
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
      return new Response(opts.iterateBody ?? '', {
        status: 200,
        headers: { 'Content-Type': 'text/event-stream' },
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
      screen.getByText('Processes paused, click to wake up')
    ).toBeInTheDocument();

    // Chat input is rendered.
    expect(screen.getByLabelText('Build request')).toBeInTheDocument();
  });

  it('renders a plan tree and artifacts from the store', async () => {
    installMockFetch();
    renderWorkbench();

    // Wait for the initial hydration flow to settle.
    await screen.findByText('Processes paused, click to wake up');

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
    expect(screen.getByText('Artifacts')).toBeInTheDocument();
  });

  it('pushes the user message immediately when the chat input is submitted', async () => {
    installMockFetch({
      streamBody:
        'event: plan.ready\ndata: {"project_id":"wb-test","plan":{"id":"task-root","title":"Build Sales agent","status":"running","description":"","children":[{"id":"task-a","title":"Plan","status":"running","children":[],"artifact_ids":[],"log":[],"parent_id":"task-root","started_at":null,"completed_at":null}],"artifact_ids":[],"log":[],"parent_id":null,"started_at":null,"completed_at":null}}\n\n',
    });

    const user = userEvent.setup();
    renderWorkbench();

    // Wait for the initial hydrate to finish.
    await screen.findByText('Processes paused, click to wake up');

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

  it('dispatches harness.metrics events into the store', async () => {
    const metricsEvent =
      'event: harness.metrics\ndata: {"steps_completed":2,"total_steps":8,"tokens_used":1200,"cost_usd":0.01,"elapsed_ms":5000,"current_phase":"executing"}\n\n' +
      'event: build.completed\ndata: {"project_id":"wb-test","version":1}\n\n';

    installMockFetch({ streamBody: metricsEvent });
    const user = userEvent.setup();
    renderWorkbench();
    await screen.findByText('Processes paused, click to wake up');

    const textarea = screen.getByLabelText('Build request');
    await user.type(textarea, 'Build an agent{Enter}');

    await waitFor(() => {
      const metrics = useWorkbenchStore.getState().harnessMetrics;
      expect(metrics?.stepsCompleted).toBe(2);
      expect(metrics?.tokensUsed).toBe(1200);
      expect(metrics?.currentPhase).toBe('executing');
    });
  });

  it('dispatches reflection.completed events into the store', async () => {
    const reflectionEvent =
      'event: reflection.completed\ndata: {"id":"r1","task_id":"task-root","quality_score":88,"suggestions":["Add retry logic"],"timestamp":1000}\n\n' +
      'event: build.completed\ndata: {"project_id":"wb-test","version":1}\n\n';

    installMockFetch({ streamBody: reflectionEvent });
    const user = userEvent.setup();
    renderWorkbench();
    await screen.findByText('Processes paused, click to wake up');

    const textarea = screen.getByLabelText('Build request');
    await user.type(textarea, 'Build an agent{Enter}');

    await waitFor(() => {
      const reflections = useWorkbenchStore.getState().reflections;
      expect(reflections).toHaveLength(1);
      expect(reflections[0].qualityScore).toBe(88);
      expect(reflections[0].suggestions).toContain('Add retry logic');
    });
  });

  it('renders a reflection card inline in the conversation feed', async () => {
    const reflectionEvent =
      'event: reflection.completed\ndata: {"id":"r1","task_id":"task-root","quality_score":75,"suggestions":["Improve test coverage"],"timestamp":1000}\n\n' +
      'event: build.completed\ndata: {"project_id":"wb-test","version":1}\n\n';

    installMockFetch({ streamBody: reflectionEvent });
    const user = userEvent.setup();
    renderWorkbench();
    await screen.findByText('Processes paused, click to wake up');

    await user.type(screen.getByLabelText('Build request'), 'Build an agent{Enter}');

    // Reflection card shows the suggestion text.
    await screen.findByText('Improve test coverage');
    // And the Apply button.
    expect(screen.getByRole('button', { name: 'Apply' })).toBeInTheDocument();
  });

  it('submits an iteration request via the /iterate endpoint when a build is complete and IterationControls fires', async () => {
    // First build completes.
    const completedBuildBody =
      'event: build.completed\ndata: {"project_id":"wb-test","version":1}\n\n';
    const iterateBody =
      'event: build.completed\ndata: {"project_id":"wb-test","version":2}\n\n';

    const fetchMock = installMockFetch({ streamBody: completedBuildBody, iterateBody });
    const user = userEvent.setup();
    renderWorkbench();
    await screen.findByText('Processes paused, click to wake up');

    // Submit the initial build.
    await user.type(screen.getByLabelText('Build request'), 'Build an agent{Enter}');

    // Wait for build to complete and IterationControls to render.
    await waitFor(() => {
      expect(useWorkbenchStore.getState().buildStatus).toBe('done');
    });
    await screen.findByTestId('iteration-controls');

    // Open iterate input and submit.
    await user.click(screen.getByRole('button', { name: /iterate/i }));
    await user.type(screen.getByLabelText('Iteration message'), 'Add retry logic');
    await user.click(screen.getByRole('button', { name: /^run$/i }));

    // The /iterate endpoint should have been called.
    await waitFor(() => {
      const iterateCalls = fetchMock.mock.calls.filter(
        ([url]: [string]) => typeof url === 'string' && url.endsWith('/api/workbench/build/iterate')
      );
      expect(iterateCalls.length).toBe(1);
    });

    // Store version should update to 2 after iteration.
    await waitFor(() => {
      expect(useWorkbenchStore.getState().version).toBe(2);
    });
  });
});
