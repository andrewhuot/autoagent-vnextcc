import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  AlertTriangle,
  ArrowRight,
  Bot,
  CheckCircle2,
  Copy,
  Download,
  Play,
  RotateCcw,
  RotateCw,
  Send,
  Sparkles,
  X,
} from 'lucide-react';
import { useSaveAgent } from '../lib/api';
import { useActiveAgent } from '../lib/active-agent';
import {
  exportBuilderConfig,
  getBuilderSession,
  previewBuilderSession,
  sendBuilderMessage,
  type BuilderConfig,
  type BuilderSessionPayload,
} from '../lib/builder-chat-api';
import {
  buildCheckpointHistory,
  buildLocalDraftFilename,
  clearPersistedAgentImproverState,
  formatCountLabel,
  latestUserRequestFromSession,
  readPersistedAgentImproverState,
  serializeBuilderConfigToYaml,
  writePersistedAgentImproverState,
  type AgentImproverCheckpoint,
} from '../lib/agent-improver';
import { toastError, toastSuccess } from '../lib/toast';
import type { AgentLibraryItem, BuildPreviewResult, BuildSaveResult } from '../lib/types';
import { classNames } from '../lib/utils';
import { normalizeProviderFallback, type NormalizedFallback } from '../lib/provider-fallback';

type InspectorMode = 'summary' | 'config' | 'preview';
type ConfigFormat = 'yaml' | 'json';
type RestorationState = 'none' | 'live' | 'local';

interface ImproverStep {
  label: string;
  status: 'complete' | 'current' | 'upcoming';
}

const IMPROVEMENT_EXAMPLES: string[] = [
  'Improve the escalation path so the handoff includes the customer\u2019s last two actions.',
  'Tighten the refund workflow so damaged-item claims always request photo evidence first.',
  'Add calmer tone guidance for high-friction conversations and make the closing summary more concise.',
  'Strengthen the safety policy so the agent refuses account changes before verification succeeds.',
];

const INSPECTOR_MODES: Array<{ id: InspectorMode; label: string; description: string }> = [
  { id: 'summary', label: 'Summary', description: 'Readable draft overview' },
  { id: 'config', label: 'Config', description: 'Inspectable YAML or JSON' },
  { id: 'preview', label: 'Preview', description: 'Behavior test harness' },
];

/**
 * Provides a focused, truthful improvement workspace on top of the existing builder session APIs.
 * The page adds browser-local continuity and checkpoint safety without pretending the backend
 * draft store is more durable than it is today.
 */
