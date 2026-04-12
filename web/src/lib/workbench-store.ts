/**
 * Zustand store for the Agent Builder Workbench page.
 *
 * Owns the streaming build state (plan tree, artifacts, assistant messages)
 * plus a small amount of view state (active artifact, preview vs source).
 * Components subscribe with narrow selectors so high-frequency streaming
 * updates don't re-render the whole page.
 */

import { create } from 'zustand';
import type {
  BuildStreamEvent,
  HarnessMetrics,
  IterationEntry,
  PlanTask,
  PlanTaskStatus,
  ReflectionEntry,
  WorkbenchArtifact,
  WorkbenchCanonicalModel,
  WorkbenchCompatibilityDiagnostic,
  WorkbenchExports,
  WorkbenchMessage,
  WorkbenchPresentation,
  WorkbenchRun,
  WorkbenchTestResult,
  WorkbenchActivity,
  WorkbenchTarget,
} from './workbench-api';
import {
  findTaskById,
  recomputeParentStatus,
  walkTasks,
} from './workbench-plan';

/** One assistant narration bubble shown inline in the conversation feed. */
export interface AssistantMessage {
  id: string;
  role: 'user' | 'assistant';
  taskId: string | null;
  text: string;
  createdAt: number;
}

/** Active artifact view mode on the right pane. */
export type ArtifactView = 'preview' | 'source' | 'diff';

/** Category filter for the artifact tab bar in the right pane. */
export type ArtifactCategoryFilter =
  | 'all'
  | 'agent'
  | 'tool'
  | 'guardrail'
  | 'eval'
  | 'environment';

/** Right-side workspace surfaces backed by the latest harness payload. */
export type WorkspaceTab = 'artifacts' | 'agent' | 'source' | 'evals' | 'trace' | 'activity';

/** High-level lifecycle of the page-wide build flow. */
export type BuildStatus = 'idle' | 'starting' | 'running' | 'done' | 'error';

/** User-facing theme for the Workbench shell. Default is light. */
export type WorkbenchTheme = 'light' | 'dark';

const THEME_STORAGE_KEY = 'agentlab.workbench.theme';

function loadInitialTheme(): WorkbenchTheme {
  if (typeof window === 'undefined') return 'light';
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (stored === 'dark' || stored === 'light') return stored;
  } catch {
    // localStorage may be unavailable in private mode — fall through.
  }
  return 'light';
}

function persistTheme(theme: WorkbenchTheme): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Best-effort — silently skip if storage is unavailable.
  }
}

interface WorkbenchState {
  // --- theme (light by default; user-toggleable, persisted to localStorage)
  theme: WorkbenchTheme;

  // --- identity
  projectId: string | null;
  projectName: string;
  target: WorkbenchTarget;
  environment: string;
  version: number;

  // --- streaming build state
  buildStatus: BuildStatus;
  plan: PlanTask | null;
  artifacts: WorkbenchArtifact[];
  messages: AssistantMessage[];
  lastBrief: string;
  error: string | null;

  // --- view state
  activeArtifactId: string | null;
  activeArtifactView: ArtifactView;
  activeCategory: ArtifactCategoryFilter;
  activeWorkspaceTab: WorkspaceTab;
  userSelectedArtifactAt: number;

  // --- canonical model snapshot for the right-pane "agent" tab
  canonicalModel: WorkbenchCanonicalModel | null;
  exports: WorkbenchExports | null;
  compatibility: WorkbenchCompatibilityDiagnostic[];
  lastTest: WorkbenchTestResult | null;
  activity: WorkbenchActivity[];
  activeRun: WorkbenchRun | null;
  presentation: WorkbenchPresentation | null;

  // --- abort controller for the in-flight stream
  abortController: AbortController | null;

