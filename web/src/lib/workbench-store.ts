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
  PlanTask,
  PlanTaskStatus,
  WorkbenchArtifact,
  WorkbenchCanonicalModel,
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
  taskId: string | null;
  text: string;
  createdAt: number;
}

/** Active artifact view mode on the right pane. */
export type ArtifactView = 'preview' | 'source';

/** Category filter for the artifact tab bar in the right pane. */
export type ArtifactCategoryFilter =
  | 'all'
  | 'agent'
  | 'tool'
  | 'guardrail'
  | 'eval'
  | 'environment';

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
  userSelectedArtifactAt: number;

  // --- canonical model snapshot for the right-pane "agent" tab
  canonicalModel: WorkbenchCanonicalModel | null;

  // --- abort controller for the in-flight stream
  abortController: AbortController | null;
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
    canonicalModel?: WorkbenchCanonicalModel | null;
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
  setTarget: (target: WorkbenchTarget) => void;
  setError: (error: string | null) => void;
  setTheme: (theme: WorkbenchTheme) => void;
  toggleTheme: () => void;
  reset: () => void;
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
  userSelectedArtifactAt: 0,
  canonicalModel: null,
  abortController: null,
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
      canonicalModel: snapshot.canonicalModel ?? null,
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
        buildStatus: 'done',
        abortController: null,
        projectId: (data.project_id as string) ?? state.projectId,
        version: (data.version as number) ?? state.version,
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
  },

  setActiveArtifact: (id) =>
    set(() => ({
      activeArtifactId: id,
      userSelectedArtifactAt: Date.now(),
    })),

  setActiveArtifactView: (view) => set(() => ({ activeArtifactView: view })),

  setActiveCategory: (category) => set(() => ({ activeCategory: category })),

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
}));

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