export function AgentImprover() {
  const navigate = useNavigate();
  const { setActiveAgent } = useActiveAgent();
  const saveAgent = useSaveAgent();

  const [composer, setComposer] = useState<string>('');
  const [checkpoints, setCheckpoints] = useState<AgentImproverCheckpoint[]>([]);
  const [activeCheckpointIndex, setActiveCheckpointIndex] = useState<number>(0);
  const [sessionHydrating, setSessionHydrating] = useState<boolean>(true);
  const [requestPending, setRequestPending] = useState<boolean>(false);
  const [savePending, setSavePending] = useState<boolean>(false);
  const [previewPending, setPreviewPending] = useState<boolean>(false);
  const [inspectorMode, setInspectorMode] = useState<InspectorMode>('summary');
  const [configFormat, setConfigFormat] = useState<ConfigFormat>('yaml');
  const [previewMessage, setPreviewMessage] = useState<string>('');
  const [previewResult, setPreviewResult] = useState<BuildPreviewResult | null>(null);
  const [saveResult, setSaveResult] = useState<BuildSaveResult | null>(null);
  const [savedAgent, setSavedAgent] = useState<AgentLibraryItem | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [liveSessionId, setLiveSessionId] = useState<string | null>(null);
  const [liveSessionAvailable, setLiveSessionAvailable] = useState<boolean>(false);
  const [restorationState, setRestorationState] = useState<RestorationState>('none');
  const [showResetConfirm, setShowResetConfirm] = useState<boolean>(false);
  const conversationRef = useRef<HTMLDivElement | null>(null);

  const busy: boolean = requestPending || savePending || previewPending;
  const session: BuilderSessionPayload | null = checkpoints[activeCheckpointIndex]?.session ?? null;
  const latestSession: BuilderSessionPayload | null = checkpoints.at(-1)?.session ?? null;
  const latestUserRequest: string = useMemo(() => latestUserRequestFromSession(session), [session]);
  const viewingLatestCheckpoint = checkpoints.length === 0 || activeCheckpointIndex === checkpoints.length - 1;
  const checkpointMode = checkpoints.length > 0 && !viewingLatestCheckpoint;
  const recoveredLocalDraft = restorationState === 'local' && Boolean(session?.session_id);
  const liveActionsEnabled = Boolean(latestSession?.session_id) && viewingLatestCheckpoint && liveSessionAvailable;
  const hasUnsavedWork = Boolean(session?.session_id && !saveResult);
  const yamlPreview: string = session?.config ? serializeBuilderConfigToYaml(session.config) : '';
  const jsonPreview: string = session?.config ? JSON.stringify(session.config, null, 2) : '';
  const configPreview: string = configFormat === 'yaml' ? yamlPreview : jsonPreview;
  const canUndo = activeCheckpointIndex > 0;
  const canRedo = activeCheckpointIndex < checkpoints.length - 1;
  const composerDisabled = checkpointMode || recoveredLocalDraft;
  const composerHelperText = checkpointMode
    ? 'Return to the latest checkpoint to continue live editing.'
    : recoveredLocalDraft
      ? 'This recovered copy is read-only. Start a new draft to continue live editing.'
      : null;
  const steps: ImproverStep[] = useMemo(() => {
    const hasDraft = Boolean(session?.session_id);
    const hasPreview = Boolean(previewResult);
    const hasSaved = Boolean(saveResult);

    if (hasSaved) {
      return [
        { label: 'Brief', status: 'complete' },
        { label: 'Refine', status: 'complete' },
        { label: 'Inspect', status: 'complete' },
        { label: 'Validate', status: 'current' },
      ];
    }

    if (hasPreview) {
      return [
        { label: 'Brief', status: 'complete' },
        { label: 'Refine', status: 'complete' },
        { label: 'Inspect', status: 'current' },
        { label: 'Validate', status: 'upcoming' },
      ];
    }

    if (hasDraft) {
      return [
        { label: 'Brief', status: 'complete' },
        { label: 'Refine', status: 'current' },
        { label: 'Inspect', status: 'upcoming' },
        { label: 'Validate', status: 'upcoming' },
      ];
    }

    return [
      { label: 'Brief', status: 'current' },
      { label: 'Refine', status: 'upcoming' },
      { label: 'Inspect', status: 'upcoming' },
      { label: 'Validate', status: 'upcoming' },
    ];
  }, [previewResult, saveResult, session?.session_id]);

  useEffect(() => {
    document.title = 'Agent Improver \u2022 AgentLab';
  }, []);

  // Unsaved-work protection: warn before browser close/refresh
  useEffect(() => {
    if (!hasUnsavedWork) return;

    function onBeforeUnload(e: BeforeUnloadEvent) {
      e.preventDefault();
    }
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => window.removeEventListener('beforeunload', onBeforeUnload);
  }, [hasUnsavedWork]);

  useEffect(() => {
    const persisted = readPersistedAgentImproverState();
    if (persisted) {
      setCheckpoints(persisted.checkpoints);
      setActiveCheckpointIndex(persisted.activeCheckpointIndex);
      setPreviewMessage(persisted.previewMessage);
      setSaveResult(persisted.saveResult);
      setSavedAgent(persisted.savedAgent);
      setLiveSessionId(persisted.liveSessionId ?? persisted.checkpoints.at(-1)?.session.session_id ?? null);
    }

    const storedSessionId = persisted?.liveSessionId ?? persisted?.checkpoints.at(-1)?.session.session_id ?? null;
    if (!storedSessionId) {
      setSessionHydrating(false);
      return;
    }

    let cancelled = false;
    setSessionHydrating(true);

    void getBuilderSession(storedSessionId)
      .then((storedSession) => {
        if (cancelled) return;
        const nextHistory = buildCheckpointHistory(persisted?.checkpoints ?? [], storedSession);
        setCheckpoints(nextHistory);
        setActiveCheckpointIndex(nextHistory.length - 1);
        setLiveSessionId(storedSession.session_id);
        setLiveSessionAvailable(true);
        setRestorationState('live');
        if (!persisted?.previewMessage?.trim()) {
          setPreviewMessage(defaultPreviewMessageForBuilderConfig(storedSession.config));
        }
      })
      .catch(() => {
        if (cancelled) return;
        setLiveSessionId(storedSessionId);
        setLiveSessionAvailable(false);
        setRestorationState(persisted?.checkpoints.length ? 'local' : 'none');
      })
      .finally(() => {
        if (!cancelled) setSessionHydrating(false);
      });

    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!session?.config || previewMessage.trim()) return;
    setPreviewMessage(defaultPreviewMessageForBuilderConfig(session.config));
  }, [previewMessage, session?.config, session?.updated_at]);

  useEffect(() => {
    const container = conversationRef.current;
    if (!container) return;
    container.scrollTop = container.scrollHeight;
  }, [session?.messages]);

  // Global keyboard shortcuts: Cmd/Ctrl+S to save
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === 's') {
        e.preventDefault();
        if (liveActionsEnabled && !busy) {
          void handleSaveDraft();
        }
      }
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveActionsEnabled, busy]);

  useEffect(() => {
    if (
      checkpoints.length === 0
      && !previewMessage.trim()
      && !saveResult
      && !savedAgent
      && !liveSessionId
    ) {
      clearPersistedAgentImproverState();
      return;
    }

    writePersistedAgentImproverState({
      version: 2,
      liveSessionId: liveSessionId ?? latestSession?.session_id ?? null,
      checkpoints,
      activeCheckpointIndex,
      previewMessage,
      saveResult,
      savedAgent,
    });
  }, [
    activeCheckpointIndex,
    checkpoints,
    liveSessionId,
    latestSession?.session_id,
    previewMessage,
    saveResult,
    savedAgent,
  ]);

  async function handleSendRequest(): Promise<void> {
    const message = composer.trim();
    if (!message || requestPending || composerDisabled) return;

    setRequestPending(true);
    setError(null);

    try {
      const nextSession = await sendBuilderMessage({
        message,
        session_id: latestSession?.session_id,
      });
      const nextHistory = buildCheckpointHistory(checkpoints, nextSession);
      setCheckpoints(nextHistory);
      setActiveCheckpointIndex(nextHistory.length - 1);
      setLiveSessionId(nextSession.session_id);
      setLiveSessionAvailable(true);
      setRestorationState('none');
      setComposer('');
      setPreviewResult(null);
      setSaveResult(null);
      setSavedAgent(null);
      setInspectorMode('summary');
    } catch (submitError) {
      const messageText =
        submitError instanceof Error ? submitError.message : 'The improver request failed. Check your connection and try again.';
      setError(messageText);
      toastError('Request failed', messageText);
    } finally {
      setRequestPending(false);
    }
  }

  async function handleRunPreview(): Promise<void> {
    const message = previewMessage.trim();
    if (!liveActionsEnabled || !latestSession?.session_id || !message || previewPending) return;

    setPreviewPending(true);
    setError(null);

    try {
      const result = await previewBuilderSession({
        session_id: latestSession.session_id,
        message,
      });
      setPreviewResult(result);
      setInspectorMode('preview');
    } catch (previewError) {
      const messageText =
        previewError instanceof Error ? previewError.message : 'Preview failed. The builder may be temporarily unavailable.';
      setError(messageText);
      toastError('Preview failed', messageText);
    } finally {
      setPreviewPending(false);
    }
  }

  async function handleSaveDraft(): Promise<AgentLibraryItem | null> {
    if (!liveActionsEnabled || !latestSession?.session_id || savePending) return null;

    setSavePending(true);
    setError(null);

    try {
      const payload = await saveAgent.mutateAsync({
        source: 'built',
        build_source: 'builder_chat',
        session_id: latestSession.session_id,
      });

      if (!payload.save_result) {
        throw new Error('The save response did not include workspace metadata.');
      }

      setSaveResult(payload.save_result);
      setSavedAgent(payload.agent);
      setActiveAgent(payload.agent);
      toastSuccess('Draft saved', payload.save_result.config_path);
      return payload.agent;
    } catch (saveError) {
      const messageText = saveError instanceof Error ? saveError.message : 'Save failed. Your draft is still in the session \u2014 try again.';
      setError(messageText);
      toastError('Save failed', messageText);
      return null;
    } finally {
      setSavePending(false);
    }
  }

  async function handleContinueToEval(): Promise<void> {
    if (savedAgent) {
      navigateToEvalWorkflow(navigate, savedAgent);
      return;
    }

    const agent = await handleSaveDraft();
    if (agent) {
      navigateToEvalWorkflow(navigate, agent);
    }
  }

  async function handleCopyDraft(): Promise<void> {
    if (!configPreview || !navigator.clipboard?.writeText) return;

    try {
      await navigator.clipboard.writeText(configPreview);
      toastSuccess('Copied', `${configFormat.toUpperCase()} draft copied to clipboard.`);
    } catch (copyError) {
      const messageText = copyError instanceof Error ? copyError.message : 'Copy failed.';
      setError(messageText);
      toastError('Copy failed', messageText);
    }
  }

  async function handleDownloadDraft(): Promise<void> {
    if (!session?.config) return;

    try {
      if (liveActionsEnabled && latestSession?.session_id) {
        const payload = await exportBuilderConfig({
          session_id: latestSession.session_id,
          format: configFormat,
        });
        downloadTextFile(payload.content, payload.filename, payload.content_type);
        toastSuccess('Exported', payload.filename);
        return;
      }

      const filename = buildLocalDraftFilename(session.config.agent_name, configFormat);
      downloadTextFile(
        configPreview,
        filename,
        configFormat === 'json' ? 'application/json' : 'application/x-yaml',
      );
      toastSuccess('Exported', filename);
    } catch (downloadError) {
      const messageText =
        downloadError instanceof Error ? downloadError.message : 'Download failed.';
      setError(messageText);
      toastError('Download failed', messageText);
    }
  }

  function handleUndoCheckpoint(): void {
    if (!canUndo) return;
    setActiveCheckpointIndex((current) => Math.max(current - 1, 0));
    setPreviewResult(null);
    setInspectorMode('summary');
    setError(null);
  }

  function handleRedoCheckpoint(): void {
    if (!canRedo) return;
    setActiveCheckpointIndex((current) => Math.min(current + 1, checkpoints.length - 1));
    setPreviewResult(null);
    setInspectorMode('summary');
    setError(null);
  }

  function handleStartNewDraft(): void {
    setShowResetConfirm(false);
    const seedMessage = latestUserRequest !== 'No request submitted yet.' ? latestUserRequest : '';
    setComposer((current) => current.trim() || seedMessage);
    setCheckpoints([]);
    setActiveCheckpointIndex(0);
    setLiveSessionId(null);
    setLiveSessionAvailable(false);
    setRestorationState('none');
    setPreviewMessage('');
    setPreviewResult(null);
    setSaveResult(null);
    setSavedAgent(null);
    setError(null);
    setInspectorMode('summary');
    clearPersistedAgentImproverState();
    toastSuccess('Session reset', 'Started a fresh improvement session.');
  }

  const recoveryNotice = recoveredLocalDraft ? (
    <InlineNotice tone="warning" title="Recovered local draft">
      <p>The live builder session could not be restored. You can inspect or copy this draft, or start a new draft to continue editing.</p>
    </InlineNotice>
  ) : checkpointMode ? (
    <InlineNotice tone="warning" title={`Viewing checkpoint ${activeCheckpointIndex + 1} of ${checkpoints.length}`}>
      <p>Undo/redo checkpoints are inspection-only snapshots. Return to the latest draft to preview, save, or continue editing live.</p>
    </InlineNotice>
  ) : restorationState === 'live' ? (
    <InlineNotice tone="success" title="Restored live draft">
      <p>Your latest browser-backed draft is ready to continue.</p>
    </InlineNotice>
  ) : null;

  return (
    <div className="relative overflow-hidden rounded-[38px] bg-[radial-gradient(circle_at_top_left,rgba(245,236,244,0.96),rgba(235,231,239,0.82)_38%,rgba(228,225,236,0.78)_100%)] p-3 sm:p-5">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-40 bg-[radial-gradient(circle_at_top,rgba(255,255,255,0.78),transparent_70%)]" />
      <div className="pointer-events-none absolute -right-20 top-10 h-56 w-56 rounded-full bg-[rgba(220,197,205,0.24)] blur-3xl" />
      <div className="pointer-events-none absolute bottom-4 left-10 h-48 w-48 rounded-full bg-[rgba(214,208,228,0.26)] blur-3xl" />

      {/* Reset confirmation dialog */}
      {showResetConfirm ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm"
          role="dialog"
          aria-modal="true"
          aria-label="Confirm reset"
          onKeyDown={(e) => {
            if (e.key === 'Escape') setShowResetConfirm(false);
          }}
        >
          <div className="mx-4 w-full max-w-md rounded-[24px] border border-[#e7dde2] bg-white p-6 shadow-xl">
            <div className="flex items-start gap-3">
              <AlertTriangle className="mt-0.5 h-5 w-5 flex-shrink-0 text-amber-500" />
              <div>
                <h3 className="text-base font-semibold text-[#1f1b23]">Start over?</h3>
                <p className="mt-2 text-sm leading-6 text-[#625967]">
                  This will discard your current draft and conversation. This cannot be undone.
                </p>
              </div>
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowResetConfirm(false)}
                className="rounded-full border border-[#ded5db] bg-white px-4 py-2 text-sm font-medium text-[#4d4550] transition hover:bg-[#faf7f8]"
                autoFocus
              >
                Keep working
              </button>
              <button
                type="button"
                onClick={handleStartNewDraft}
                className="rounded-full bg-rose-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-rose-700"
              >
                Discard and reset
              </button>
            </div>
          </div>
        </div>
      ) : null}

      <div className="relative rounded-[34px] border border-white/70 bg-[#f8f3f0]/90 p-3 shadow-[0_24px_80px_rgba(74,54,82,0.16)] backdrop-blur-xl sm:p-4">
        <div className="rounded-[28px] border border-white/80 bg-white/70 px-4 py-4 shadow-[0_10px_30px_rgba(87,64,88,0.08)]">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.22em] text-[#756c78]">
                <span>Build</span>
                <span className="text-[#bbb2bc]">/</span>
                <span>Agent Improver</span>
              </div>
              <h2 className="mt-2 text-2xl font-semibold tracking-[-0.03em] text-[#1f1b23]">
                Agent Improver
              </h2>
              <p className="mt-1 max-w-2xl text-sm leading-6 text-[#615867]">
                Describe what your agent should do differently. Refine the draft, inspect the config, test it, then save.
              </p>
            </div>

            <nav aria-label="Improvement progress">
              <ol className="flex flex-wrap gap-2" role="list">
                {steps.map((step, index) => (
                  <li key={step.label}>
                    <span
                      aria-label={`Step ${index + 1}: ${step.label} \u2014 ${step.status}`}
                      aria-current={step.status === 'current' ? 'step' : undefined}
                      className={classNames(
                        'inline-flex items-center gap-2 rounded-full border px-3 py-2 text-xs font-medium',
                        step.status === 'complete'
                          ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
                          : step.status === 'current'
                            ? 'border-[#d9c7cf] bg-[#fbf4f5] text-[#6f5060]'
                            : 'border-[#e2d8de] bg-white/70 text-[#8a8089]'
                      )}
                    >
                      <span
                        className={classNames(
                          'flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-semibold',
                          step.status === 'complete'
                            ? 'bg-white text-emerald-700'
                            : step.status === 'current'
                              ? 'bg-white text-[#6f5060]'
                              : 'bg-[#f3edf0] text-[#8a8089]'
                        )}
                      >
                        {step.status === 'complete' ? <CheckCircle2 className="h-3 w-3" /> : step.label.slice(0, 1)}
                      </span>
                      {step.label}
                    </span>
                  </li>
                ))}
              </ol>
            </nav>

            <div className="flex flex-wrap items-center gap-2">
              {session?.session_id ? (
                <button
                  type="button"
                  onClick={() => {
                    if (hasUnsavedWork) {
                      setShowResetConfirm(true);
                    } else {
                      handleStartNewDraft();
                    }
                  }}
                  className="inline-flex items-center gap-2 rounded-full border border-[#ddd4da] bg-white/80 px-3.5 py-2 text-sm font-medium text-[#4d4550] transition hover:bg-white"
                  aria-label="Start a new session"
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                  New session
                </button>
              ) : null}
              <Link
                to="/build?tab=builder-chat"
                className="inline-flex items-center gap-2 rounded-full border border-[#ddd4da] bg-white/80 px-3.5 py-2 text-sm font-medium text-[#4d4550] transition hover:bg-white"
              >
                Open Build
              </Link>
            </div>
          </div>
        </div>

        <div className="mt-3 grid gap-3 xl:grid-cols-[minmax(0,0.92fr)_minmax(0,1.08fr)]">
          <section className="flex min-h-[760px] flex-col overflow-hidden rounded-[30px] border border-white/70 bg-[#fbf7f4]/90 shadow-[0_12px_30px_rgba(83,63,79,0.08)]" aria-label="Improvement workspace">
            <div className="border-b border-[#e7dde2] px-5 py-5">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#8a8087]">
                    Improvement workspace
                  </p>
                  <h3 className="mt-2 text-xl font-semibold tracking-[-0.02em] text-[#1f1b23]">
                    {session?.session_id ? 'Refine your agent' : 'Start with an improvement'}
                  </h3>
                  <p className="mt-2 max-w-xl text-sm leading-6 text-[#625967]">
                    {session?.session_id
                      ? 'Each message updates the draft on the right. Review it in Summary, Config, or Preview before saving.'
                      : 'Describe what your agent needs \u2014 a new tool, a policy change, better routing, or a tone adjustment. Pick an example below or write your own.'}
                  </p>
                </div>
                <SessionBadge session={session} />
              </div>

              {!session?.session_id ? (
                <div className="mt-4 space-y-3">
                  <div className="rounded-[24px] border border-[#e7dde2] bg-white/85 p-4">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#8a8087]">
                      Try an example
                    </p>
                    <p className="mt-2 text-sm leading-6 text-[#5e5662]">
                      Click any example to load it into the composer, then send it to create your first draft.
                    </p>
                    <div className="mt-4 grid gap-2 sm:grid-cols-2">
                      {IMPROVEMENT_EXAMPLES.map((example) => (
                        <button
                          key={example}
                          type="button"
                          onClick={() => setComposer(example)}
                          className="rounded-[18px] border border-[#e4d8de] bg-[#fbf7f8] px-3 py-3 text-left text-xs leading-5 text-[#625967] transition hover:border-[#d4c4cc] hover:bg-white focus:outline-none focus:ring-2 focus:ring-[#d4c4cc] focus:ring-offset-1"
                        >
                          {example}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div className="rounded-[24px] border border-[#eadfce] bg-[#fffaf3] p-4">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#93816d]">
                      Good to know
                    </p>
                    <p className="mt-2 text-sm leading-6 text-[#685d50]">
                      Each session starts fresh. To continue improving a previously saved agent, start a new session and describe the changes you want.
                    </p>
                  </div>
                </div>
              ) : null}
            </div>

            <div
              ref={conversationRef}
              className="flex-1 space-y-4 overflow-y-auto px-5 py-5"
              role="log"
              aria-label="Conversation history"
              aria-live="polite"
            >
              {sessionHydrating ? (
                <EmptyWorkspaceCard
                  title="Restoring your session"
                  body="Looking for your previous draft in this browser..."
                />
              ) : null}

              {!sessionHydrating && recoveryNotice}

              {!sessionHydrating && !session?.session_id ? (
                <ConversationMessage
                  role="assistant"
                  title="Improver"
                  body="Describe what you want to change. I'll create a draft you can inspect, test, and save."
                />
              ) : null}

              {(session?.messages ?? []).map((message) => (
                <ConversationMessage
                  key={message.message_id}
                  role={message.role}
                  title={message.role === 'user' ? 'You' : 'Improver'}
                  body={message.content}
                />
              ))}

              {error ? (
                <DismissibleError
                  message={error}
                  onDismiss={() => setError(null)}
                />
              ) : null}
            </div>

            <div className="border-t border-[#e7dde2] bg-[linear-gradient(180deg,rgba(251,247,244,0.65),rgba(255,255,255,0.95))] px-5 py-5">
              <div className="rounded-[26px] border border-[#e3d8dd] bg-white/95 p-3 shadow-[0_10px_30px_rgba(87,64,88,0.08)]">
                <label className="sr-only" htmlFor="agent-improver-composer">
                  Describe how the draft should improve next
                </label>
                <textarea
                  id="agent-improver-composer"
                  value={composer}
                  onChange={(event) => setComposer(event.target.value)}
                  placeholder="Describe how the draft should improve next..."
                  rows={4}
                  disabled={composerDisabled}
                  aria-describedby="composer-hint"
                  className="min-h-[110px] w-full resize-none bg-transparent px-3 py-3 text-sm leading-6 text-[#211d24] outline-none placeholder:text-[#9b929a] disabled:cursor-not-allowed disabled:text-[#8f8790]"
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' && !event.shiftKey) {
                      event.preventDefault();
                      void handleSendRequest();
                    }
                  }}
                />
                <div className="flex flex-col gap-3 border-t border-[#f0e8eb] px-3 pt-3 sm:flex-row sm:items-center sm:justify-between">
                  <p id="composer-hint" className="text-xs leading-5 text-[#817781]">
                    {composerHelperText ?? (
                      <>
                        Press Enter to send, Shift+Enter for a new line.
                        {session?.session_id ? <span className="hidden sm:inline"> {'\u00B7'} {isMac() ? '\u2318' : 'Ctrl+'}S to save.</span> : null}
                      </>
                    )}
                  </p>
                  <button
                    type="button"
                    onClick={() => void handleSendRequest()}
                    disabled={!composer.trim() || busy || composerDisabled}
                    className="inline-flex items-center justify-center gap-2 rounded-full bg-[#2a242d] px-4 py-2.5 text-sm font-medium text-white transition hover:bg-[#1f1a22] disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    <Send className="h-4 w-4" />
                    {requestPending ? 'Updating draft...' : 'Send request'}
                  </button>
                </div>
              </div>
            </div>
          </section>

          <section className="flex min-h-[760px] flex-col overflow-hidden rounded-[30px] border border-white/70 bg-[#fffdfb]/92 shadow-[0_12px_30px_rgba(83,63,79,0.08)]" aria-label="Draft inspector">
            <div className="border-b border-[#ede4e8] px-5 py-5">
              <div className="flex flex-col gap-4">
                <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
                  <div>
                    <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#8a8087]">
                      Current draft
                    </p>
                    <h3 className="mt-2 text-xl font-semibold tracking-[-0.02em] text-[#1f1b23]">
                      {session?.config ? 'Review and validate' : 'Waiting for first draft'}
                    </h3>
                    <p className="mt-2 max-w-xl text-sm leading-6 text-[#625967]">
                      {session?.config
                        ? 'Check the Summary for an overview, Config for the raw definition, and Preview to test behavior.'
                        : 'Send your first message to generate a draft. It will appear here for inspection.'}
                    </p>
                  </div>

                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      onClick={handleUndoCheckpoint}
                      disabled={!canUndo}
                      aria-label="Undo checkpoint"
                      className="inline-flex items-center gap-2 rounded-full border border-[#ded5db] bg-white px-3.5 py-2 text-sm font-medium text-[#4d4550] transition hover:bg-[#faf7f8] disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      <RotateCcw className="h-4 w-4" />
                      Undo
                    </button>
                    <button
                      type="button"
                      onClick={handleRedoCheckpoint}
                      disabled={!canRedo}
                      aria-label="Redo checkpoint"
                      className="inline-flex items-center gap-2 rounded-full border border-[#ded5db] bg-white px-3.5 py-2 text-sm font-medium text-[#4d4550] transition hover:bg-[#faf7f8] disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      <RotateCw className="h-4 w-4" />
                      Redo
                    </button>
                  </div>
                </div>

                {session?.mock_mode && viewingLatestCheckpoint ? (
                  <FallbackNotice
                    mockMode={session.mock_mode}
                    mockReason={session.mock_reason}
                    onRetry={session.session_id ? () => {
                      const lastMsg = latestUserRequest;
                      if (lastMsg && lastMsg !== 'No request submitted yet.') {
                        setComposer(lastMsg);
                      }
                    } : undefined}
                  />
                ) : null}

                <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
                  <div className="inline-flex rounded-full border border-[#e5dbe0] bg-[#f8f4f6] p-1" role="tablist" aria-label="Inspector views">
                    {INSPECTOR_MODES.map((mode) => (
                      <button
                        key={mode.id}
                        type="button"
                        role="tab"
                        id={`tab-${mode.id}`}
                        aria-selected={inspectorMode === mode.id}
                        aria-controls={`panel-${mode.id}`}
                        onClick={() => setInspectorMode(mode.id)}
                        className={classNames(
                          'rounded-full px-4 py-2 text-sm font-medium transition focus:outline-none focus:ring-2 focus:ring-[#d4c4cc] focus:ring-offset-1',
                          inspectorMode === mode.id
                            ? 'bg-white text-[#1f1b23] shadow-sm'
                            : 'text-[#7f747f] hover:text-[#3a333d]'
                        )}
                      >
                        {mode.label}
                      </button>
                    ))}
                  </div>

                  <div className="flex flex-wrap items-center gap-2">
                    {session?.session_id ? (
                      <button
                        type="button"
                        onClick={() => void handleSaveDraft()}
                        disabled={!liveActionsEnabled || busy}
                        aria-keyshortcuts={isMac() ? 'Meta+S' : 'Control+S'}
                        className="inline-flex items-center gap-2 rounded-full border border-[#ded5db] bg-white px-3.5 py-2 text-sm font-medium text-[#4d4550] transition hover:bg-[#faf7f8] disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        <CheckCircle2 className="h-4 w-4" />
                        {savePending ? 'Saving...' : saveResult ? 'Saved' : 'Save to workspace'}
                      </button>
                    ) : null}
                    <button
                      type="button"
                      onClick={() => void handleContinueToEval()}
                      disabled={!liveActionsEnabled || busy}
                      className="inline-flex items-center gap-2 rounded-full border border-[#ecd8dc] bg-[#fbf3f4] px-3.5 py-2 text-sm font-medium text-[#7b5663] transition hover:bg-[#f8eaed] disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      Continue to Eval
                      <ArrowRight className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              </div>
            </div>

            <div
              className="flex-1 overflow-y-auto px-5 py-5"
              role="tabpanel"
              id={`panel-${inspectorMode}`}
              aria-labelledby={`tab-${inspectorMode}`}
            >
              {inspectorMode === 'summary' ? (
                <SummaryMode
                  session={session}
                  latestUserRequest={latestUserRequest}
                  checkpointMode={checkpointMode}
                  restoredLocally={recoveredLocalDraft}
                  restoredLive={restorationState === 'live'}
                />
              ) : null}

              {inspectorMode === 'config' ? (
                <ConfigMode
                  config={session?.config ?? null}
                  activeFormat={configFormat}
                  content={configPreview}
                  onFormatChange={setConfigFormat}
                  onCopy={() => void handleCopyDraft()}
                  onDownload={() => void handleDownloadDraft()}
                  localExport={recoveredLocalDraft || checkpointMode}
                />
              ) : null}

              {inspectorMode === 'preview' ? (
                <PreviewMode
                  session={session}
                  previewMessage={previewMessage}
                  previewPending={previewPending}
                  previewResult={previewResult}
                  actionsDisabledReason={getPreviewDisabledReason({
                    checkpointMode,
                    recoveredLocalDraft,
                    liveActionsEnabled,
                  })}
                  onPreviewMessageChange={setPreviewMessage}
                  onRunPreview={() => void handleRunPreview()}
                />
              ) : null}
            </div>

            <div className="border-t border-[#ede4e8] bg-[#fffaf7] px-5 py-4">
              {saveResult ? (
                <InlineNotice tone="success" title="Draft saved">
                  Saved to {saveResult.config_path}. You can now continue to eval or keep refining.
                </InlineNotice>
              ) : session?.mock_mode ? (
                <FallbackFooterNotice mockMode={session.mock_mode} mockReason={session.mock_reason} />
              ) : (
                <p className="text-xs leading-5 text-[#847986]">
                  {session?.session_id
                    ? 'Review the draft, then save when you\'re satisfied. Use Preview to test behavior first.'
                    : 'Your draft will appear here after your first message.'}
                </p>
              )}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}

