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
  WorkbenchConversationMessage,
  WorkbenchTarget,
  WorkbenchTurnRecord,
  WorkbenchValidationCheck,
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
  /** Turn this message belongs to, for multi-turn grouping. */
  turnId?: string | null;
}

/** Multi-turn view state. Each turn owns its own plan and message list. */
export interface WorkbenchTurn {
  turnId: string;
  brief: string;
  mode: 'initial' | 'follow_up' | 'correction' | string;
  status: 'running' | 'completed' | 'error' | string;
  createdAt: number;
  plan: PlanTask | null;
  artifactIds: string[];
  iterationCount: number;
  validation?: {
    status?: string;
    checks?: WorkbenchValidationCheck[];
  } | null;
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

  // --- streaming build state (current turn's plan is the live one)
  buildStatus: BuildStatus;
  plan: PlanTask | null;
  artifacts: WorkbenchArtifact[];
  messages: AssistantMessage[];
  lastBrief: string;
  error: string | null;

  // --- multi-turn state
  turns: WorkbenchTurn[];
  activeTurnId: string | null;
  /** Count of autonomous iterations the current turn has run through. */
  currentIterationIndex: number;
  /** Validation output from the most recently completed iteration. */
  lastValidation: {
    status?: string;
    checks?: WorkbenchValidationCheck[];
    turnId?: string;
  } | null;
  /** Let the backend autonomously iterate on validation failures. */
  autoIterate: boolean;
  /** Hard cap on plan passes per turn (initial + corrections). */
  maxIterations: number;

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
    conversation?: WorkbenchConversationMessage[];
    turns?: WorkbenchTurnRecord[];
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
  setAutoIterate: (autoIterate: boolean) => void;
  setMaxIterations: (max: number) => void;
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
  turns: [],
  activeTurnId: null,
  currentIterationIndex: 0,
  lastValidation: null,
  autoIterate: true,
  maxIterations: 3,
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

  hydrate: (rawSnapshot) =>
    set((state) => {
      let snapshot = rawSnapshot;
      const messagesFromConversation: AssistantMessage[] = (
        snapshot.conversation ?? []
      )
        .filter((message) => (message.content ?? '').trim().length > 0)
        .map((message, index) => {
          const role = message.role === 'assistant' ? 'assist' : 'user';
          // Preserve deterministic ids so React key churn is minimal.
          const baseId = message.id ?? `msg-${role}-${index}`;
          const id =
            role === 'assist'
              ? `msg-assist-${baseId}`
              : `msg-user-${baseId}`;
          return {
            id,
            taskId: message.task_id ?? null,
            text: message.content,
            createdAt: Date.parse(message.created_at ?? '') || Date.now(),
            turnId: message.turn_id ?? null,
          };
        });

      const turns: WorkbenchTurn[] = (snapshot.turns ?? []).map((turn) => ({
        turnId: turn.turn_id,
        brief: turn.brief,
        mode: turn.mode,
        status: turn.status,
        createdAt: Date.parse(turn.created_at ?? '') || Date.now(),
        plan: turn.plan ?? null,
        artifactIds: turn.artifact_ids ?? [],
        iterationCount: turn.iterations?.length ?? 0,
        validation: turn.validation ?? null,
      }));

      // Legacy fallback: if the snapshot carries a plan but the backend
      // didn't give us explicit turn records (e.g. a project built before
      // multi-turn was wired up, or a unit-test harness passing only the
      // plan shape), synthesize a single turn so the feed renders without
      // special casing. Keeps the UI code multi-turn-only.
      if (turns.length === 0 && snapshot.plan) {
        const syntheticTurnId =
          (snapshot.plan as PlanTask).id ?? `turn-legacy-${Date.now()}`;
        turns.push({
          turnId: syntheticTurnId,
          brief: snapshot.lastBrief ?? state.lastBrief ?? '',
          mode: 'initial',
          status: 'completed',
          createdAt: Date.now(),
          plan: snapshot.plan,
          artifactIds: (snapshot.artifacts ?? []).map((a) => a.id),
          iterationCount: 1,
          validation: null,
        });
        // Stamp legacy artifacts with the synthetic turn id so they group
        // correctly under the synthesized turn block.
        if (snapshot.artifacts) {
          snapshot = {
            ...snapshot,
            artifacts: snapshot.artifacts.map((a) =>
              a.turn_id ? a : { ...a, turn_id: syntheticTurnId }
            ),
          };
        }
      }

      return {
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
        turns,
        activeTurnId: turns.length > 0 ? turns[turns.length - 1].turnId : null,
        messages:
          messagesFromConversation.length > 0
            ? messagesFromConversation
            : state.messages,
      };
    }),

