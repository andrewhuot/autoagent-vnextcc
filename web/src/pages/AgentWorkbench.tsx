/**
 * Agent Builder Workbench — dark, Manus-style two-pane shell.
 *
 * Left pane: conversation feed (user message → live plan tree → assistant
 * narration → artifact cards → running-task spinner) plus a chat input at
 * the bottom. Right pane: a single active artifact with a Preview / Source
 * code toggle and a category tab bar.
 *
 * Data flow:
 *   1. On mount we hydrate the page from /api/workbench/projects/default
 *      (seed a starter project if none exist yet) and a follow-up
 *      /api/workbench/projects/{id}/plan for any live plan state.
 *   2. When the user submits a brief, we start streaming
 *      /api/workbench/build/stream and dispatch every SSE event into the
 *      Zustand store. The components re-render as events arrive.
 *   3. ⌘K focuses the input, ⌘↵ (or Enter) sends.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import {
  cancelWorkbenchRun,
  createWorkbenchEvalBridge,
  getDefaultWorkbenchProject,
  getWorkbenchPlanSnapshot,
  iterateWorkbenchBuild,
  streamWorkbenchBuild,
  type RunSummary,
  type WorkbenchCanonicalModel,
  type WorkbenchImprovementBridge,
  type WorkbenchTestResult,
  type WorkbenchTarget,
} from '../lib/workbench-api';
import { useWorkbenchStore, type BuildStatus } from '../lib/workbench-store';
import { WorkbenchLayout } from '../components/workbench/WorkbenchLayout';
import { ConversationFeed } from '../components/workbench/ConversationFeed';
import { ArtifactViewer } from '../components/workbench/ArtifactViewer';
import { ChatInput } from '../components/workbench/ChatInput';
import { IterationControls } from '../components/workbench/IterationControls';
import { toastError } from '../lib/toast';
import { OperatorNextStepCard } from '../components/OperatorNextStepCard';
import { createJourneyStatusSummary } from '../lib/operator-journey';
import { statusLabel } from '../lib/utils';

function mapWorkbenchBuildStatus(status: string | undefined): BuildStatus {
  switch (status) {
    case 'queued':
      return 'queued';
    case 'running':
      return 'running';
    case 'reflecting':
      return 'reflecting';
    case 'presenting':
      return 'presenting';
    case 'completed':
      return 'done';
    case 'cancelled':
      return 'cancelled';
    case 'interrupted':
      return 'interrupted';
    case 'error':
    case 'failed':
      return 'error';
    default:
      return 'idle';
  }
}

/** Derive Workbench readiness from the persisted build/test evidence already loaded by the page. */
function getWorkbenchJourneySummary(input: {
  buildStatus: BuildStatus;
  canonicalModel: WorkbenchCanonicalModel | null;
  lastTest: WorkbenchTestResult | null;
  runSummary: RunSummary | null;
}) {
  const hasCandidate = Boolean(input.canonicalModel?.agents?.length);
  const runCompleted = input.runSummary?.status === 'completed';
  const validationPassed = input.lastTest?.status === 'passed';
  const isReadyForEval = hasCandidate && (input.buildStatus === 'done' || runCompleted || validationPassed);

  if (isReadyForEval) {
    return createJourneyStatusSummary({
      currentStep: 'workbench',
      status: 'ready',
      statusLabel: statusLabel('ready'),
      summary: 'The Workbench candidate has build evidence. Run Eval before sending it into Optimize.',
      nextLabel: 'Run eval',
      nextDescription: 'Open Eval Runs and launch the first evaluation for this candidate.',
      href: '/evals?new=1',
    });
  }

  return createJourneyStatusSummary({
    currentStep: 'workbench',
    status: hasCandidate ? 'waiting' : 'blocked',
    statusLabel: hasCandidate ? 'Needs validation' : 'Candidate needed',
    summary: hasCandidate
      ? 'Finish validation or presentation in Workbench before Eval.'
      : 'Describe the agent in Workbench so a candidate can be materialized first.',
    nextLabel: 'Build candidate',
    nextDescription: 'Use the Workbench prompt to create a candidate with artifacts and validation evidence.',
  });
}

