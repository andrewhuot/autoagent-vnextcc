import { beforeEach, describe, expect, it } from 'vitest';
import type { BuildStreamEvent, HarnessMetrics, PlanTask, WorkbenchArtifact } from './workbench-api';
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

  it('marks buildStatus done on build.completed', () => {
    dispatch({ event: 'plan.ready', data: { plan: makePlan() } });
    dispatch({ event: 'build.completed', data: { project_id: 'wb-42', version: 3 } });
    const state = useWorkbenchStore.getState();
    expect(state.buildStatus).toBe('done');
    expect(state.version).toBe(3);
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

// ---------------------------------------------------------------------------
// Harness metrics, reflections, iteration
// ---------------------------------------------------------------------------

describe('workbench-store — harness features', () => {
  beforeEach(() => {
    useWorkbenchStore.getState().reset();
  });

  it('updates harnessMetrics on harness.metrics event', () => {
    dispatch({
      event: 'harness.metrics',
      data: {
        steps_completed: 3,
        total_steps: 8,
        tokens_used: 2400,
        cost_usd: 0.02,
        elapsed_ms: 12000,
        current_phase: 'executing' as HarnessMetrics['currentPhase'],
      },
    });
    const { harnessMetrics } = useWorkbenchStore.getState();
    expect(harnessMetrics).not.toBeNull();
    expect(harnessMetrics?.stepsCompleted).toBe(3);
    expect(harnessMetrics?.totalSteps).toBe(8);
    expect(harnessMetrics?.tokensUsed).toBe(2400);
    expect(harnessMetrics?.costUsd).toBe(0.02);
    expect(harnessMetrics?.elapsedMs).toBe(12000);
    expect(harnessMetrics?.currentPhase).toBe('executing');
  });

  it('merges partial harness.metrics events without losing existing fields', () => {
    dispatch({
      event: 'harness.metrics',
      data: { steps_completed: 2, total_steps: 8, tokens_used: 1000, cost_usd: 0.01, elapsed_ms: 5000, current_phase: 'planning' },
    });
    // Second event only updates tokens and phase — rest should carry forward.
    dispatch({
      event: 'harness.metrics',
      data: { tokens_used: 2400, current_phase: 'executing' },
    });
    const { harnessMetrics } = useWorkbenchStore.getState();
    expect(harnessMetrics?.stepsCompleted).toBe(2);
    expect(harnessMetrics?.totalSteps).toBe(8);
    expect(harnessMetrics?.tokensUsed).toBe(2400);
    expect(harnessMetrics?.currentPhase).toBe('executing');
  });

  it('appends reflection entries on reflection.completed event', () => {
    dispatch({
      event: 'reflection.completed',
      data: {
        id: 'reflect-1',
        task_id: 'task-root',
        quality_score: 85,
        suggestions: ['Add error handling', 'Write a unit test'],
        timestamp: 1_000_000,
      },
    });
    const { reflections } = useWorkbenchStore.getState();
    expect(reflections).toHaveLength(1);
    expect(reflections[0].id).toBe('reflect-1');
    expect(reflections[0].qualityScore).toBe(85);
    expect(reflections[0].suggestions).toEqual(['Add error handling', 'Write a unit test']);
  });

  it('accumulates multiple reflections across events', () => {
    dispatch({ event: 'reflection.completed', data: { id: 'r1', quality_score: 70, suggestions: [], task_id: 't1', timestamp: 1 } });
    dispatch({ event: 'reflection.completed', data: { id: 'r2', quality_score: 90, suggestions: [], task_id: 't2', timestamp: 2 } });
    expect(useWorkbenchStore.getState().reflections).toHaveLength(2);
  });

  it('increments iterationCount and saves history on iteration.started event', () => {
    dispatch({
      event: 'iteration.started',
      data: {
        id: 'iter-1',
        message: 'Add a new tool',
        artifact_count: 3,
        timestamp: 1_000_000,
      },
    });
    const state = useWorkbenchStore.getState();
    expect(state.iterationCount).toBe(1);
    expect(state.iterationHistory).toHaveLength(1);
    expect(state.iterationHistory[0].message).toBe('Add a new tool');
    expect(state.iterationHistory[0].iterationNumber).toBe(1);
  });

  it('snapshots current artifacts into previousVersionArtifacts on iteration.started', () => {
    // Place an artifact in the store first.
    dispatch({ event: 'plan.ready', data: { plan: makePlan() } });
    dispatch({ event: 'artifact.updated', data: { task_id: 'task-role', artifact: makeArtifact() } });
    expect(useWorkbenchStore.getState().artifacts).toHaveLength(1);

    dispatch({ event: 'iteration.started', data: { id: 'iter-1', message: 'Refactor', artifact_count: 1 } });

    expect(useWorkbenchStore.getState().previousVersionArtifacts).toHaveLength(1);
    expect(useWorkbenchStore.getState().previousVersionArtifacts[0].id).toBe('art-1');
  });

  it('startIteration action records message, increments count, and transitions status', () => {
    dispatch({ event: 'plan.ready', data: { plan: makePlan() } });
    dispatch({ event: 'artifact.updated', data: { task_id: 'task-role', artifact: makeArtifact() } });
    dispatch({ event: 'build.completed', data: { project_id: 'wb-1', version: 2 } });

    useWorkbenchStore.getState().startIteration('Improve the guardrail');
    const state = useWorkbenchStore.getState();

    expect(state.buildStatus).toBe('starting');
    expect(state.iterationCount).toBe(1);
    expect(state.iterationHistory[0].message).toBe('Improve the guardrail');
    expect(state.lastBrief).toBe('Improve the guardrail');
    // Previous artifacts should be preserved.
    expect(state.previousVersionArtifacts).toHaveLength(1);
    // Current artifacts are cleared for the new run.
    expect(state.artifacts).toHaveLength(0);
    // A user message is appended to the feed.
    const userMessages = state.messages.filter((m) => m.id.startsWith('msg-user-'));
    expect(userMessages.at(-1)?.text).toBe('Improve the guardrail');
  });

  it('selectVersionForDiff stores the target version and can clear it', () => {
    useWorkbenchStore.getState().selectVersionForDiff(3);
    expect(useWorkbenchStore.getState().diffTargetVersion).toBe(3);
    useWorkbenchStore.getState().selectVersionForDiff(null);
    expect(useWorkbenchStore.getState().diffTargetVersion).toBeNull();
  });

  it('reset() clears all harness state', () => {
    dispatch({ event: 'harness.metrics', data: { steps_completed: 5, total_steps: 10, tokens_used: 500, cost_usd: 0.01, elapsed_ms: 3000, current_phase: 'reflecting' } });
    dispatch({ event: 'reflection.completed', data: { id: 'r1', quality_score: 80, suggestions: [], task_id: 't1', timestamp: 1 } });
    useWorkbenchStore.getState().startIteration('Some change');

    useWorkbenchStore.getState().reset();
    const state = useWorkbenchStore.getState();
    expect(state.harnessMetrics).toBeNull();
    expect(state.reflections).toHaveLength(0);
    expect(state.iterationCount).toBe(0);
    expect(state.iterationHistory).toHaveLength(0);
    expect(state.previousVersionArtifacts).toHaveLength(0);
    expect(state.diffTargetVersion).toBeNull();
  });
});
