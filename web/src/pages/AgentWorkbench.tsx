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

import { useCallback, useEffect, useRef } from 'react';
import {
  getDefaultWorkbenchProject,
  getWorkbenchPlanSnapshot,
  iterateWorkbenchBuild,
  streamWorkbenchBuild,
  type WorkbenchTarget,
} from '../lib/workbench-api';
import { useWorkbenchStore } from '../lib/workbench-store';
import { WorkbenchLayout } from '../components/workbench/WorkbenchLayout';
import { ConversationFeed } from '../components/workbench/ConversationFeed';
import { ArtifactViewer } from '../components/workbench/ArtifactViewer';
import { ChatInput } from '../components/workbench/ChatInput';
import { IterationControls } from '../components/workbench/IterationControls';

export function AgentWorkbench() {
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
          buildStatus:
            snapshot.build_status === 'running'
              || snapshot.build_status === 'reflecting'
              ? 'running'
              : snapshot.build_status === 'completed'
                ? 'done'
                : snapshot.build_status === 'error' || snapshot.build_status === 'failed'
                ? 'error'
                : 'idle',
          lastBrief: snapshot.last_brief,
          // Multi-turn hydration: repopulate conversation + turn tree so a
          // page reload restores the running log exactly where it stopped.
          conversation: snapshot.conversation,
          turns: snapshot.turns,
        });
      } catch (error) {
        if (cancelled) return;
        setError(error instanceof Error ? error.message : 'Workbench failed to load');
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
    async (brief: string) => {
      beginBuild(brief);
      const controller = new AbortController();
      activeControllerRef.current?.abort();
      activeControllerRef.current = controller;
      setAbortController(controller);
      try {
        const stream = streamWorkbenchBuild(
          {
            project_id: projectId ?? null,
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
    [consumeStream, handleSubmit, setAbortController, setError, startIteration, target]
  );

  return (
    <div className="px-4 pb-6 pt-2">
      <WorkbenchLayout
        left={<ConversationFeed onApplySuggestion={handleIterate} />}
        right={<ArtifactViewer />}
        footer={<ChatInput onSubmit={handleSubmit} />}
        iterationControls={<IterationControls onIterate={handleIterate} />}
      />
    </div>
  );
}

export default AgentWorkbench;