function SummaryMode({
  session,
  latestUserRequest,
  checkpointMode,
  restoredLocally,
  restoredLive,
}: {
  session: BuilderSessionPayload | null;
  latestUserRequest: string;
  checkpointMode: boolean;
  restoredLocally: boolean;
  restoredLive: boolean;
}) {
  if (!session?.config) {
    return (
      <EmptyWorkspaceCard
        title="No draft yet"
        body="Start the conversation on the left and the improver will turn the request into a live builder-backed draft here."
      />
    );
  }

  const { config } = session;
  const fallback = normalizeProviderFallback(session.mock_mode, session.mock_reason);
  const sessionStateLabel = restoredLocally
    ? 'Recovered locally'
    : checkpointMode
      ? 'Checkpoint view'
      : restoredLive
        ? 'Restored live draft'
        : fallback
          ? fallback.badge
          : 'Live session';

  return (
    <div className="space-y-4">
      <div className="rounded-[26px] border border-[#e9dee4] bg-[#fbf7f4] p-5">
        <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
          <div className="min-w-0">
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#8a8087]">
              Agent card
            </p>
            <h4 className="mt-2 text-2xl font-semibold tracking-[-0.03em] text-[#1f1b23]">
              {config.agent_name}
            </h4>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-[#615867]">
              {config.system_prompt}
            </p>
          </div>

          <div className="rounded-[22px] border border-[#efe3e7] bg-white px-4 py-3 text-sm text-[#4f4651]">
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#8a8087]">
              Model
            </p>
            <p className="mt-2 font-medium">{config.model}</p>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          <SummaryPill label={sessionStateLabel} />
          <SummaryPill label={formatCountLabel(session.stats.tool_count, 'tool')} />
          <SummaryPill label={formatCountLabel(session.stats.policy_count, 'policy', 'policies')} />
          <SummaryPill label={formatCountLabel(session.stats.routing_rule_count, 'route')} />
          <SummaryPill label={session.evals ? `${session.evals.case_count} draft evals` : 'No eval draft yet'} />
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.1fr)_minmax(280px,0.9fr)]">
        <SummaryPanel eyebrow="Latest request" title="What changed most recently">
          <p className="text-sm leading-6 text-[#554d59]">{latestUserRequest}</p>
        </SummaryPanel>

        <SummaryPanel eyebrow="Trust cues" title="Why this draft is inspectable">
          <ul className="space-y-2 text-sm leading-6 text-[#554d59]">
            <li>Each accepted request becomes a restorable checkpoint.</li>
            <li>The raw config stays viewable in YAML or JSON.</li>
            <li>The preview mode exercises the current draft directly when the live session is available.</li>
          </ul>
        </SummaryPanel>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <SummaryListPanel
          eyebrow="Tools"
          title={formatCountLabel(config.tools.length, 'active capability', 'active capabilities')}
          items={config.tools.map((tool) => `${tool.name}: ${tool.description}`)}
        />
        <SummaryListPanel
          eyebrow="Routing"
          title={formatCountLabel(config.routing_rules.length, 'decision path')}
          items={config.routing_rules.map((rule) => `${rule.intent}: ${rule.description}`)}
        />
        <div className="lg:col-span-2">
          <SummaryListPanel
            eyebrow="Policies"
            title={formatCountLabel(config.policies.length, 'operating guardrail')}
            items={config.policies.map((policy) => `${policy.name}: ${policy.description}`)}
          />
        </div>
      </div>
    </div>
  );
}