  beginBuild: (brief) =>
    set((state) => ({
      buildStatus: 'starting',
      // Multi-turn: do NOT reset plan/artifacts/turns on a new turn. The
      // backend streams a turn.started event that seeds the new turn's plan
      // and we'll append to the existing artifact list, keeping prior turns
      // visible in the feed (Claude-Code/Manus style running log).
      plan: state.turns.length === 0 ? null : state.plan,
      artifacts: state.artifacts,
      messages: [
        ...state.messages,
        {
          id: `msg-user-${Date.now()}`,
          taskId: null,
          text: brief,
          createdAt: Date.now(),
          turnId: null,
        },
      ],
      lastBrief: brief,
      activeArtifactId: state.activeArtifactId,
      error: null,
      currentIterationIndex: 0,
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

    if (name === 'turn.started') {
      const turnId = String(data.turn_id ?? '');
      const mode = String(data.mode ?? 'initial');
      const brief = String(data.brief ?? '');
      set((state) => {
        // Record the new turn in the running log.
        const newTurn: WorkbenchTurn = {
          turnId,
          brief,
          mode,
          status: 'running',
          createdAt: Date.now(),
          plan: null,
          artifactIds: [],
          iterationCount: 0,
        };
        const nextTurns = [...state.turns, newTurn];
        // Tag the most recent user message with this turn id so the feed
        // renders it under the correct turn header.
        const nextMessages = [...state.messages];
        for (let i = nextMessages.length - 1; i >= 0; i -= 1) {
          const message = nextMessages[i];
          if (message.id.startsWith('msg-user-') && !message.turnId) {
            nextMessages[i] = { ...message, turnId };
            break;
          }
        }
        return {
          buildStatus: 'running',
          activeTurnId: turnId,
          turns: nextTurns,
          messages: nextMessages,
          projectId: (data.project_id as string) ?? state.projectId,
          currentIterationIndex: 0,
          error: null,
        };
      });
      return;
    }

    if (name === 'iteration.started') {
      const iterationIndex = Number(data.index ?? 0);
      set((state) => ({
        currentIterationIndex: iterationIndex,
        turns: state.turns.map((turn) =>
          turn.turnId === (data.turn_id as string)
            ? { ...turn, iterationCount: iterationIndex + 1 }
            : turn
        ),
      }));
      return;
    }

    if (name === 'validation.ready') {
      const turnId = String(data.turn_id ?? '');
      const status = String(data.status ?? '');
      const checks = (data.checks as WorkbenchValidationCheck[] | undefined) ?? [];
      set((state) => ({
        lastValidation: { status, checks, turnId },
        turns: state.turns.map((turn) =>
          turn.turnId === turnId
            ? { ...turn, validation: { status, checks } }
            : turn
        ),
      }));
      return;
    }

    if (name === 'turn.completed') {
      const turnId = String(data.turn_id ?? '');
      const status = String(data.status ?? 'completed');
      set((state) => ({
        buildStatus: status === 'error' ? 'error' : 'done',
        abortController: null,
        turns: state.turns.map((turn) =>
          turn.turnId === turnId
            ? {
                ...turn,
                status,
                iterationCount: Number(data.iterations ?? turn.iterationCount),
              }
            : turn
        ),
        version: (data.version as number) ?? state.version,
        projectId: (data.project_id as string) ?? state.projectId,
      }));
      return;
    }

    if (name === 'plan.ready') {
      const plan = data.plan as PlanTask;
      const turnId = data.turn_id as string | undefined;
      set((state) => ({
        plan,
        buildStatus: 'running',
        projectId: (data.project_id as string) ?? state.projectId,
        turns: turnId
          ? state.turns.map((turn) =>
              turn.turnId === turnId ? { ...turn, plan } : turn
            )
          : state.turns,
      }));
      return;
    }

    if (name === 'task.started') {
      const { task_id: taskId } = data as { task_id: string };
      const turnId = data.turn_id as string | undefined;
      set((state) => {
        if (!state.plan) return {};
        const nextPlan = cloneTree(state.plan);
        const task = findTaskById(nextPlan, taskId);
        if (task) {
          task.status = 'running' as PlanTaskStatus;
          task.started_at = new Date().toISOString();
        }
        recomputeParentStatus(nextPlan);
        return {
          plan: nextPlan,
          turns: turnId
            ? state.turns.map((turn) =>
                turn.turnId === turnId ? { ...turn, plan: nextPlan } : turn
              )
            : state.turns,
        };
      });
      return;
    }

    if (name === 'task.progress') {
      const { task_id: taskId, note } = data as { task_id: string; note: string };
      const turnId = data.turn_id as string | undefined;
      set((state) => {
        if (!state.plan) return {};
        const nextPlan = cloneTree(state.plan);
        const task = findTaskById(nextPlan, taskId);
        if (task && note) {
          task.log = [...(task.log ?? []), note];
        }
        return {
          plan: nextPlan,
          turns: turnId
            ? state.turns.map((turn) =>
                turn.turnId === turnId ? { ...turn, plan: nextPlan } : turn
              )
            : state.turns,
        };
      });
      return;
    }

    if (name === 'message.delta') {
      const { task_id: taskId, text } = data as { task_id: string | null; text: string };
      const turnId = (data.turn_id as string | undefined) ?? null;
      set((state) => {
        const messages = [...state.messages];
        const last = messages[messages.length - 1];
        const createdAt = Date.now();
        if (
          last &&
          last.taskId === taskId &&
          last.turnId === turnId &&
          last.id.startsWith('msg-assist-')
        ) {
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
            turnId,
          });
        }
        return { messages };
      });
      return;
    }

    if (name === 'artifact.updated') {
      const incoming = data.artifact as WorkbenchArtifact;
      const turnId =
        (data.turn_id as string | undefined) ?? incoming.turn_id ?? null;
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
          turns: turnId
            ? state.turns.map((turn) => {
                if (turn.turnId !== turnId) return turn;
                const artifactIds = (turn.artifactIds ?? []).includes(incoming.id)
                  ? turn.artifactIds
                  : [...(turn.artifactIds ?? []), incoming.id];
                return {
                  ...turn,
                  plan: nextPlan ?? turn.plan,
                  artifactIds,
                };
              })
            : state.turns,
        };
      });
      return;
    }

    if (name === 'task.completed') {
      const { task_id: taskId } = data as { task_id: string };
      const turnId = data.turn_id as string | undefined;
      set((state) => {
        if (!state.plan) return {};
        const nextPlan = cloneTree(state.plan);
        const task = findTaskById(nextPlan, taskId);
        if (task) {
          task.status = 'done' as PlanTaskStatus;
          task.completed_at = new Date().toISOString();
        }
        recomputeParentStatus(nextPlan);
        return {
          plan: nextPlan,
          turns: turnId
            ? state.turns.map((turn) =>
                turn.turnId === turnId ? { ...turn, plan: nextPlan } : turn
              )
            : state.turns,
        };
      });
      return;
    }

    if (name === 'build.completed') {
      // A single iteration finished. Multi-turn status transitions now live
      // in turn.completed; here we just acknowledge the pass ended.
      set((state) => ({
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

  setAutoIterate: (autoIterate) => set(() => ({ autoIterate })),

  setMaxIterations: (max) =>
    set(() => ({ maxIterations: Math.max(1, Math.min(6, Math.floor(max))) })),

  // Reset preserves the user's theme choice and autonomous-loop preferences
  // — those are display / agent-config preferences, not conversation state.
  reset: () =>
    set((state) => ({
      ...INITIAL_STATE,
      theme: state.theme,
      autoIterate: state.autoIterate,
      maxIterations: state.maxIterations,
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
