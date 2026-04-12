import { beforeEach, describe, expect, it } from 'vitest';
import type { BuildStreamEvent, PlanTask, WorkbenchArtifact } from './workbench-api';
import { useWorkbenchStore } from './workbench-store';

function makePlan(): PlanTask {
  return {
    id: 'task-root',
    title: 'Build agent',
    status: 'pending',
    description: '',
    children: [
      {
        id: 'task-plan',
        title: 'Plan',
        status: 'pending',
        description: '',
        children: [
          {
            id: 'task-role',
            title: 'Define role',
            status: 'pending',
            description: '',
            children: [],
            artifact_ids: [],
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
  };
}

function makeArtifact(overrides: Partial<WorkbenchArtifact> = {}): WorkbenchArtifact {
  return {
    id: 'art-1',
    task_id: 'task-role',
    category: 'agent',
    name: 'Airline agent role',
    summary: 'Defined the role',
    preview: 'role content',
    source: 'role content',
    language: 'markdown',
    created_at: '2026-04-11T00:00:00Z',
    version: 1,
    ...overrides,
  };
}

function dispatch(event: BuildStreamEvent) {
  useWorkbenchStore.getState().dispatchEvent(event);
}

describe('workbench-store', () => {
  beforeEach(() => {
    useWorkbenchStore.getState().reset();
  });

  it('records a user message and marks build as starting on beginBuild', () => {
    useWorkbenchStore.getState().beginBuild('Build me a flight agent');
    const state = useWorkbenchStore.getState();
    expect(state.buildStatus).toBe('starting');
    expect(state.messages).toHaveLength(1);
    expect(state.messages[0].text).toBe('Build me a flight agent');
    expect(state.lastBrief).toBe('Build me a flight agent');
  });

  it('records a plan on plan.ready and flips to running', () => {
    dispatch({ event: 'plan.ready', data: { project_id: 'wb-42', plan: makePlan() } });
    const state = useWorkbenchStore.getState();
    expect(state.plan?.id).toBe('task-root');
    expect(state.projectId).toBe('wb-42');
    expect(state.buildStatus).toBe('running');
  });

  it('transitions task status on task.started and task.completed', () => {
    dispatch({ event: 'plan.ready', data: { plan: makePlan() } });
    dispatch({ event: 'task.started', data: { task_id: 'task-role' } });
    let leaf = useWorkbenchStore
      .getState()
      .plan?.children[0].children[0];
    expect(leaf?.status).toBe('running');

    dispatch({ event: 'task.completed', data: { task_id: 'task-role' } });
    leaf = useWorkbenchStore.getState().plan?.children[0].children[0];
    expect(leaf?.status).toBe('done');
    // Parent bubble-up.
    const parent = useWorkbenchStore.getState().plan?.children[0];
    expect(parent?.status).toBe('done');
  });

  it('appends delta text into a single assistant message bubble', () => {
    dispatch({ event: 'plan.ready', data: { plan: makePlan() } });
    dispatch({
      event: 'message.delta',
      data: { task_id: 'task-root', text: 'Here is the plan' },
    });
    dispatch({
      event: 'message.delta',
      data: { task_id: 'task-root', text: ' for your agent.' },
    });
    const messages = useWorkbenchStore.getState().messages;
    expect(messages).toHaveLength(1);
    expect(messages[0].text).toBe('Here is the plan for your agent.');
  });

  it('stores artifacts and auto-focuses the most recent one', () => {
    dispatch({ event: 'plan.ready', data: { plan: makePlan() } });
    dispatch({
      event: 'artifact.updated',
      data: { task_id: 'task-role', artifact: makeArtifact() },
    });
    dispatch({
      event: 'artifact.updated',
      data: {
        task_id: 'task-role',
        artifact: makeArtifact({ id: 'art-2', name: 'Second artifact' }),
      },
    });
    const state = useWorkbenchStore.getState();
    expect(state.artifacts.map((a) => a.id)).toEqual(['art-1', 'art-2']);
    expect(state.activeArtifactId).toBe('art-2');
  });

  it('respects user-selected active artifact for the debounce window', () => {
    dispatch({ event: 'plan.ready', data: { plan: makePlan() } });
    dispatch({
      event: 'artifact.updated',
      data: { task_id: 'task-role', artifact: makeArtifact() },
    });
    useWorkbenchStore.getState().setActiveArtifact('art-1');

    // A new artifact arrives within the 3s debounce window — should NOT steal focus.
    dispatch({
      event: 'artifact.updated',
      data: {
        task_id: 'task-role',
        artifact: makeArtifact({ id: 'art-2', name: 'Second artifact' }),
      },
    });
    expect(useWorkbenchStore.getState().activeArtifactId).toBe('art-1');
  });

  it('keeps the harness running on build.completed until run.completed arrives', () => {
    dispatch({ event: 'plan.ready', data: { plan: makePlan() } });
    dispatch({ event: 'build.completed', data: { project_id: 'wb-42', version: 3 } });
    const state = useWorkbenchStore.getState();
    expect(state.buildStatus).toBe('running');
    expect(state.version).toBe(3);
  });

  it('stores terminal run payloads from run.completed', () => {
    dispatch({ event: 'plan.ready', data: { project_id: 'wb-42', run_id: 'run-1', plan: makePlan() } });
    dispatch({
      event: 'run.completed',
      data: {
        project_id: 'wb-42',
        run_id: 'run-1',
        version: 4,
        status: 'completed',
        phase: 'present',
        validation: {
          run_id: 'validation-1',
          status: 'passed',
          created_at: '2026-04-11T00:00:00Z',
          checks: [{ name: 'exports_compile', passed: true, detail: 'Rendered.' }],
          trace: [{ event: 'compile_exports', status: 'passed' }],
        },
        presentation: {
          run_id: 'run-1',
          version: 4,
          summary: 'Built 3 changes.',
          artifact_ids: ['art-1'],
          active_artifact_id: 'art-1',
          generated_outputs: ['agent.py'],
          validation_status: 'passed',
          next_actions: ['Review artifacts.'],
        },
        project: {
          project_id: 'wb-42',
          name: 'Harness Workbench',
          target: 'portable',
          environment: 'draft',
          version: 4,
          draft_badge: 'Draft v4',
          model: {
            project: { name: 'Harness Workbench', description: 'Build.' },
            agents: [
              {
                id: 'root',
                name: 'Harness Agent',
                role: 'Help users.',
                model: 'gpt-5.4-mini',
                instructions: 'Help safely.',
                sub_agents: [],
              },
            ],
            tools: [],
            callbacks: [],
            guardrails: [],
            eval_suites: [],
            environments: [],
            deployments: [],
          },
          compatibility: [],
          exports: {
            generated_config: {},
            adk: { target: 'adk', files: { 'agent.py': 'root_agent = ...' } },
            cx: { target: 'cx', files: { 'agent.json': '{}' } },
          },
          last_test: null,
          versions: [],
          activity: [{ id: 'act-1', kind: 'test', created_at: 'now', summary: 'Harness reflection passed.', diff: [] }],
        },
        exports: {
          generated_config: {},
          adk: { target: 'adk', files: { 'agent.py': 'root_agent = ...' } },
          cx: { target: 'cx', files: { 'agent.json': '{}' } },
        },
        compatibility: [],
        activity: [{ id: 'act-1', kind: 'test', created_at: 'now', summary: 'Harness reflection passed.', diff: [] }],
        run: {
          run_id: 'run-1',
          status: 'completed',
          phase: 'present',
          events: [],
          messages: [],
          validation: null,
          presentation: null,
        },
      },
    });

    const state = useWorkbenchStore.getState();
    expect(state.buildStatus).toBe('done');
    expect(state.version).toBe(4);
    expect(state.projectName).toBe('Harness Workbench');
    expect(state.canonicalModel?.agents[0].name).toBe('Harness Agent');
    expect(state.lastTest?.status).toBe('passed');
    expect(state.activeRun?.run_id).toBe('run-1');
    expect(state.exports?.adk.files['agent.py']).toContain('root_agent');
    expect(state.activity[0].kind).toBe('test');
  });

  it('stores error message on error event', () => {
    dispatch({ event: 'error', data: { message: 'Provider timed out' } });
    const state = useWorkbenchStore.getState();
    expect(state.buildStatus).toBe('error');
    expect(state.error).toBe('Provider timed out');
  });

  it('defaults to light theme', () => {
    expect(useWorkbenchStore.getState().theme).toBe('light');
  });

  it('toggles theme between light and dark and persists to localStorage', () => {
    // Stub localStorage so we can assert persistence on top of jsdom's
    // partial implementation.
    const storage: Record<string, string> = {};
    const stub = {
      getItem: (key: string) => storage[key] ?? null,
      setItem: (key: string, value: string) => {
        storage[key] = value;
      },
      removeItem: (key: string) => {
        delete storage[key];
      },
      clear: () => {
        for (const key of Object.keys(storage)) delete storage[key];
      },
      key: () => null,
      length: 0,
    };
    Object.defineProperty(window, 'localStorage', { value: stub, configurable: true });

    useWorkbenchStore.getState().toggleTheme();
    expect(useWorkbenchStore.getState().theme).toBe('dark');
    expect(storage['agentlab.workbench.theme']).toBe('dark');
    useWorkbenchStore.getState().toggleTheme();
    expect(useWorkbenchStore.getState().theme).toBe('light');
    expect(storage['agentlab.workbench.theme']).toBe('light');
  });

  it('reset() preserves the user theme choice', () => {
    useWorkbenchStore.getState().setTheme('dark');
    useWorkbenchStore.getState().beginBuild('Build something');
    useWorkbenchStore.getState().reset();
    const state = useWorkbenchStore.getState();
    expect(state.theme).toBe('dark');
    expect(state.messages).toHaveLength(0);
  });
});