function ConfigMode({
  config,
  activeFormat,
  content,
  onFormatChange,
  onCopy,
  onDownload,
  localExport,
}: {
  config: BuilderConfig | null;
  activeFormat: ConfigFormat;
  content: string;
  onFormatChange: (format: ConfigFormat) => void;
  onCopy: () => void;
  onDownload: () => void;
  localExport: boolean;
}) {
  if (!config) {
    return (
      <EmptyWorkspaceCard
        title="No draft yet"
        body="The config view will appear as soon as the improver produces the first draft."
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 rounded-[24px] border border-[#e9dee4] bg-[#fbf7f4] p-4 md:flex-row md:items-center md:justify-between">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#8a8087]">
            Raw config
          </p>
          <p className="mt-2 text-sm leading-6 text-[#615867]">
            Inspect the exact draft that is being shaped by the conversation. Copy or download the
            current view when you need to compare or share it.
          </p>
          {localExport ? (
            <p className="mt-2 text-xs leading-5 text-[#7a6f79]">
              Download exports the current local checkpoint because the live backend draft is not the active source of truth.
            </p>
          ) : null}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex rounded-full border border-[#e2d8de] bg-white/90 p-1">
            {(['yaml', 'json'] as const).map((format) => (
              <button
                key={format}
                type="button"
                onClick={() => onFormatChange(format)}
                className={classNames(
                  'rounded-full px-3 py-1.5 text-sm font-medium transition',
                  activeFormat === format
                    ? 'bg-[#2a242d] text-white'
                    : 'text-[#756c78] hover:text-[#2a242d]'
                )}
              >
                {format.toUpperCase()}
              </button>
            ))}
          </div>

          <button
            type="button"
            onClick={onCopy}
            className="inline-flex items-center gap-2 rounded-full border border-[#ded5db] bg-white px-3.5 py-2 text-sm font-medium text-[#4d4550] transition hover:bg-[#faf7f8]"
          >
            <Copy className="h-4 w-4" />
            Copy draft
          </button>

          <button
            type="button"
            onClick={onDownload}
            className="inline-flex items-center gap-2 rounded-full border border-[#ded5db] bg-white px-3.5 py-2 text-sm font-medium text-[#4d4550] transition hover:bg-[#faf7f8]"
          >
            <Download className="h-4 w-4" />
            Download draft
          </button>
        </div>
      </div>

      <div
        data-testid="agent-improver-yaml-preview"
        className="overflow-hidden rounded-[26px] border border-[#1d1724] bg-[#121019] shadow-[inset_0_1px_0_rgba(255,255,255,0.03)]"
      >
        <div className="flex items-center justify-between border-b border-white/6 px-4 py-3 text-xs text-slate-400">
          <span>{config.agent_name}</span>
          <span>{activeFormat.toUpperCase()} view</span>
        </div>
        <ConfigCodeBlock content={content} />
      </div>
    </div>
  );
}

function PreviewMode({
  session,
  previewMessage,
  previewPending,
  previewResult,
  actionsDisabledReason,
  onPreviewMessageChange,
  onRunPreview,
}: {
  session: BuilderSessionPayload | null;
  previewMessage: string;
  previewPending: boolean;
  previewResult: BuildPreviewResult | null;
  actionsDisabledReason: string | null;
  onPreviewMessageChange: (message: string) => void;
  onRunPreview: () => void;
}) {
  if (!session?.config) {
    return (
      <EmptyWorkspaceCard
        title="No draft yet"
        body="Preview mode becomes active after the first improver response creates a draft."
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="rounded-[24px] border border-[#e9dee4] bg-[#fbf7f4] p-4">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#8a8087]">
              Behavior preview
            </p>
            <p className="mt-2 text-sm leading-6 text-[#615867]">
              Test the current draft with a realistic message. The response below comes from the same
              builder-backed draft you are refining on the left.
            </p>
          </div>
          <span className="inline-flex items-center gap-2 rounded-full border border-[#d8d1d5] bg-white px-3 py-1.5 text-xs font-medium text-[#645b67]">
            <Bot className="h-3.5 w-3.5" />
            {session.mock_mode
              ? `Builder ${normalizeProviderFallback(session.mock_mode, session.mock_reason)?.badge.toLowerCase() ?? 'fallback'} mode`
              : 'Builder live mode'}
          </span>
        </div>
      </div>

      {actionsDisabledReason ? (
        <InlineNotice tone="warning" title="Preview unavailable">
          <p>{actionsDisabledReason}</p>
        </InlineNotice>
      ) : null}

      <div className="rounded-[24px] border border-[#e9dee4] bg-white p-4">
        <label htmlFor="agent-improver-preview-message" className="text-sm font-medium text-[#2d2730]">
          Preview message
        </label>
        <textarea
          id="agent-improver-preview-message"
          aria-label="Preview message"
          value={previewMessage}
          onChange={(event) => onPreviewMessageChange(event.target.value)}
          rows={4}
          disabled={Boolean(actionsDisabledReason)}
          className="mt-3 min-h-[128px] w-full resize-none rounded-[22px] border border-[#e5dbe0] bg-[#fcfaf9] px-4 py-3 text-sm leading-6 text-[#211d24] outline-none transition focus:border-[#d2c0c7] focus:ring-4 focus:ring-[#f3e8ec] disabled:cursor-not-allowed disabled:text-[#8f8790]"
        />

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={onRunPreview}
            disabled={!previewMessage.trim() || previewPending || Boolean(actionsDisabledReason)}
            className="inline-flex items-center gap-2 rounded-full bg-[#2a242d] px-4 py-2.5 text-sm font-medium text-white transition hover:bg-[#1f1a22] disabled:cursor-not-allowed disabled:opacity-60"
          >
            <Play className="h-4 w-4" />
            {previewPending ? 'Running preview...' : 'Run preview'}
          </button>
          {session.evals ? (
            <span className="rounded-full border border-[#e3d8de] bg-[#faf6f7] px-3 py-1.5 text-xs font-medium text-[#766c77]">
              {session.evals.case_count} draft evals ready to formalize
            </span>
          ) : null}
        </div>
      </div>

      <PreviewResultCard
        result={previewResult}
        emptyText="Run a preview to validate the latest draft before you save it."
      />
    </div>
  );
}

function ConversationMessage({
  role,
  title,
  body,
}: {
  role: 'assistant' | 'user';
  title: string;
  body: string;
}) {
  return (
    <div className={classNames('flex', role === 'user' ? 'justify-end' : 'justify-start')}>
      <div
        className={classNames(
          'max-w-[86%] rounded-[24px] border px-4 py-3.5 text-sm leading-6 shadow-sm',
          role === 'user'
            ? 'border-[#ead7dd] bg-[#fff6f7] text-[#3c323b]'
            : 'border-[#e7dde2] bg-white text-[#514753]'
        )}
      >
        <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[#90858f]">{title}</p>
        <p className="mt-2 whitespace-pre-wrap">{body}</p>
      </div>
    </div>
  );
}

function DismissibleError({
  message,
  onDismiss,
}: {
  message: string;
  onDismiss: () => void;
}) {
  return (
    <div className="rounded-[22px] border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-900" role="alert">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="font-semibold">Something went wrong</p>
          <p className="mt-1 leading-6">{message}</p>
        </div>
        <button
          type="button"
          onClick={onDismiss}
          className="flex-shrink-0 rounded-full p-1 text-rose-600 transition hover:bg-rose-100"
          aria-label="Dismiss error"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

function SummaryPanel({
  eyebrow,
  title,
  children,
}: {
  eyebrow: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-[24px] border border-[#e9dee4] bg-white p-4">
      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#8a8087]">{eyebrow}</p>
      <h4 className="mt-2 text-base font-semibold text-[#1f1b23]">{title}</h4>
      <div className="mt-3">{children}</div>
    </section>
  );
}

function SummaryListPanel({
  eyebrow,
  title,
  items,
}: {
  eyebrow: string;
  title: string;
  items: string[];
}) {
  return (
    <SummaryPanel eyebrow={eyebrow} title={title}>
      <ul className="space-y-2 text-sm leading-6 text-[#554d59]">
        {items.length === 0 ? (
          <li>No entries yet.</li>
        ) : (
          items.map((item) => <li key={item}>{item}</li>)
        )}
      </ul>
    </SummaryPanel>
  );
}

function SummaryPill({ label }: { label: string }) {
  return (
    <span className="rounded-full border border-[#e3d8de] bg-white/90 px-3 py-1.5 text-xs font-medium text-[#5e5561]">
      {label}
    </span>
  );
}

function InlineNotice({
  tone,
  title,
  children,
}: {
  tone: 'success' | 'warning' | 'error';
  title: string;
  children: ReactNode;
}) {
  const toneClasses =
    tone === 'success'
      ? 'border-emerald-200 bg-emerald-50 text-emerald-900'
      : tone === 'warning'
        ? 'border-amber-200 bg-amber-50 text-amber-900'
        : 'border-rose-200 bg-rose-50 text-rose-900';

  return (
    <div
      role={tone === 'error' ? 'alert' : 'status'}
      aria-live={tone === 'error' ? 'assertive' : 'polite'}
      className={classNames('rounded-[22px] border px-4 py-3 text-sm', toneClasses)}
    >
      <p className="font-semibold">{title}</p>
      <div className="mt-1 leading-6">{children}</div>
    </div>
  );
}

function SessionBadge({ session }: { session: BuilderSessionPayload | null }) {
  const fallback = session?.mock_mode
    ? normalizeProviderFallback(session.mock_mode, session.mock_reason)
    : null;

  const isRateLimit = fallback?.category === 'rate-limit';
  const badgeText = session?.session_id
    ? fallback
      ? `${fallback.badge} session`
      : 'Live session'
    : 'Fresh session';
  const ariaLabel = session?.session_id
    ? fallback
      ? `Session running in ${fallback.badge.toLowerCase()} mode`
      : 'Session connected live'
    : 'No active session';

  return (
    <span
      aria-label={ariaLabel}
      className={classNames(
        'inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium',
        isRateLimit
          ? 'border-orange-200 bg-orange-50 text-orange-800'
          : fallback
            ? 'border-amber-200 bg-amber-50 text-amber-800'
            : session?.session_id
              ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
              : 'border-[#d9cfd6] bg-white/80 text-[#6c636d]'
      )}
    >
      <Sparkles className="h-3.5 w-3.5" />
      {badgeText}
    </span>
  );
}

function FallbackNotice({
  mockMode,
  mockReason,
  onRetry,
}: {
  mockMode: boolean;
  mockReason?: string;
  onRetry?: () => void;
}) {
  const fallback = normalizeProviderFallback(mockMode, mockReason);
  if (!fallback) return null;

  const isRateLimit = fallback.category === 'rate-limit';

  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="fallback-notice"
      className={classNames(
        'rounded-[22px] border px-4 py-3 text-sm',
        isRateLimit
          ? 'border-orange-200 bg-orange-50 text-orange-900'
          : 'border-amber-200 bg-amber-50 text-amber-900'
      )}
    >
      <p className="font-semibold">{fallback.headline}</p>
      <p className="mt-1 leading-6">{fallback.guidance}</p>
      {fallback.retryable && onRetry ? (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={onRetry}
            className={classNames(
              'inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-semibold transition',
              isRateLimit
                ? 'border-orange-300 bg-white text-orange-900 hover:bg-orange-100'
                : 'border-amber-300 bg-white text-amber-900 hover:bg-amber-100'
            )}
          >
            <RotateCcw className="h-3.5 w-3.5" />
            Retry last request
          </button>
          <span className="text-xs opacity-75">
            Rate limits usually clear within 1-2 minutes.
          </span>
        </div>
      ) : null}
    </div>
  );
}

function FallbackFooterNotice({
  mockMode,
  mockReason,
}: {
  mockMode: boolean;
  mockReason?: string;
}) {
  const fallback = normalizeProviderFallback(mockMode, mockReason);
  if (!fallback) return null;

  const isRateLimit = fallback.category === 'rate-limit';
  const title = isRateLimit ? 'Provider rate limited' : 'Running in fallback mode';
  const body = isRateLimit
    ? 'This draft used fallback data. You can still export or save it, then retry when the rate limit clears.'
    : `${fallback.headline} Results may not reflect production behavior.`;

  return (
    <InlineNotice tone="warning" title={title}>
      {body}
    </InlineNotice>
  );
}

function EmptyWorkspaceCard({
  title,
  body,
}: {
  title: string;
  body: string;
}) {
  return (
    <div className="rounded-[24px] border border-dashed border-[#d9cfd6] bg-white/75 px-5 py-6 text-left">
      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#8a8087]">{title}</p>
      <p className="mt-2 max-w-xl text-sm leading-6 text-[#625967]">{body}</p>
    </div>
  );
}

function ConfigCodeBlock({ content }: { content: string }) {
  const lines = content.split('\n');

  return (
    <div className="font-mono text-[12px] leading-6 text-slate-200">
      {lines.map((line, index) => (
        <div
          key={`${index}-${line}`}
          className="grid grid-cols-[48px_minmax(0,1fr)] items-start border-b border-white/5 px-4"
        >
          <span className="select-none pr-3 text-right text-slate-500">{index + 1}</span>
          <code className="overflow-x-auto py-1.5">{line || '\u00A0'}</code>
        </div>
      ))}
    </div>
  );
}

function PreviewResultCard({
  result,
  emptyText,
}: {
  result: BuildPreviewResult | null;
  emptyText: string;
}) {
  if (!result) {
    return (
      <EmptyWorkspaceCard
        title="No preview yet"
        body={emptyText}
      />
    );
  }

  return (
    <div className="rounded-[24px] border border-[#e9dee4] bg-white p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={classNames(
            'inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.18em]',
            result.mock_mode
              ? 'bg-amber-100 text-amber-800'
              : 'bg-emerald-100 text-emerald-800'
          )}
        >
          {result.mock_mode ? 'Mock preview' : 'Live preview'}
        </span>
        <span className="text-xs text-[#7c727e]">{result.specialist_used} specialist</span>
        <span className="text-xs text-[#7c727e]">{Math.round(result.latency_ms)} ms</span>
        <span className="text-xs text-[#7c727e]">{result.token_count} tokens</span>
      </div>
      <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-[#2f2831]">{result.response}</p>
      {result.tool_calls.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {result.tool_calls.map((toolCall, index) => (
            <span
              key={`${String(toolCall.name ?? toolCall.tool_name ?? `tool_${index}`)}-${index}`}
              className="rounded-full border border-[#e5dbe0] bg-[#faf6f7] px-2.5 py-1 text-xs font-medium text-[#655b67]"
            >
              Tool: {String(toolCall.name ?? toolCall.tool_name ?? `call_${index + 1}`)}
            </span>
          ))}
        </div>
      ) : null}
      {result.mock_mode && result.mock_reasons.length > 0 ? (
        <InlineNotice tone="warning" title="Mocked preview">
          <p>{result.mock_reasons.join(' ')}</p>
        </InlineNotice>
      ) : null}
    </div>
  );
}

function defaultPreviewMessageForBuilderConfig(config: BuilderConfig): string {
  const toolNames = config.tools.map((tool) => tool.name.toLowerCase());
  if (toolNames.some((name) => name.includes('ticket') || name.includes('refund'))) {
    return 'A customer wants a human after two failed refund attempts.';
  }
  if (toolNames.some((name) => name.includes('knowledge') || name.includes('faq'))) {
    return 'Can you answer a policy question using the knowledge base?';
  }
  return `Can you help me with ${config.agent_name}?`;
}

function navigateToEvalWorkflow(
  navigate: ReturnType<typeof useNavigate>,
  agent: AgentLibraryItem,
) {
  navigate(`/evals?agent=${encodeURIComponent(agent.id)}&new=1`, {
    state: {
      agent,
      open: 'run',
    },
  });
}

function downloadTextFile(content: string, filename: string, contentType: string): void {
  const blob = new Blob([content], { type: contentType });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.style.display = 'none';
  document.body.appendChild(anchor);
  anchor.click();
  window.setTimeout(() => {
    URL.revokeObjectURL(url);
    anchor.remove();
  }, 0);
}

function getPreviewDisabledReason({
  checkpointMode,
  recoveredLocalDraft,
  liveActionsEnabled,
}: {
  checkpointMode: boolean;
  recoveredLocalDraft: boolean;
  liveActionsEnabled: boolean;
}): string | null {
  if (checkpointMode) {
    return 'Return to the latest checkpoint before running preview against the live draft.';
  }
  if (recoveredLocalDraft) {
    return 'The live builder session is unavailable, so this recovered draft cannot run a fresh preview.';
  }
  if (!liveActionsEnabled) {
    return 'Start a draft on the left before running preview.';
  }
  return null;
}

function isMac(): boolean {
  return typeof navigator !== 'undefined' && /Mac|iPhone|iPad|iPod/.test(navigator.userAgent);
}