  // --- harness metrics and iteration tracking
  harnessMetrics: HarnessMetrics | null;
  iterationCount: number;
  iterationHistory: IterationEntry[];
  reflections: ReflectionEntry[];
  /** Snapshot of artifacts from the previous iteration, used for diff comparison. */
  previousVersionArtifacts: WorkbenchArtifact[];
  /** Which version number is currently selected for diff (null = none). */
  diffTargetVersion: number | null;
}

interface WorkbenchActions {
  hydrate: (snapshot: {
    projectId: string;
    projectName?: string;
    target: WorkbenchTarget;
    environment?: string;
    version: number;
    plan?: PlanTask | null;
    artifacts?: WorkbenchArtifact[];
    messages?: WorkbenchMessage[];
    canonicalModel?: WorkbenchCanonicalModel | null;
    exports?: WorkbenchExports | null;
    compatibility?: WorkbenchCompatibilityDiagnostic[];
    lastTest?: WorkbenchTestResult | null;
    activity?: WorkbenchActivity[];
    activeRun?: WorkbenchRun | null;
    buildStatus?: BuildStatus;
    lastBrief?: string;
  }) => void;
  beginBuild: (brief: string) => void;
  setAbortController: (controller: AbortController | null) => void;
  cancelBuild: () => void;
  dispatchEvent: (event: BuildStreamEvent) => void;
  setActiveArtifact: (id: string | null) => void;
  setActiveArtifactView: (view: ArtifactView) => void;
  setActiveCategory: (category: ArtifactCategoryFilter) => void;
  setActiveWorkspaceTab: (tab: WorkspaceTab) => void;
  setTarget: (target: WorkbenchTarget) => void;
  setError: (error: string | null) => void;
  setTheme: (theme: WorkbenchTheme) => void;
  toggleTheme: () => void;
  reset: () => void;

  // --- harness actions
  /** Begin a follow-up iteration on the completed build. */
  startIteration: (message: string) => void;
  /** Pin a specific version's artifact snapshot for side-by-side diff. */
  selectVersionForDiff: (version: number | null) => void;
}

const INITIAL_STATE: WorkbenchState = {
  theme: loadInitialTheme(),
  projectId: null,
  projectName: 'New Workbench',
  target: 'portable',
  environment: 'draft',
  version: 1,
  buildStatus: 'idle',
  plan: null,
  artifacts: [],
  messages: [],
  lastBrief: '',
  error: null,
  activeArtifactId: null,
  activeArtifactView: 'preview',
  activeCategory: 'all',
  activeWorkspaceTab: 'artifacts',
  userSelectedArtifactAt: 0,
  canonicalModel: null,
  exports: null,
  compatibility: [],
  lastTest: null,
  activity: [],
  activeRun: null,
  presentation: null,
  abortController: null,
  harnessMetrics: null,
  iterationCount: 0,
  iterationHistory: [],
  reflections: [],
  previousVersionArtifacts: [],
  diffTargetVersion: null,
};

/** Time window during which a user-selected artifact blocks auto-focus. */
const USER_FOCUS_DEBOUNCE_MS = 3_000;

