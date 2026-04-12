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
  WorkbenchHarnessState,
  IterationEntry,
  PlanTask,
  PlanTaskStatus,
  ReflectionEntry,
  WorkbenchArtifact,
  WorkbenchCanonicalModel,
  WorkbenchCompatibilityDiagnostic,
  WorkbenchConversationMessage,
  WorkbenchExports,
  WorkbenchMessage,
  WorkbenchPresentation,
  WorkbenchRun,
  WorkbenchTestResult,
  WorkbenchActivity,
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
  role: 'user' | 'assistant';
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
export type BuildStatus =
  | 'idle'
  | 'starting'
  | 'queued'
  | 'running'
  | 'reflecting'
  | 'presenting'
  | 'done'
  | 'error'
  | 'cancelled';

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
    conversation?: WorkbenchConversationMessage[];
    turns?: WorkbenchTurnRecord[];
    harnessState?: WorkbenchHarnessState | null;
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
  setAutoIterate: (autoIterate: boolean) => void;
  setMaxIterations: (max: number) => void;
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
  turns: [],
  activeTurnId: null,
  currentIterationIndex: 0,
  lastValidation: null,
  autoIterate: true,
  maxIterations: 3,
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

  hydrate: (rawSnapshot) =>
    set((state) => {
      let snapshot = rawSnapshot;

      // Build messages from the conversation log when available (master
      // multi-turn model), falling back to the API messages array (harness
      // run model) so both hydration paths work.
      const messagesFromConversation: AssistantMessage[] = (
        snapshot.conversation ?? []
      )
        .filter((message) => (message.content ?? '').trim().length > 0)
        .map((message, index) => {
          const role = message.role === 'assistant' ? 'assist' : 'user';
          const baseId = message.id ?? `msg-${role}-${index}`;
          const id =
            role === 'assist'
              ? `msg-assist-${baseId}`
              : `msg-user-${baseId}`;
          return {
            id,
            role: message.role === 'assistant' ? 'assistant' as const : 'user' as const,
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

      // Legacy fallback: synthesize a single turn from the plan so the
      // feed renders without special-casing (works for pre-multi-turn
      // projects and test harnesses that only pass a plan shape).
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
        if (snapshot.artifacts) {
          snapshot = {
            ...snapshot,
            artifacts: snapshot.artifacts.map((a) =>
              a.turn_id ? a : { ...a, turn_id: syntheticTurnId }
            ),
          };
        }
      }

      // Prefer conversation-derived messages, then API messages, then keep
      // whatever the store already had.
      const messages =
        messagesFromConversation.length > 0
          ? messagesFromConversation
          : snapshot.messages
            ? snapshot.messages.map(messageFromApi)
            : state.messages;
      const hydratedHarnessMetrics = harnessMetricsFromWire(
        snapshot.harnessState?.last_metrics,
        state.harnessMetrics
      );

      return {
        projectId: snapshot.projectId,
        projectName: snapshot.projectName ?? state.projectName,
        target: snapshot.target,
        environment: snapshot.environment ?? state.environment,
        version: snapshot.version,
        plan: snapshot.plan ?? null,
        artifacts: snapshot.artifacts ?? [],
        messages,
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
        harnessMetrics: hydratedHarnessMetrics,
        turns,
        activeTurnId: turns.length > 0 ? turns[turns.length - 1].turnId : null,
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
          role: 'user',
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
    set((state) => ({
      buildStatus: 'cancelled',
      abortController: null,
      error: state.activeRun?.cancel_reason ?? 'Run cancellation requested.',
    }));
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
          activeRun: mergeRun(state.activeRun, data),
          currentIterationIndex: 0,
          error: null,
        };
      });
      return;
    }

    if (name === 'iteration.started') {
      const iterationIndex = Number(data.index ?? 0);
      const incoming = data as {
        id?: string;
        message?: string;
        artifact_count?: number;
        timestamp?: number;
        iteration_number?: number;
      };
      set((state) => {
        // Guard against double-counting from optimistic startIteration()
        const lastEntry = state.iterationHistory[state.iterationHistory.length - 1];
        const alreadyCounted = lastEntry && lastEntry.id.startsWith('iter-local-');
        const nextIterationNumber = alreadyCounted
          ? state.iterationCount
          : state.iterationCount + 1;
        const newEntry: IterationEntry | null = alreadyCounted
          ? null
          : {
              id: incoming.id ?? `iter-${Date.now()}`,
              iterationNumber: nextIterationNumber,
              message: incoming.message ?? '',
              timestamp: incoming.timestamp ?? Date.now(),
              artifactCount: incoming.artifact_count ?? state.artifacts.length,
            };
        return {
          currentIterationIndex: iterationIndex,
          iterationCount: nextIterationNumber,
          iterationHistory: newEntry
            ? [...state.iterationHistory, newEntry]
            : state.iterationHistory,
          previousVersionArtifacts: alreadyCounted
            ? state.previousVersionArtifacts
            : state.artifacts,
          activeRun: mergeRun(state.activeRun, data),
          turns: state.turns.map((turn) =>
            turn.turnId === (data.turn_id as string)
              ? { ...turn, iterationCount: iterationIndex + 1 }
              : turn
          ),
        };
      });
      return;
    }

    if (name === 'validation.ready') {
      const turnId = String(data.turn_id ?? '');
      const status = String(data.status ?? '');
      const checks = (data.checks as WorkbenchValidationCheck[] | undefined) ?? [];
      set((state) => ({
        lastValidation: { status, checks, turnId },
        activeRun: mergeRun(state.activeRun, data),
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
        buildStatus:
          status === 'failed' || status === 'error'
            ? 'error'
            : status === 'cancelled'
              ? 'cancelled'
              : state.buildStatus === 'running' ||
                  state.buildStatus === 'reflecting' ||
                  state.buildStatus === 'presenting'
                ? state.buildStatus
                : 'done',
        abortController: null,
        activeRun: mergeRun(state.activeRun, data),
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
        activeRun: mergeRun(state.activeRun, data),
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
            role: 'assistant',
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
        buildStatus: 'running',
        projectId: (data.project_id as string) ?? state.projectId,
        version: (data.version as number) ?? state.version,
        activeRun: mergeRun(state.activeRun, data),
      }));
      return;
    }

    if (name === 'reflect.started') {
      set((state) => ({
        buildStatus: 'reflecting',
        activeRun: mergeRun(state.activeRun, data),
      }));
      return;
    }

    if (name === 'reflect.completed') {
      const validation = data.validation as WorkbenchTestResult | undefined;
      set((state) => ({
        buildStatus: validation?.status === 'failed' ? 'error' : 'reflecting',
        lastTest: validation ?? state.lastTest,
        activeRun: mergeRun(state.activeRun, data),
      }));
      return;
    }

    if (name === 'present.ready') {
      const presentation = data.presentation as WorkbenchPresentation | undefined;
      set((state) => ({
        buildStatus: 'presenting',
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
        artifacts: WorkbenchArtifact[];
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
        artifacts: project?.artifacts ?? state.artifacts,
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
        activeRun: mergeRun(run ?? state.activeRun, data),
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
        activeRun: mergeRun(run ?? state.activeRun, data),
        error: String((data as { error?: string; message?: string }).error ?? (data as { message?: string }).message ?? 'Build failed.'),
      }));
      return;
    }

    if (name === 'run.cancel_requested') {
      set((state) => ({
        activeRun: mergeRun(state.activeRun, data),
        error: String((data as { cancel_reason?: string }).cancel_reason ?? 'Run cancellation requested.'),
      }));
      return;
    }

    if (name === 'run.cancelled') {
      const run = data.run as WorkbenchRun | undefined;
      const reason = String((data as { cancel_reason?: string }).cancel_reason ?? run?.cancel_reason ?? 'Run cancelled.');
      set((state) => ({
        buildStatus: 'cancelled',
        abortController: null,
        activeRun: mergeRun(run ?? state.activeRun, data),
        error: reason,
      }));
      return;
    }

    if (name === 'run.recovered') {
      set((state) => ({
        buildStatus: 'error',
        abortController: null,
        activeRun: mergeRun(state.activeRun, data),
        error: String((data as { message?: string }).message ?? 'Run recovered from an interrupted state.'),
      }));
      return;
    }

    if (name === 'error') {
      set((state) => ({
        buildStatus: 'error',
        abortController: null,
        activeRun: mergeRun(state.activeRun, data),
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
        harnessMetrics: harnessMetricsFromWire(incoming, state.harnessMetrics),
        activeRun: mergeRunBudgetFromMetrics(mergeRun(state.activeRun, data), incoming),
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
        artifacts: state.artifacts,
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
        activeArtifactId: state.activeArtifactId,
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

type HarnessMetricsWire = NonNullable<WorkbenchHarnessState['last_metrics']>;

function harnessMetricsFromWire(
  incoming: HarnessMetricsWire | null | undefined,
  current: HarnessMetrics | null
): HarnessMetrics | null {
  if (!incoming) return current;
  return {
    stepsCompleted: incoming.steps_completed ?? current?.stepsCompleted ?? 0,
    totalSteps: incoming.total_steps ?? current?.totalSteps ?? 0,
    tokensUsed: incoming.tokens_used ?? current?.tokensUsed ?? 0,
    costUsd: incoming.cost_usd ?? current?.costUsd ?? 0,
    elapsedMs: incoming.elapsed_ms ?? current?.elapsedMs ?? 0,
    currentPhase: incoming.current_phase ?? current?.currentPhase ?? 'idle',
  };
}

function mergeRun(current: WorkbenchRun | null, data: Record<string, unknown>): WorkbenchRun | null {
  const runId = data.run_id as string | undefined;
  if (!runId) return current;
  const incomingRun = data.run as WorkbenchRun | undefined;
  const budget = data.budget ?? incomingRun?.budget ?? current?.budget;
  const telemetrySummary =
    data.telemetry_summary ?? incomingRun?.telemetry_summary ?? current?.telemetry_summary;
  const handoff = data.handoff ?? incomingRun?.handoff ?? current?.handoff ?? null;
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
    ...(incomingRun ?? {}),
    run_id: runId,
    project_id: (data.project_id as string | undefined) ?? incomingRun?.project_id ?? current?.project_id,
    status: (data.status as string | undefined) ?? incomingRun?.status ?? current?.status ?? 'running',
    phase: (data.phase as string | undefined) ?? incomingRun?.phase ?? current?.phase ?? 'plan',
    execution_mode:
      (data.execution_mode as string | undefined) ?? incomingRun?.execution_mode ?? current?.execution_mode,
    provider: (data.provider as string | undefined) ?? incomingRun?.provider ?? current?.provider,
    model: (data.model as string | undefined) ?? incomingRun?.model ?? current?.model,
    mode_reason:
      (data.mode_reason as string | undefined) ?? incomingRun?.mode_reason ?? current?.mode_reason,
    budget: budget as WorkbenchRun['budget'],
    telemetry_summary: telemetrySummary as WorkbenchRun['telemetry_summary'],
    failure_reason:
      (data.failure_reason as string | null | undefined) ??
      incomingRun?.failure_reason ??
      current?.failure_reason ??
      null,
    cancel_reason:
      (data.cancel_reason as string | null | undefined) ??
      incomingRun?.cancel_reason ??
      current?.cancel_reason ??
      null,
    review_gate:
      (data.review_gate as WorkbenchRun['review_gate'] | undefined) ??
      incomingRun?.review_gate ??
      current?.review_gate ??
      null,
    handoff: handoff as WorkbenchRun['handoff'],
    validation:
      (data.validation as WorkbenchTestResult | undefined) ??
      incomingRun?.validation ??
      current?.validation ??
      null,
    presentation:
      (data.presentation as WorkbenchPresentation | undefined) ??
      incomingRun?.presentation ??
      current?.presentation ??
      null,
  };
}

function mergeRunBudgetFromMetrics(
  run: WorkbenchRun | null,
  metrics: {
    tokens_used?: number;
    cost_usd?: number;
    elapsed_ms?: number;
  }
): WorkbenchRun | null {
  if (!run?.budget) return run;
  const usage = {
    ...(run.budget.usage ?? {}),
    tokens:
      metrics.tokens_used ??
      run.budget.usage?.tokens ??
      run.budget.usage?.tokens_used ??
      0,
    tokens_used:
      metrics.tokens_used ??
      run.budget.usage?.tokens_used ??
      run.budget.usage?.tokens ??
      0,
    cost_usd: metrics.cost_usd ?? run.budget.usage?.cost_usd ?? 0,
    elapsed_ms: metrics.elapsed_ms ?? run.budget.usage?.elapsed_ms ?? 0,
  };
  return {
    ...run,
    budget: {
      ...run.budget,
      usage,
    },
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
