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
    expect(screen.getAllByText('Artifacts').length).toBeGreaterThanOrEqual(1);
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
});