export const useWorkbenchStore = create<WorkbenchState & WorkbenchActions>((set, get) => ({
  ...INITIAL_STATE,

  hydrate: (snapshot) =>
    set((state) => ({
      projectId: snapshot.projectId,
      projectName: snapshot.projectName ?? state.projectName,
      target: snapshot.target,
      environment: snapshot.environment ?? state.environment,
      version: snapshot.version,
      plan: snapshot.plan ?? null,
      artifacts: snapshot.artifacts ?? [],
      messages: snapshot.messages ? snapshot.messages.map(messageFromApi) : state.messages,
      canonicalModel: snapshot.canonicalModel ?? null,
      exports: snapshot.exports ?? state.exports,
      compatibility: snapshot.compatibility ?? state.compatibility,
      lastTest: snapshot.lastTest ?? state.lastTest,
      activity: snapshot.activity ?? state.activity,
      activeRun: snapshot.activeRun ?? state.activeRun,
      presentation: snapshot.activeRun?.presentation ?? state.presentation,
      buildStatus: snapshot.buildStatus ?? state.buildStatus,
      lastBrief: snapshot.lastBrief ?? state.lastBrief,
      error: null,
    })),

  beginBuild: (brief) =>
    set((state) => ({
      buildStatus: 'starting',
      plan: null,
      artifacts: [],
      messages: [
        ...state.messages,
        {
          id: `msg-user-${Date.now()}`,
          role: 'user',
          taskId: null,
          text: brief,
          createdAt: Date.now(),
        },
      ],
      lastBrief: brief,
      activeArtifactId: null,
      error: null,
    })),

  setAbortController: (controller) => set(() => ({ abortController: controller })),

  cancelBuild: () => {
    const controller = get().abortController;
    if (controller) {
      controller.abort();
    }
    set(() => ({ buildStatus: 'idle', abortController: null }));
  },

  dispatchEvent: (event) => {
    const { event: name, data } = event;

    if (name === 'plan.ready') {
      const plan = data.plan as PlanTask;
      set(() => ({
        plan,
        buildStatus: 'running',
        projectId: (data.project_id as string) ?? get().projectId,
        activeRun: mergeRun(get().activeRun, data),
      }));
      return;
    }

    if (name === 'task.started') {
      const { task_id: taskId } = data as { task_id: string };
      set((state) => {
        if (!state.plan) return {};
        const nextPlan = cloneTree(state.plan);
        const task = findTaskById(nextPlan, taskId);
        if (task) {
          task.status = 'running' as PlanTaskStatus;
          task.started_at = new Date().toISOString();
        }
        recomputeParentStatus(nextPlan);
        return { plan: nextPlan };
      });
      return;
    }

    if (name === 'task.progress') {
      const { task_id: taskId, note } = data as { task_id: string; note: string };
      set((state) => {
        if (!state.plan) return {};
        const nextPlan = cloneTree(state.plan);
        const task = findTaskById(nextPlan, taskId);
        if (task && note) {
          task.log = [...(task.log ?? []), note];
        }
        return { plan: nextPlan };
      });
      return;
    }

    if (name === 'message.delta') {
      const { task_id: taskId, text } = data as { task_id: string | null; text: string };
      set((state) => {
        const messages = [...state.messages];
        const last = messages[messages.length - 1];
        const createdAt = Date.now();
        if (last && last.taskId === taskId && last.id.startsWith('msg-assist-')) {
          messages[messages.length - 1] = {
            ...last,
            text: `${last.text}${text}`.trim(),
          };
        } else {
          messages.push({
            id: `msg-assist-${createdAt}-${messages.length}`,
            role: 'assistant',
            taskId,
            text: text.trim(),
            createdAt,
          });
        }
        return { messages };
      });
      return;
    }

    if (name === 'artifact.updated') {
      const incoming = data.artifact as WorkbenchArtifact;
      set((state) => {
        const artifacts = state.artifacts.filter((a) => a.id !== incoming.id);
        artifacts.push(incoming);
        const nextPlan = state.plan ? cloneTree(state.plan) : null;
        if (nextPlan) {
          const task = findTaskById(nextPlan, incoming.task_id);
          if (task && !(task.artifact_ids ?? []).includes(incoming.id)) {
            task.artifact_ids = [...(task.artifact_ids ?? []), incoming.id];
          }
        }
        const userSelectedRecently =
          Date.now() - state.userSelectedArtifactAt < USER_FOCUS_DEBOUNCE_MS;
        return {
          artifacts,
          plan: nextPlan ?? state.plan,
          activeArtifactId:
            state.activeArtifactId && userSelectedRecently
              ? state.activeArtifactId
              : incoming.id,
        };
      });
      return;
    }

    if (name === 'task.completed') {
      const { task_id: taskId } = data as { task_id: string };
      set((state) => {
        if (!state.plan) return {};
        const nextPlan = cloneTree(state.plan);
        const task = findTaskById(nextPlan, taskId);
        if (task) {
          task.status = 'done' as PlanTaskStatus;
          task.completed_at = new Date().toISOString();
        }
        recomputeParentStatus(nextPlan);
        return { plan: nextPlan };
      });
      return;
    }

    if (name === 'build.completed') {
      set((state) => ({
        buildStatus: 'running',
        projectId: (data.project_id as string) ?? state.projectId,
        version: (data.version as number) ?? state.version,
        activeRun: mergeRun(state.activeRun, data),
      }));
      return;
    }

    if (name === 'reflect.started') {
      set((state) => ({
        buildStatus: 'running',
        activeRun: mergeRun(state.activeRun, data),
      }));
      return;
    }

    if (name === 'reflect.completed') {
      const validation = data.validation as WorkbenchTestResult | undefined;
      set((state) => ({
        buildStatus: validation?.status === 'failed' ? 'error' : 'running',
        lastTest: validation ?? state.lastTest,
        activeRun: mergeRun(state.activeRun, data),
      }));
      return;
    }

    if (name === 'present.ready') {
      const presentation = data.presentation as WorkbenchPresentation | undefined;
      set((state) => ({
        buildStatus: 'running',
        presentation: presentation ?? state.presentation,
        activeArtifactId: presentation?.active_artifact_id ?? state.activeArtifactId,
        activeRun: mergeRun(state.activeRun, data),
      }));
      return;
    }

    if (name === 'run.completed') {
      const project = data.project as Partial<{
        name: string;
        target: WorkbenchTarget;
        environment: string;
        version: number;
        model: WorkbenchCanonicalModel;
        exports: WorkbenchExports;
        compatibility: WorkbenchCompatibilityDiagnostic[];
        last_test: WorkbenchTestResult | null;
        activity: WorkbenchActivity[];
        messages: WorkbenchMessage[];
      }> | undefined;
      const validation = data.validation as WorkbenchTestResult | undefined;
      const run = data.run as WorkbenchRun | undefined;
      const presentation = data.presentation as WorkbenchPresentation | undefined;
      set((state) => ({
        buildStatus: data.status === 'completed' ? 'done' : 'error',
        abortController: null,
        projectId: (data.project_id as string) ?? state.projectId,
        projectName: project?.name ?? state.projectName,
        target: project?.target ?? state.target,
        environment: project?.environment ?? state.environment,
        version: (data.version as number) ?? project?.version ?? state.version,
        canonicalModel: project?.model ?? state.canonicalModel,
        exports: (data.exports as WorkbenchExports | undefined) ?? project?.exports ?? state.exports,
        compatibility:
          (data.compatibility as WorkbenchCompatibilityDiagnostic[] | undefined) ??
          project?.compatibility ??
          state.compatibility,
        lastTest: validation ?? project?.last_test ?? state.lastTest,
        activity:
          (data.activity as WorkbenchActivity[] | undefined) ??
          project?.activity ??
          state.activity,
        messages: project?.messages ? project.messages.map(messageFromApi) : state.messages,
        activeRun: run ?? mergeRun(state.activeRun, data),
        presentation: presentation ?? run?.presentation ?? state.presentation,
        error: null,
      }));
      return;
    }

    if (name === 'run.failed') {
      const run = data.run as WorkbenchRun | undefined;
      set((state) => ({
        buildStatus: 'error',
        abortController: null,
        activeRun: run ?? mergeRun(state.activeRun, data),
        error: String((data as { error?: string; message?: string }).error ?? (data as { message?: string }).message ?? 'Build failed.'),
      }));
      return;
    }

    if (name === 'error') {
      set(() => ({
        buildStatus: 'error',
        abortController: null,
        error: String((data as { message?: string }).message ?? 'Build failed.'),
      }));
      return;
    }

    // --- Harness-specific events (additive) ---

    if (name === 'harness.metrics') {
      const incoming = data as {
        steps_completed?: number;
        total_steps?: number;
        tokens_used?: number;
        cost_usd?: number;
        elapsed_ms?: number;
        current_phase?: HarnessMetrics['currentPhase'];
      };
      set((state) => ({
        harnessMetrics: {
          stepsCompleted: incoming.steps_completed ?? state.harnessMetrics?.stepsCompleted ?? 0,
          totalSteps: incoming.total_steps ?? state.harnessMetrics?.totalSteps ?? 0,
          tokensUsed: incoming.tokens_used ?? state.harnessMetrics?.tokensUsed ?? 0,
          costUsd: incoming.cost_usd ?? state.harnessMetrics?.costUsd ?? 0,
          elapsedMs: incoming.elapsed_ms ?? state.harnessMetrics?.elapsedMs ?? 0,
          currentPhase: incoming.current_phase ?? state.harnessMetrics?.currentPhase ?? 'idle',
        },
      }));
      return;
    }

    if (name === 'reflection.completed') {
      const incoming = data as {
        id?: string;
        task_id?: string;
        quality_score?: number;
        suggestions?: string[];
        timestamp?: number;
      };
      const entry: ReflectionEntry = {
        id: incoming.id ?? `reflect-${Date.now()}`,
        taskId: incoming.task_id ?? '',
        qualityScore: incoming.quality_score ?? 0,
        suggestions: incoming.suggestions ?? [],
        timestamp: incoming.timestamp ?? Date.now(),
      };
      set((state) => ({ reflections: [...state.reflections, entry] }));
      return;
    }

    if (name === 'iteration.started') {
      const incoming = data as {
        id?: string;
        message?: string;
        artifact_count?: number;
        timestamp?: number;
      };
      set((state) => {
        // Guard against double-counting from optimistic startIteration()
        const lastEntry = state.iterationHistory[state.iterationHistory.length - 1];
        if (lastEntry && lastEntry.id.startsWith('iter-local-')) {
          return {};
        }
        const nextIterationNumber = state.iterationCount + 1;
        const entry: IterationEntry = {
          id: incoming.id ?? `iter-${Date.now()}`,
          iterationNumber: nextIterationNumber,
          message: incoming.message ?? '',
          timestamp: incoming.timestamp ?? Date.now(),
          artifactCount: incoming.artifact_count ?? state.artifacts.length,
        };
        return {
          iterationCount: nextIterationNumber,
          iterationHistory: [...state.iterationHistory, entry],
          previousVersionArtifacts: state.artifacts,
        };
      });
      return;
    }
  },

  setActiveArtifact: (id) =>
    set(() => ({
      activeArtifactId: id,
      userSelectedArtifactAt: Date.now(),
    })),

  setActiveArtifactView: (view) => set(() => ({ activeArtifactView: view })),

  setActiveCategory: (category) =>
    set((state) => {
      const matching =
        category === 'all'
          ? state.artifacts
          : state.artifacts.filter((artifact) => artifact.category === category);
      const nextActive = matching[matching.length - 1]?.id ?? state.activeArtifactId;
      return {
        activeCategory: category,
        activeArtifactId: nextActive,
        userSelectedArtifactAt: Date.now(),
      };
    }),

  setActiveWorkspaceTab: (tab) => set(() => ({ activeWorkspaceTab: tab })),

  setTarget: (target) => set(() => ({ target })),

  setError: (error) => set(() => ({ error })),

  setTheme: (theme) => {
    persistTheme(theme);
    set(() => ({ theme }));
  },

  toggleTheme: () => {
    const next: WorkbenchTheme = get().theme === 'dark' ? 'light' : 'dark';
    persistTheme(next);
    set(() => ({ theme: next }));
  },

  // Reset preserves the user's theme choice — it's a display preference,
  // not conversation state.
  reset: () =>
    set((state) => ({
      ...INITIAL_STATE,
      theme: state.theme,
    })),

  startIteration: (message) =>
    set((state) => {
      const nextIterationNumber = state.iterationCount + 1;
      const entry: IterationEntry = {
        id: `iter-local-${Date.now()}`,
        iterationNumber: nextIterationNumber,
        message,
        timestamp: Date.now(),
        artifactCount: state.artifacts.length,
      };
      return {
        buildStatus: 'starting' as BuildStatus,
        plan: null,
        artifacts: [],
        previousVersionArtifacts: state.artifacts,
        messages: [
          ...state.messages,
          {
            id: `msg-user-${Date.now()}`,
            role: 'user' as const,
            taskId: null,
            text: message,
            createdAt: Date.now(),
          },
        ],
        lastBrief: message,
        activeArtifactId: null,
        error: null,
        iterationCount: nextIterationNumber,
        iterationHistory: [...state.iterationHistory, entry],
      };
    }),

  selectVersionForDiff: (version) =>
    set(() => ({
      diffTargetVersion: version,
    })),
}));

