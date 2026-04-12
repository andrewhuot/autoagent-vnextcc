import { beforeEach, describe, expect, it } from 'vitest';
import type { BuildStreamEvent, PlanTask, WorkbenchArtifact, WorkbenchRun } from './workbench-api';
import { isWorkbenchBuildActive, useWorkbenchStore } from './workbench-store';

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

function makeRun(overrides: Partial<WorkbenchRun> = {}): WorkbenchRun {
  return {
    run_id: 'run-1',
    project_id: 'wb-42',
    brief: 'Build agent',
    target: 'portable',
    environment: 'draft',
    status: 'running',
    phase: 'planning',
    started_version: 1,
    completed_version: null,
    created_at: '2026-04-11T00:00:00Z',
    updated_at: '2026-04-11T00:00:01Z',
    completed_at: null,
    error: null,
    events: [],
    messages: [],
    validation: null,
    presentation: null,
    ...overrides,
  };
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
    dispatch({
      event: 'turn.started',
      data: { project_id: 'wb-42', turn_id: 'turn-1', mode: 'initial', brief: 'go' },
    });
    dispatch({ event: 'plan.ready', data: { plan: makePlan() } });
    dispatch({ event: 'build.completed', data: { project_id: 'wb-42', version: 3 } });
    // After build.completed the harness continues through reflect/present
    // phases — buildStatus stays 'running' until run.completed arrives.
    const state = useWorkbenchStore.getState();
    expect(state.buildStatus).toBe('running');
    expect(state.version).toBe(3);
    expect(state.turns).toHaveLength(1);
    expect(state.turns[0].status).toBe('running');
  });

  it('accumulates turns across multi-turn messages', () => {
    dispatch({
      event: 'turn.started',
      data: { project_id: 'wb-42', turn_id: 'turn-1', mode: 'initial', brief: 'Initial' },
    });
    dispatch({ event: 'plan.ready', data: { plan: makePlan() } });
    dispatch({
      event: 'turn.completed',
      data: { project_id: 'wb-42', turn_id: 'turn-1', status: 'completed' },
    });

    dispatch({
      event: 'turn.started',
      data: {
        project_id: 'wb-42',
        turn_id: 'turn-2',
        mode: 'follow_up',
        brief: 'Follow-up',
      },
    });
    dispatch({ event: 'plan.ready', data: { plan: makePlan(), turn_id: 'turn-2' } });
    dispatch({
      event: 'artifact.updated',
      data: {
        task_id: 'task-role',
        turn_id: 'turn-2',
        artifact: makeArtifact({ id: 'art-follow', turn_id: 'turn-2' }),
      },
    });
    dispatch({
      event: 'turn.completed',
      data: { project_id: 'wb-42', turn_id: 'turn-2', status: 'completed' },
    });

    const state = useWorkbenchStore.getState();
    expect(state.turns).toHaveLength(2);
    expect(state.turns[0].turnId).toBe('turn-1');
    expect(state.turns[1].turnId).toBe('turn-2');
    expect(state.turns[1].mode).toBe('follow_up');
    expect(state.turns[1].artifactIds).toContain('art-follow');
  });

  it('tracks autonomous iterations via iteration.started and validation.ready', () => {
    dispatch({
      event: 'turn.started',
      data: { project_id: 'wb-42', turn_id: 'turn-1', mode: 'initial', brief: 'go' },
    });
    dispatch({
      event: 'iteration.started',
      data: { turn_id: 'turn-1', iteration_id: 'iter-1', index: 0, mode: 'initial' },
    });
    dispatch({
      event: 'validation.ready',
      data: {
        turn_id: 'turn-1',
        iteration_id: 'iter-1',
        status: 'failed',
        checks: [{ name: 'example', passed: false, detail: 'oops' }],
      },
    });
    dispatch({
      event: 'iteration.started',
      data: { turn_id: 'turn-1', iteration_id: 'iter-2', index: 1, mode: 'correction' },
    });
    const state = useWorkbenchStore.getState();
    expect(state.currentIterationIndex).toBe(1);
    expect(state.lastValidation?.status).toBe('failed');
    expect(state.turns[0].iterationCount).toBe(2);
  });

  it('keeps live stream events on the active run before terminal hydration', () => {
    dispatch({
      event: 'turn.started',
      data: {
        project_id: 'wb-42',
        run_id: 'run-1',
        turn_id: 'turn-1',
        mode: 'initial',
        brief: 'go',
        phase: 'planning',
        status: 'running',
        handoff: {
          run_id: 'run-1',
          next_action: 'Watch the run.',
          progress: { total_tasks: 0, completed_tasks: 0 },
          verification: { status: 'pending' },
          last_event: {
            sequence: 1,
            event: 'turn.started',
            phase: 'planning',
            status: 'running',
            created_at: '2026-04-12T00:00:00Z',
          },
        },
      },
    });
    dispatch({
      event: 'plan.ready',
      data: {
        project_id: 'wb-42',
        run_id: 'run-1',
        turn_id: 'turn-1',
        phase: 'planning',
        status: 'running',
        plan: makePlan(),
        handoff: {
          run_id: 'run-1',
          next_action: 'Check the plan.',
          progress: { total_tasks: 1, completed_tasks: 0 },
          verification: { status: 'pending' },
          last_event: {
            sequence: 2,
            event: 'plan.ready',
            phase: 'planning',
            status: 'running',
            created_at: '2026-04-12T00:00:01Z',
          },
        },
      },
    });

    const events = useWorkbenchStore.getState().activeRun?.events ?? [];
    expect(events.map((event) => event.event)).toEqual(['turn.started', 'plan.ready']);
    expect(events[1].sequence).toBe(2);
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
        handoff: {
          run_id: 'run-1',
          phase: 'present',
          status: 'completed',
          next_action: 'Review generated artifacts.',
          progress: {
            total_tasks: 3,
            completed_tasks: 3,
          },
          verification: {
            status: 'passed',
          },
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
    expect(state.activeRun?.handoff?.next_action).toBe('Review generated artifacts.');
    expect(state.activeRun?.handoff?.progress.completed_tasks).toBe(3);
    expect(state.exports?.adk.files['agent.py']).toContain('root_agent');
    expect(state.activity[0].kind).toBe('test');
  });

  it('stores error message on error event', () => {
    dispatch({ event: 'error', data: { message: 'Provider timed out' } });
    const state = useWorkbenchStore.getState();
    expect(state.buildStatus).toBe('error');
    expect(state.error).toBe('Provider timed out');
  });

  it('stores mode, budget, and telemetry details from run start events', () => {
    dispatch({
      event: 'turn.started',
      data: {
        project_id: 'wb-42',
        run_id: 'run-1',
        turn_id: 'run-1',
        mode: 'initial',
        brief: 'Build',
        execution_mode: 'mock',
        provider: 'mock',
        model: 'mock-builder',
        mode_reason: 'forced by test',
        budget: {
          limits: {
            max_iterations: 2,
            max_tokens: 1000,
            max_cost_usd: 1.5,
            max_seconds: 60,
          },
          usage: {
            iterations: 0,
            tokens: 0,
            cost_usd: 0,
            elapsed_ms: 0,
          },
        },
        telemetry_summary: {
          run_id: 'run-1',
          execution_mode: 'mock',
          provider: 'mock',
          model: 'mock-builder',
          duration_ms: 0,
        },
      },
    });

    const state = useWorkbenchStore.getState();
    expect(state.activeRun?.run_id).toBe('run-1');
    expect(state.activeRun?.execution_mode).toBe('mock');
    expect(state.activeRun?.provider).toBe('mock');
    expect(state.activeRun?.budget?.limits.max_tokens).toBe(1000);
    expect(state.activeRun?.telemetry_summary?.execution_mode).toBe('mock');
  });

  it('marks the build cancelled from run.cancelled events', () => {
    dispatch({
      event: 'turn.started',
      data: { project_id: 'wb-42', run_id: 'run-1', turn_id: 'run-1', mode: 'initial', brief: 'Build' },
    });
    dispatch({
      event: 'run.cancelled',
      data: {
        project_id: 'wb-42',
        run_id: 'run-1',
        status: 'cancelled',
        phase: 'terminal',
        cancel_reason: 'operator stopped it',
        run: {
          run_id: 'run-1',
          project_id: 'wb-42',
          brief: 'Build',
          target: 'portable',
          environment: 'draft',
          status: 'cancelled',
          phase: 'terminal',
          started_version: 1,
          completed_version: null,
          created_at: '2026-04-12T00:00:00Z',
          completed_at: '2026-04-12T00:00:01Z',
          error: null,
          cancel_reason: 'operator stopped it',
          events: [],
          messages: [],
          validation: null,
          presentation: null,
        },
      },
    });

    const state = useWorkbenchStore.getState();
    expect(state.buildStatus).toBe('cancelled');
    expect(state.error).toBe('operator stopped it');
    expect(state.activeRun?.status).toBe('cancelled');
    expect(state.activeRun?.cancel_reason).toBe('operator stopped it');
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

describe('workbench-store — harness features', () => {
  beforeEach(() => {
    useWorkbenchStore.getState().reset();
  });

  it('classifies reflecting and presenting as active build states', () => {
    expect(isWorkbenchBuildActive('starting')).toBe(true);
    expect(isWorkbenchBuildActive('reflecting')).toBe(true);
    expect(isWorkbenchBuildActive('presenting')).toBe(true);
    expect(isWorkbenchBuildActive('done')).toBe(false);
  });

  it('stores harness metrics from harness.metrics event', () => {
    dispatch({
      event: 'harness.metrics',
      data: {
        current_phase: 'executing',
        steps_completed: 2,
        total_steps: 5,
        tokens_used: 1200,
        cost_usd: 0.018,
        elapsed_ms: 12500,
      },
    });
    const state = useWorkbenchStore.getState();
    expect(state.harnessMetrics).not.toBeNull();
    expect(state.harnessMetrics?.currentPhase).toBe('executing');
    expect(state.harnessMetrics?.stepsCompleted).toBe(2);
    expect(state.harnessMetrics?.tokensUsed).toBe(1200);
  });

  it('hydrates last harness metrics from the plan snapshot harness state', () => {
    useWorkbenchStore.getState().hydrate({
      projectId: 'wb-42',
      projectName: 'Hydrated Harness',
      target: 'portable',
      environment: 'draft',
      version: 2,
      harnessState: {
        checkpoint_count: 2,
        last_metrics: {
          steps_completed: 3,
          total_steps: 5,
          tokens_used: 1200,
          cost_usd: 0.04,
          elapsed_seconds: 2.5,
          current_phase: 'executing',
        },
      },
    });

    expect(useWorkbenchStore.getState().harnessMetrics).toEqual({
      stepsCompleted: 3,
      totalSteps: 5,
      tokensUsed: 1200,
      costUsd: 0.04,
      elapsedMs: 2500,
      currentPhase: 'executing',
    });
  });

  it('hydrates durable harness state and run summary from snapshots', () => {
    useWorkbenchStore.getState().hydrate({
      projectId: 'wb-42',
      projectName: 'Hydrated Harness',
      target: 'portable',
      environment: 'draft',
      version: 2,
      harnessState: {
        checkpoint_count: 1,
        latest_handoff: {
          run_id: 'run-1',
          phase: 'terminal',
          status: 'completed',
          last_event: { sequence: 9, event: 'run.completed' },
          progress: { total_tasks: 2, completed_tasks: 2 },
          verification: { status: 'passed' },
          next_action: 'Review artifacts and run evals.',
        },
      },
      runSummary: {
        run_id: 'run-1',
        status: 'completed',
        phase: 'presenting',
        mode: 'mock',
        provider: 'mock',
        model: 'mock-workbench',
        validation_status: 'passed',
        changes: [],
        recommended_action: 'Review artifacts and approve for deployment.',
      },
    });

    const state = useWorkbenchStore.getState();
    expect(state.harnessState?.checkpoint_count).toBe(1);
    expect(state.harnessState?.latest_handoff?.next_action).toBe(
      'Review artifacts and run evals.'
    );
    expect(state.runSummary?.recommended_action).toBe(
      'Review artifacts and approve for deployment.'
    );
  });

  it('stores heartbeat liveness and context budget from harness.heartbeat event', () => {
    dispatch({
      event: 'harness.heartbeat',
      data: {
        context_budget: {
          total_tokens: 900,
          conversation_tokens: 300,
          plan_tokens: 200,
          artifact_tokens: 250,
          model_tokens: 150,
          conversation_count: 4,
          artifact_count: 2,
        },
      },
    });

    const state = useWorkbenchStore.getState();
    expect(state.lastHeartbeatAt).toBeGreaterThan(0);
    expect(state.harnessMetrics?.contextBudget?.totalTokens).toBe(900);
    expect(state.harnessMetrics?.contextBudget?.artifactCount).toBe(2);
  });

  it('keeps stale recovery details visible after hydration', () => {
    useWorkbenchStore.getState().hydrate({
      projectId: 'wb-42',
      projectName: 'Recovered Harness',
      target: 'portable',
      environment: 'draft',
      version: 1,
      buildStatus: 'error',
      activeRun: makeRun({
        status: 'failed',
        phase: 'terminal',
        failure_reason: 'stale_interrupted',
        error: 'Run interrupted after process recovery; last update was 90 seconds ago.',
      }),
    });

    expect(useWorkbenchStore.getState().error).toBe(
      'Run interrupted after process recovery; last update was 90 seconds ago.'
    );
  });

  it('keeps cancellation reason visible after hydration', () => {
    useWorkbenchStore.getState().hydrate({
      projectId: 'wb-42',
      projectName: 'Cancelled Harness',
      target: 'portable',
      environment: 'draft',
      version: 1,
      buildStatus: 'cancelled',
      activeRun: makeRun({
        status: 'cancelled',
        phase: 'terminal',
        cancel_reason: 'operator stopped run',
      }),
    });

    expect(useWorkbenchStore.getState().error).toBe('operator stopped run');
  });

  it('increments stall count from progress.stall event', () => {
    dispatch({
      event: 'progress.stall',
      data: { task_id: 'task-role', type: 'no_output' },
    });
    dispatch({
      event: 'progress.stall',
      data: { task_id: 'task-tool', type: 'no_output' },
    });

    const state = useWorkbenchStore.getState();
    expect(state.stallCount).toBe(2);
    expect(state.lastHeartbeatAt).toBeGreaterThan(0);
  });

  it('hydrates harness metrics from persisted harness_state', () => {
    useWorkbenchStore.getState().hydrate({
      projectId: 'wb-42',
      target: 'portable',
      version: 1,
      harnessState: {
        checkpoint_count: 0,
        last_metrics: {
          steps_completed: 3,
          total_steps: 5,
          tokens_used: 250,
          cost_usd: 0.004,
          elapsed_ms: 900,
          current_phase: 'reflecting',
        },
      },
    });

    const state = useWorkbenchStore.getState();
    expect(state.harnessMetrics?.stepsCompleted).toBe(3);
    expect(state.harnessMetrics?.totalSteps).toBe(5);
    expect(state.harnessMetrics?.tokensUsed).toBe(250);
    expect(state.harnessMetrics?.currentPhase).toBe('reflecting');
  });

  it('stores reflections from reflection.completed event', () => {
    dispatch({
      event: 'reflection.completed',
      data: {
        id: 'refl-1',
        quality_score: 0.85,
        suggestions: ['Add error handling', 'Improve guardrails'],
      },
    });
    const state = useWorkbenchStore.getState();
    expect(state.reflections).toHaveLength(1);
    expect(state.reflections[0].qualityScore).toBe(0.85);
    expect(state.reflections[0].suggestions).toHaveLength(2);
  });

  it('records iteration from iteration.started event', () => {
    dispatch({
      event: 'iteration.started',
      data: {
        id: 'iter-1',
        message: 'Improve error handling',
      },
    });
    const state = useWorkbenchStore.getState();
    // Starts at 0, increments to 1
    expect(state.iterationCount).toBe(1);
    expect(state.iterationHistory).toHaveLength(1);
  });

  it('startIteration stores optimistic local state', () => {
    // Seed some artifacts first
    dispatch({ event: 'plan.ready', data: { plan: makePlan() } });
    dispatch({
      event: 'artifact.updated',
      data: { task_id: 'task-role', artifact: makeArtifact() },
    });
    expect(useWorkbenchStore.getState().artifacts).toHaveLength(1);

    useWorkbenchStore.getState().startIteration('Make it better');
    const state = useWorkbenchStore.getState();
    expect(state.buildStatus).toBe('starting');
    expect(state.iterationCount).toBeGreaterThanOrEqual(1);
    expect(state.previousVersionArtifacts).toHaveLength(1);
    // Optimistic user message added
    const userMessages = state.messages.filter((m) => m.role === 'user');
    expect(userMessages.length).toBeGreaterThanOrEqual(1);
  });

  it('startIteration preserves visible artifacts while snapshotting them for diff', () => {
    dispatch({ event: 'plan.ready', data: { plan: makePlan() } });
    dispatch({
      event: 'artifact.updated',
      data: { task_id: 'task-role', artifact: makeArtifact() },
    });

    useWorkbenchStore.getState().startIteration('Add a stricter guardrail');

    const state = useWorkbenchStore.getState();
    expect(state.artifacts.map((artifact) => artifact.id)).toEqual(['art-1']);
    expect(state.previousVersionArtifacts.map((artifact) => artifact.id)).toEqual(['art-1']);
  });

  it('selectVersionForDiff sets the diff target version', () => {
    useWorkbenchStore.getState().selectVersionForDiff(3);
    expect(useWorkbenchStore.getState().diffTargetVersion).toBe(3);
    useWorkbenchStore.getState().selectVersionForDiff(null);
    expect(useWorkbenchStore.getState().diffTargetVersion).toBeNull();
  });

  it('reset clears harness-specific state', () => {
    dispatch({
      event: 'harness.metrics',
      data: { phase: 'reflect', current_step: 'validate', steps_completed: 1, steps_total: 1, tokens_used: 500, estimated_cost: 0.01, elapsed_seconds: 5 },
    });
    dispatch({
      event: 'reflection.completed',
      data: { id: 'refl-1', score: 0.9, summary: 'Great', suggestions: [], created_at: '2026-04-11T00:00:00Z' },
    });
    useWorkbenchStore.getState().selectVersionForDiff(2);

    useWorkbenchStore.getState().reset();
    const state = useWorkbenchStore.getState();
    expect(state.harnessMetrics).toBeNull();
    expect(state.reflections).toHaveLength(0);
    expect(state.iterationCount).toBe(0);
    expect(state.previousVersionArtifacts).toHaveLength(0);
    expect(state.diffTargetVersion).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Skill context integration
// ---------------------------------------------------------------------------

describe('skill context', () => {
  beforeEach(() => {
    useWorkbenchStore.getState().reset();
  });

  it('initializes skillContext as null', () => {
    expect(useWorkbenchStore.getState().skillContext).toBeNull();
  });

  it('captures skill_context from build.completed', () => {
    const dispatch = useWorkbenchStore.getState().dispatchEvent;

    dispatch({
      event: 'build.completed',
      data: {
        project_id: 'proj-1',
        skill_context: {
          build_skills_available: 5,
          runtime_skills_available: 3,
          build_skills_relevant: ['safety_hardening'],
          runtime_skills_relevant: ['order_lookup'],
          skill_store_loaded: true,
        },
      },
    });

    const ctx = useWorkbenchStore.getState().skillContext;
    expect(ctx).not.toBeNull();
    expect(ctx?.build_skills_available).toBe(5);
    expect(ctx?.runtime_skills_available).toBe(3);
    expect(ctx?.skill_store_loaded).toBe(true);
  });

  it('attaches skill_layer from artifact.updated event', () => {
    const dispatch = useWorkbenchStore.getState().dispatchEvent;

    // Set up plan first
    dispatch({ event: 'plan.ready', data: { plan: makePlan() } });

    dispatch({
      event: 'artifact.updated',
      data: {
        task_id: 'task-role',
        artifact: makeArtifact({ id: 'art-skill', category: 'tool' }),
        skill_layer: 'runtime',
      },
    });

    const artifacts = useWorkbenchStore.getState().artifacts;
    const art = artifacts.find((a) => a.id === 'art-skill');
    expect(art).toBeDefined();
    expect(art?.skill_layer).toBe('runtime');
  });

  it('handles artifact.updated events without skill_layer gracefully', () => {
    const dispatch = useWorkbenchStore.getState().dispatchEvent;

    // Set up plan
    dispatch({ event: 'plan.ready', data: { plan: makePlan() } });

    // Event without skill_layer (older harness or mock mode)
    dispatch({
      event: 'artifact.updated',
      data: {
        task_id: 'task-role',
        artifact: makeArtifact({ id: 'art-no-layer', category: 'agent' }),
        // no skill_layer field
      },
    });

    const artifacts = useWorkbenchStore.getState().artifacts;
    const art = artifacts.find((a) => a.id === 'art-no-layer');
    expect(art).toBeDefined();
    // skill_layer should be undefined (not crash)
    expect(art?.skill_layer).toBeUndefined();
  });

  it('resets skillContext on reset()', () => {
    const dispatch = useWorkbenchStore.getState().dispatchEvent;
    dispatch({
      event: 'build.completed',
      data: {
        project_id: 'proj-1',
        skill_context: {
          build_skills_available: 2,
          runtime_skills_available: 1,
          skill_store_loaded: true,
        },
      },
    });
    expect(useWorkbenchStore.getState().skillContext).not.toBeNull();

    useWorkbenchStore.getState().reset();
    expect(useWorkbenchStore.getState().skillContext).toBeNull();
  });
});
