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
  streamWorkbenchBuild,
  type WorkbenchTarget,
} from '../lib/workbench-api';
import { useWorkbenchStore } from '../lib/workbench-store';
import { WorkbenchLayout } from '../components/workbench/WorkbenchLayout';
import { ConversationFeed } from '../components/workbench/ConversationFeed';
import { ArtifactViewer } from '../components/workbench/ArtifactViewer';
import { ChatInput } from '../components/workbench/ChatInput';

export function AgentWorkbench() {
  const projectId = useWorkbenchStore((s) => s.projectId);
  const hydrate = useWorkbenchStore((s) => s.hydrate);
  const beginBuild = useWorkbenchStore((s) => s.beginBuild);
  const dispatchEvent = useWorkbenchStore((s) => s.dispatchEvent);
  const setAbortController = useWorkbenchStore((s) => s.setAbortController);
  const target = useWorkbenchStore((s) => s.target);
  const setError = useWorkbenchStore((s) => s.setError);
  const reset = useWorkbenchStore((s) => s.reset);

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
          canonicalModel: snapshot.model ?? null,
          buildStatus:
            snapshot.build_status === 'running'
              ? 'running'
              : snapshot.build_status === 'error'
                ? 'error'
                : 'idle',
          lastBrief: snapshot.last_brief,
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
          },
          { signal: controller.signal }
        );
        for await (const event of stream) {
          dispatchEvent(event);
        }
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
    [beginBuild, dispatchEvent, projectId, setAbortController, setError, target]
  );

  return (
    <div className="px-4 pb-6 pt-2">
      <WorkbenchLayout
        left={<ConversationFeed />}
        right={<ArtifactViewer />}
        footer={<ChatInput onSubmit={handleSubmit} />}
      />
    </div>
  );
}

export default AgentWorkbench;