function messageFromApi(message: WorkbenchMessage): AssistantMessage {
  return {
    id: message.id,
    role: message.role,
    taskId: message.task_id,
    text: message.text,
    createdAt: Date.parse(message.created_at) || Date.now(),
  };
}

function mergeRun(current: WorkbenchRun | null, data: Record<string, unknown>): WorkbenchRun | null {
  const runId = data.run_id as string | undefined;
  if (!runId) return current;
  return {
    ...(current ?? {
      run_id: runId,
      brief: '',
      target: 'portable',
      environment: 'draft',
      status: 'running',
      phase: 'plan',
      started_version: 0,
      completed_version: null,
      created_at: new Date().toISOString(),
      completed_at: null,
      error: null,
      events: [],
      messages: [],
      validation: null,
      presentation: null,
    }),
    run_id: runId,
    project_id: (data.project_id as string | undefined) ?? current?.project_id,
    status: (data.status as string | undefined) ?? current?.status ?? 'running',
    phase: (data.phase as string | undefined) ?? current?.phase ?? 'plan',
    validation: (data.validation as WorkbenchTestResult | undefined) ?? current?.validation ?? null,
    presentation: (data.presentation as WorkbenchPresentation | undefined) ?? current?.presentation ?? null,
  };
}

/** Deep-clone a plan tree. Keeps reducers pure without pulling in Immer. */
function cloneTree(task: PlanTask): PlanTask {
  return {
    ...task,
    artifact_ids: [...(task.artifact_ids ?? [])],
    log: [...(task.log ?? [])],
    children: (task.children ?? []).map(cloneTree),
  };
}

/** Flatten the plan tree to its leaves. Useful for progress counters. */
export function selectLeafCount(state: WorkbenchState): {
  total: number;
  done: number;
  running: number;
} {
  if (!state.plan) {
    return { total: 0, done: 0, running: 0 };
  }
  let total = 0;
  let done = 0;
  let running = 0;
  for (const task of walkTasks(state.plan)) {
    if (task.children && task.children.length > 0) continue;
    total += 1;
    if (task.status === 'done') done += 1;
    if (task.status === 'running') running += 1;
  }
  return { total, done, running };
}

/** Select the current artifact being previewed in the right pane. */
export function selectActiveArtifact(state: WorkbenchState): WorkbenchArtifact | null {
  if (!state.activeArtifactId) {
    return state.artifacts.length > 0 ? state.artifacts[state.artifacts.length - 1] : null;
  }
  return state.artifacts.find((a) => a.id === state.activeArtifactId) ?? null;
}

/** Filter artifacts by the active category tab. */
export function selectFilteredArtifacts(state: WorkbenchState): WorkbenchArtifact[] {
  if (state.activeCategory === 'all') return state.artifacts;
  return state.artifacts.filter((a) => a.category === state.activeCategory);
}