export function AgentWorkbench() {
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const projectId = useWorkbenchStore((s) => s.projectId);
  const hydrate = useWorkbenchStore((s) => s.hydrate);
  const beginBuild = useWorkbenchStore((s) => s.beginBuild);
  const startIteration = useWorkbenchStore((s) => s.startIteration);
  const dispatchEvent = useWorkbenchStore((s) => s.dispatchEvent);
  const setAbortController = useWorkbenchStore((s) => s.setAbortController);
  const target = useWorkbenchStore((s) => s.target);
  const environment = useWorkbenchStore((s) => s.environment);
  const setError = useWorkbenchStore((s) => s.setError);
  const reset = useWorkbenchStore((s) => s.reset);
  const autoIterate = useWorkbenchStore((s) => s.autoIterate);
  const maxIterations = useWorkbenchStore((s) => s.maxIterations);
  const presentation = useWorkbenchStore((s) => s.presentation);
  const activeRun = useWorkbenchStore((s) => s.activeRun);
  const bridge = presentation?.improvement_bridge ?? activeRun?.presentation?.improvement_bridge ?? null;
  const [evalHandoffPending, setEvalHandoffPending] = useState(false);
  const [hydrated, setHydrated] = useState(false);
  const buildHandoffStartedRef = useRef(false);
  const buildStatus = useWorkbenchStore((s) => s.buildStatus);
  const canonicalModel = useWorkbenchStore((s) => s.canonicalModel);
  const lastTest = useWorkbenchStore((s) => s.lastTest);
  const runSummary = useWorkbenchStore((s) => s.runSummary);
  const journeySummary = getWorkbenchJourneySummary({
    buildStatus,
    canonicalModel,
    lastTest,
    runSummary,
  });
  const buildHandoff = useMemo(() => {
    const state = (location.state as {
      source?: string;
      agent?: { name?: string; config_path?: string };
      configPath?: string;
      brief?: string;
    } | null) ?? null;
    const agentName = state?.agent?.name ?? searchParams.get('agentName') ?? '';
    const configPath = state?.configPath ?? state?.agent?.config_path ?? searchParams.get('configPath') ?? '';
    const cameFromBuild = state?.source === 'build' || Boolean(searchParams.get('agent'));
    const brief =
      state?.brief ??
      (agentName
        ? `Continue building ${agentName}${configPath ? ` from the saved Build config at ${configPath}` : ''}.`
        : '');
    if (!cameFromBuild || !brief) {
      return null;
    }
    return {
      agentName: agentName || 'Build candidate',
      configPath,
      brief,
    };
  }, [location.state, searchParams]);

  // Track the active stream controller so we can abort on unmount.
  const activeControllerRef = useRef<AbortController | null>(null);

  // --- hydrate on mount ---------------------------------------------------
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const payload = await getDefaultWorkbenchProject();
        if (cancelled) return;
        hydrate({
          projectId: payload.project.project_id,
          projectName: payload.project.name,
          target: payload.project.target,
          environment: payload.project.environment,
          version: payload.project.version,
          canonicalModel: payload.project.model,
          exports: payload.project.exports,
          compatibility: payload.project.compatibility,
          lastTest: payload.project.last_test,
          activity: payload.project.activity,
          activeRun: payload.project.active_run ?? null,
          messages: payload.project.messages ?? [],
        });
        // Follow-up: load any persisted plan snapshot for this project.
        const snapshot = await getWorkbenchPlanSnapshot(payload.project.project_id);
        if (cancelled) return;
        hydrate({
          projectId: snapshot.project_id,
          projectName: snapshot.name,
          target: snapshot.target as WorkbenchTarget,
          environment: snapshot.environment,
          version: snapshot.version,
          plan: snapshot.plan,
          artifacts: snapshot.artifacts ?? [],
          messages: snapshot.messages ?? [],
          canonicalModel: snapshot.model ?? null,
          exports: snapshot.exports ?? null,
          compatibility: snapshot.compatibility ?? [],
          lastTest: snapshot.last_test ?? null,
          activity: snapshot.activity ?? [],
          activeRun: snapshot.active_run ?? null,
          buildStatus: mapWorkbenchBuildStatus(snapshot.build_status),
          lastBrief: snapshot.last_brief,
          // Multi-turn hydration: repopulate conversation + turn tree so a
          // page reload restores the running log exactly where it stopped.
          conversation: snapshot.conversation,
          turns: snapshot.turns,
          harnessState: snapshot.harness_state,
          runSummary: snapshot.run_summary,
        });
        setHydrated(true);
      } catch (error) {
        if (cancelled) return;
        setError(error instanceof Error ? error.message : 'Workbench failed to load');
        setHydrated(true);
      }
    })();
    return () => {
      cancelled = true;
      activeControllerRef.current?.abort();
      reset();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // --- keyboard shortcuts --------------------------------------------------
  //   ⌘K focuses the chat input
  //   ⌘← / ⌘→ cycle through the artifacts in the right pane
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      const meta = event.metaKey || event.ctrlKey;
      if (meta && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        const textarea = document.querySelector<HTMLTextAreaElement>(
          '[aria-label="Build request"]'
        );
        textarea?.focus();
        return;
      }
      if (meta && (event.key === 'ArrowLeft' || event.key === 'ArrowRight')) {
        const state = useWorkbenchStore.getState();
        if (state.artifacts.length < 2) return;
        event.preventDefault();
        const currentIndex = state.artifacts.findIndex(
          (a) => a.id === state.activeArtifactId
        );
        const safeIndex = currentIndex === -1 ? 0 : currentIndex;
        const nextIndex =
          event.key === 'ArrowRight'
            ? (safeIndex + 1) % state.artifacts.length
            : (safeIndex - 1 + state.artifacts.length) % state.artifacts.length;
        state.setActiveArtifact(state.artifacts[nextIndex].id);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  // ---------------------------------------------------------------------------
  // Stream consumer — shared between fresh builds and iterations
  // ---------------------------------------------------------------------------
  const consumeStream = useCallback(
    async (stream: AsyncIterable<import('../lib/workbench-api').BuildStreamEvent>) => {
      for await (const event of stream) {
        dispatchEvent(event);
      }
    },
    [dispatchEvent]
  );

  // ---------------------------------------------------------------------------
  // Fresh build handler
  // ---------------------------------------------------------------------------
  const handleSubmit = useCallback(
    async (brief: string, options?: { startFreshProject?: boolean }) => {
      beginBuild(brief);
      const controller = new AbortController();
      activeControllerRef.current?.abort();
      activeControllerRef.current = controller;
      setAbortController(controller);
      try {
        const stream = streamWorkbenchBuild(
          {
            project_id: options?.startFreshProject ? null : projectId ?? null,
            brief,
            target,
            environment,
            auto_iterate: autoIterate,
            max_iterations: maxIterations,
          },
          { signal: controller.signal }
        );
        await consumeStream(stream);
      } catch (error) {
        if ((error as Error).name === 'AbortError') return;
        setError(error instanceof Error ? error.message : 'Build failed');
      } finally {
        if (activeControllerRef.current === controller) {
          activeControllerRef.current = null;
          setAbortController(null);
        }
      }
    },
    [autoIterate, beginBuild, consumeStream, environment, maxIterations, projectId, setAbortController, setError, target]
  );

  useEffect(() => {
    if (!buildHandoff?.brief || buildHandoffStartedRef.current || !hydrated || !projectId || buildStatus !== 'idle') {
      return;
    }
    buildHandoffStartedRef.current = true;
    void handleSubmit(buildHandoff.brief, { startFreshProject: true });
  }, [buildHandoff?.brief, buildStatus, handleSubmit, hydrated, projectId]);

  // ---------------------------------------------------------------------------
  // Iteration handler — called by IterationControls and ReflectionCard
  // ---------------------------------------------------------------------------
  const handleIterate = useCallback(
    async (message: string) => {
      const currentProjectId = useWorkbenchStore.getState().projectId;
      if (!currentProjectId) {
        await handleSubmit(message);
        return;
      }

      startIteration(message);
      const controller = new AbortController();
      activeControllerRef.current?.abort();
      activeControllerRef.current = controller;
      setAbortController(controller);
      try {
        const stream = iterateWorkbenchBuild(
          {
            project_id: currentProjectId,
            message,
            target,
            environment,
            max_iterations: maxIterations,
          },
          { signal: controller.signal }
        );
        await consumeStream(stream);
      } catch (error) {
        if ((error as Error).name === 'AbortError') return;
        setError(error instanceof Error ? error.message : 'Iteration failed');
      } finally {
        if (activeControllerRef.current === controller) {
          activeControllerRef.current = null;
          setAbortController(null);
        }
      }
    },
    [consumeStream, environment, handleSubmit, maxIterations, setAbortController, setError, startIteration, target]
  );

  const handleCancel = useCallback(async () => {
    const state = useWorkbenchStore.getState();
    const runId = state.activeRun?.run_id;
    const currentProjectId = state.projectId;
    if (runId) {
      try {
        const payload = await cancelWorkbenchRun(
          runId,
          'Cancelled by operator.',
          currentProjectId
        );
        dispatchEvent({ event: 'run.cancelled', data: payload as Record<string, unknown> });
      } catch (error) {
        setError(error instanceof Error ? error.message : 'Run cancellation failed');
      }
    }
    activeControllerRef.current?.abort();
    state.cancelBuild();
  }, [dispatchEvent, setError]);

  const handleOpenEval = useCallback(async () => {
    const currentProjectId = useWorkbenchStore.getState().projectId;
    if (!currentProjectId) {
      toastError('Workbench candidate not ready', 'Run or reload the Workbench before opening Eval.');
      return;
    }

    setEvalHandoffPending(true);
    try {
      const payload = await createWorkbenchEvalBridge(currentProjectId);
      const materializedBridge = payload.bridge;
      const configPath =
        materializedBridge.evaluation.request?.config_path ??
        materializedBridge.candidate.config_path ??
        payload.save_result.config_path;
      if (!configPath) {
        throw new Error('The Workbench candidate did not return a saved config path.');
      }

      const candidate = materializedBridge.candidate;
      const params = new URLSearchParams({
        source: 'workbench',
        new: '1',
        projectId: candidate.project_id,
        runId: candidate.run_id,
        configPath,
      });
      if (candidate.agent_name) {
        params.set('agentName', candidate.agent_name);
      }
      if (materializedBridge.evaluation.request?.generated_suite_id) {
        params.set('generatedSuiteId', materializedBridge.evaluation.request.generated_suite_id);
      }
      if (materializedBridge.evaluation.request?.split) {
        params.set('split', materializedBridge.evaluation.request.split);
      }

      navigate(`/evals?${params.toString()}`, {
        state: {
          source: 'workbench',
          open: 'run',
          workbenchBridge: materializedBridge,
          agent: {
            id: `workbench-${candidate.project_id}-v${candidate.version}`,
            name: candidate.agent_name || 'Workbench Agent',
            model: 'workbench',
            created_at: new Date().toISOString(),
            source: 'built',
            config_path: configPath,
            status: 'candidate',
          },
        },
      });
    } catch (error) {
      toastError(
        'Eval handoff failed',
        error instanceof Error ? error.message : 'Workbench could not materialize this candidate for Eval.'
      );
    } finally {
      setEvalHandoffPending(false);
    }
  }, [navigate]);

  return (
    <div className="space-y-4 px-4 pb-6 pt-2">
      {buildHandoff ? <BuildHandoffPanel handoff={buildHandoff} /> : null}
      <OperatorNextStepCard summary={journeySummary} />
      <WorkbenchEvalHandoffPanel
        bridge={bridge}
        isPending={evalHandoffPending}
        onOpenEval={handleOpenEval}
      />
      <WorkbenchLayout
        left={<ConversationFeed onApplySuggestion={handleIterate} />}
        right={<ArtifactViewer />}
        footer={<ChatInput onSubmit={handleSubmit} onCancel={handleCancel} />}
        iterationControls={<IterationControls onIterate={handleIterate} />}
      />
    </div>
  );
}

export default AgentWorkbench;

function BuildHandoffPanel({
  handoff,
}: {
  handoff: {
    agentName: string;
    configPath: string;
    brief: string;
  };
}) {
  return (
    <section className="rounded-md border border-[color:var(--wb-border)] bg-[color:var(--wb-bg-elev)] px-4 py-3 text-[color:var(--wb-text)]">
      <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0">
          <p className="text-[12px] font-semibold">Continuing from Build</p>
          <p className="mt-1 text-[12px] leading-5 text-[color:var(--wb-text-soft)]">
            {handoff.agentName} is being materialized as a fresh Workbench candidate.
          </p>
          {handoff.configPath ? (
            <p className="mt-1 break-all font-mono text-[11px] text-[color:var(--wb-text-dim)]">
              {handoff.configPath}
            </p>
          ) : null}
        </div>
        <p className="max-w-xl text-[11px] leading-5 text-[color:var(--wb-text-dim)]">
          {handoff.brief}
        </p>
      </div>
    </section>
  );
}

function WorkbenchEvalHandoffPanel({
  bridge,
  isPending,
  onOpenEval,
}: {
  bridge: WorkbenchImprovementBridge | null;
  isPending: boolean;
  onOpenEval: () => void;
}) {
  if (!bridge) {
    return null;
  }

  const evaluation = bridge.evaluation;
  const isBlocked = evaluation.status === 'blocked';
  const actionLabel =
    evaluation.primary_action_label ??
    (evaluation.status === 'needs_saved_config'
      ? 'Save candidate and open Eval'
      : 'Open Eval with this candidate');
  const blockedActionLabel =
    evaluation.readiness_state === 'draft_only' ? 'Finish Workbench run first' : 'Resolve blockers first';
  const description =
    evaluation.description ??
    (evaluation.status === 'ready'
      ? 'The Workbench candidate is ready to evaluate.'
      : 'Save the Workbench candidate, then run Eval on that exact config.');

  return (
    <section className="mb-3 rounded-md border border-[color:var(--wb-border)] bg-[color:var(--wb-bg-elev)] px-4 py-3 text-[color:var(--wb-text)]">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0">
          <p className="text-[12px] font-semibold text-[color:var(--wb-text)]">
            {evaluation.label ?? 'Workbench candidate for Eval'}
          </p>
          <p className="mt-1 text-[12px] leading-5 text-[color:var(--wb-text-soft)]">
            {description}
          </p>
          {bridge.candidate.config_path ? (
            <p className="mt-1 break-all font-mono text-[11px] text-[color:var(--wb-text-dim)]">
              {bridge.candidate.config_path}
            </p>
          ) : null}
          {evaluation.blocking_reasons.length > 0 ? (
            <ul className="mt-2 space-y-1 text-[12px] text-[color:var(--wb-text-dim)]">
              {evaluation.blocking_reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          ) : null}
        </div>
        <button
          type="button"
          onClick={onOpenEval}
          disabled={isBlocked || isPending}
          className="inline-flex items-center justify-center rounded-md bg-[color:var(--wb-text)] px-3 py-2 text-[12px] font-medium text-[color:var(--wb-bg)] transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {isPending ? 'Opening Eval...' : isBlocked ? blockedActionLabel : actionLabel}
        </button>
      </div>
    </section>
  );
}
