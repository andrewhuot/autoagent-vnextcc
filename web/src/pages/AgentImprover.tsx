import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  ArrowRight,
  Bot,
  Braces,
  CheckCircle2,
  Copy,
  Download,
  LayoutPanelLeft,
  Play,
  Send,
  ShieldCheck,
  Sparkles,
  WandSparkles,
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
import { toastError, toastSuccess } from '../lib/toast';
import type { AgentLibraryItem, BuildPreviewResult, BuildSaveResult } from '../lib/types';
import { classNames } from '../lib/utils';

type InspectorMode = 'summary' | 'config' | 'preview';
type ConfigFormat = 'yaml' | 'json';

interface ImproverStep {
  label: string;
  status: 'complete' | 'current' | 'upcoming';
}

const SESSION_STORAGE_KEY = 'agentlab.agent-improver.session-id';

const IMPROVEMENT_EXAMPLES: string[] = [
  'Improve the escalation path so the handoff includes the customer’s last two actions.',
  'Tighten the refund workflow so damaged-item claims always request photo evidence first.',
  'Add calmer tone guidance for high-friction conversations and make the closing summary more concise.',
  'Strengthen the safety policy so the agent refuses account changes before verification succeeds.',
];

const INSPECTOR_MODES: Array<{ id: InspectorMode; label: string; description: string }> = [
  { id: 'summary', label: 'Summary', description: 'Readable draft overview' },
  { id: 'config', label: 'Config', description: 'Inspectable YAML or JSON' },
  { id: 'preview', label: 'Preview', description: 'Behavior test harness' },
];

const SHELL_RAIL_ITEMS: Array<{ label: string; icon: ReactNode }> = [
  { label: 'Workspace', icon: <LayoutPanelLeft className="h-4 w-4" /> },
  { label: 'Improve', icon: <WandSparkles className="h-4 w-4" /> },
  { label: 'Inspect', icon: <Braces className="h-4 w-4" /> },
  { label: 'Trust', icon: <ShieldCheck className="h-4 w-4" /> },
];

/**
 * Provides a focused, truthful improvement workspace on top of the existing builder session APIs.
 * This keeps the new surface real without refactoring the broader Build page.
 */
export function AgentImprover() {
  const navigate = useNavigate();
  const { setActiveAgent } = useActiveAgent();
  const saveAgent = useSaveAgent();

  const [composer, setComposer] = useState<string>('');
  const [session, setSession] = useState<BuilderSessionPayload | null>(null);
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
  const conversationRef = useRef<HTMLDivElement | null>(null);

  const busy: boolean = requestPending || savePending || previewPending;
  const latestUserRequest: string = useMemo(() => {
    const userMessage = [...(session?.messages ?? [])].reverse().find((message) => message.role === 'user');
    return userMessage?.content ?? 'No request submitted yet.';
  }, [session?.messages]);
  const yamlPreview: string = session?.config ? builderConfigToYaml(session.config) : '';
  const jsonPreview: string = session?.config ? JSON.stringify(session.config, null, 2) : '';
  const configPreview: string = configFormat === 'yaml' ? yamlPreview : jsonPreview;
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
    document.title = 'Agent Improver • AgentLab';
  }, []);

  useEffect(() => {
    const storedSessionId = readStoredSessionId();
    if (!storedSessionId) {
      setSessionHydrating(false);
      return;
    }

    let cancelled = false;
    setSessionHydrating(true);

    void getBuilderSession(storedSessionId)
      .then((storedSession) => {
        if (cancelled) {
          return;
        }
        setSession(storedSession);
        setPreviewMessage(defaultPreviewMessageForBuilderConfig(storedSession.config));
      })
      .catch(() => {
        clearStoredSessionId();
      })
      .finally(() => {
        if (!cancelled) {
          setSessionHydrating(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!session?.session_id) {
      return;
    }
    persistSessionId(session.session_id);
  }, [session?.session_id]);

  useEffect(() => {
    if (!session?.config || previewMessage.trim()) {
      return;
    }
    setPreviewMessage(defaultPreviewMessageForBuilderConfig(session.config));
  }, [previewMessage, session?.config, session?.updated_at]);

  useEffect(() => {
    const container = conversationRef.current;
    if (!container) {
      return;
    }
    container.scrollTop = container.scrollHeight;
  }, [session?.messages]);

  async function handleSendRequest(): Promise<void> {
    const message = composer.trim();
    if (!message || requestPending) {
      return;
    }

    setRequestPending(true);
    setError(null);

    try {
      const nextSession = await sendBuilderMessage({
        message,
        session_id: session?.session_id,
      });
      setSession(nextSession);
      setComposer('');
      setPreviewResult(null);
      setSaveResult(null);
      setSavedAgent(null);
      setInspectorMode('summary');
    } catch (submitError) {
      const messageText =
        submitError instanceof Error ? submitError.message : 'The improver request failed.';
      setError(messageText);
      toastError('Agent improver request failed', messageText);
    } finally {
      setRequestPending(false);
    }
  }

  async function handleRunPreview(): Promise<void> {
    const message = previewMessage.trim();
    if (!session?.session_id || !message || previewPending) {
      return;
    }

    setPreviewPending(true);
    setError(null);

    try {
      const result = await previewBuilderSession({
        session_id: session.session_id,
        message,
      });
      setPreviewResult(result);
      setInspectorMode('preview');
    } catch (previewError) {
      const messageText =
        previewError instanceof Error ? previewError.message : 'The preview request failed.';
      setError(messageText);
      toastError('Preview failed', messageText);
    } finally {
      setPreviewPending(false);
    }
  }

  async function handleSaveDraft(): Promise<void> {
    if (!session?.session_id || savePending) {
      return;
    }

    setSavePending(true);
    setError(null);

    try {
      const payload = await saveAgent.mutateAsync({
        source: 'built',
        build_source: 'builder_chat',
        session_id: session.session_id,
      });

      if (!payload.save_result) {
        throw new Error('The save response did not include workspace metadata.');
      }

      setSaveResult(payload.save_result);
      setSavedAgent(payload.agent);
      setActiveAgent(payload.agent);
      toastSuccess('Saved to workspace', payload.save_result.config_path);
    } catch (saveError) {
      const messageText = saveError instanceof Error ? saveError.message : 'Saving the draft failed.';
      setError(messageText);
      toastError('Save failed', messageText);
    } finally {
      setSavePending(false);
    }
  }

  async function handleContinueToEval(): Promise<void> {
    if (savedAgent) {
      navigateToEvalWorkflow(navigate, savedAgent);
      return;
    }

    await handleSaveDraft();
  }

  async function handleCopyDraft(): Promise<void> {
    if (!configPreview || !navigator.clipboard?.writeText) {
      return;
    }

    try {
      await navigator.clipboard.writeText(configPreview);
      toastSuccess('Draft copied', `Copied the ${configFormat.toUpperCase()} draft to your clipboard.`);
    } catch (copyError) {
      const messageText = copyError instanceof Error ? copyError.message : 'Copy failed.';
      setError(messageText);
      toastError('Copy failed', messageText);
    }
  }

  async function handleDownloadDraft(): Promise<void> {
    if (!session?.session_id) {
      return;
    }

    try {
      const payload = await exportBuilderConfig({
        session_id: session.session_id,
        format: configFormat,
      });
      const blob = new Blob([payload.content], { type: payload.content_type });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = payload.filename;
      anchor.style.display = 'none';
      document.body.appendChild(anchor);
      anchor.click();
      window.setTimeout(() => {
        URL.revokeObjectURL(url);
        anchor.remove();
      }, 0);
      toastSuccess('Draft exported', payload.filename);
    } catch (downloadError) {
      const messageText =
        downloadError instanceof Error ? downloadError.message : 'Downloading the draft failed.';
      setError(messageText);
      toastError('Download failed', messageText);
    }
  }

  return (
    <div className="relative overflow-hidden rounded-[38px] bg-[radial-gradient(circle_at_top_left,rgba(245,236,244,0.96),rgba(235,231,239,0.82)_38%,rgba(228,225,236,0.78)_100%)] p-3 sm:p-5">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-40 bg-[radial-gradient(circle_at_top,rgba(255,255,255,0.78),transparent_70%)]" />
      <div className="pointer-events-none absolute -right-20 top-10 h-56 w-56 rounded-full bg-[rgba(220,197,205,0.24)] blur-3xl" />
      <div className="pointer-events-none absolute bottom-4 left-10 h-48 w-48 rounded-full bg-[rgba(214,208,228,0.26)] blur-3xl" />

      <div className="relative rounded-[34px] border border-white/70 bg-[#f8f3f0]/90 p-3 shadow-[0_24px_80px_rgba(74,54,82,0.16)] backdrop-blur-xl sm:p-4">
        <div className="rounded-[28px] border border-white/80 bg-white/70 px-4 py-4 shadow-[0_10px_30px_rgba(87,64,88,0.08)]">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.22em] text-[#756c78]">
                <span>Build</span>
                <span className="text-[#bbb2bc]">/</span>
                <span>Agent Improver</span>
              </div>
              <h1 className="mt-2 text-2xl font-semibold tracking-[-0.03em] text-[#1f1b23]">
                Agent Improver
              </h1>
              <p className="mt-1 max-w-2xl text-sm leading-6 text-[#615867]">
                Improvement workspace for shaping a fresh builder session through natural-language edits,
                inspecting the draft clearly, and validating behavior before you save it back into AgentLab.
              </p>
            </div>

            <ol className="flex flex-wrap gap-2">
              {steps.map((step) => (
                <li key={step.label}>
                  <span
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
                      {step.label.slice(0, 1)}
                    </span>
                    {step.label}
                  </span>
                </li>
              ))}
            </ol>

            <div className="flex flex-wrap items-center gap-2">
              <Link
                to="/build?tab=builder-chat"
                className="inline-flex items-center gap-2 rounded-full border border-[#ddd4da] bg-white/80 px-3.5 py-2 text-sm font-medium text-[#4d4550] transition hover:bg-white"
              >
                Open Build
              </Link>
              <Link
                to="/setup"
                className="inline-flex items-center gap-2 rounded-full border border-[#ead3d7] bg-[#fbf1f2] px-3.5 py-2 text-sm font-medium text-[#7c5664] transition hover:bg-[#f9e8eb]"
              >
                Setup
              </Link>
            </div>
          </div>
        </div>

        <div className="mt-3 grid gap-3 xl:grid-cols-[54px_minmax(0,0.92fr)_minmax(0,1.08fr)]">
          <aside className="hidden flex-col items-center gap-3 rounded-[28px] border border-white/70 bg-[#f3eeef]/85 px-2 py-4 xl:flex">
            {SHELL_RAIL_ITEMS.map((item, index) => (
              <div
                key={item.label}
                className={classNames(
                  'flex w-full flex-col items-center gap-2 rounded-[20px] px-2 py-3 text-center text-[10px] font-medium tracking-[0.14em]',
                  index === 1
                    ? 'bg-white text-[#4a3944] shadow-sm'
                    : 'text-[#8a8088]'
                )}
              >
                <span
                  className={classNames(
                    'flex h-9 w-9 items-center justify-center rounded-2xl border',
                    index === 1
                      ? 'border-[#e4d5dc] bg-[#fbf5f6] text-[#7d5360]'
                      : 'border-transparent bg-white/70 text-[#8a8088]'
                  )}
                >
                  {item.icon}
                </span>
                <span className="leading-4">{item.label}</span>
              </div>
            ))}
          </aside>

          <section className="flex min-h-[760px] flex-col overflow-hidden rounded-[30px] border border-white/70 bg-[#fbf7f4]/90 shadow-[0_12px_30px_rgba(83,63,79,0.08)]">
            <div className="border-b border-[#e7dde2] px-5 py-5">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#8a8087]">
                    Improvement workspace
                  </p>
                  <h2 className="mt-2 text-xl font-semibold tracking-[-0.02em] text-[#1f1b23]">
                    Describe the next improvement in plain language
                  </h2>
                  <p className="mt-2 max-w-xl text-sm leading-6 text-[#625967]">
                    The improver uses the live builder session contract. It keeps the draft on the
                    right in sync with each request and makes any mock-backed behavior explicit.
                  </p>
                </div>
                <span
                  className={classNames(
                    'inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium',
                    session?.mock_mode
                      ? 'border-amber-200 bg-amber-50 text-amber-800'
                      : session?.session_id
                        ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
                        : 'border-[#d9cfd6] bg-white/80 text-[#6c636d]'
                  )}
                >
                  <Sparkles className="h-3.5 w-3.5" />
                  {session?.session_id
                    ? session.mock_mode
                      ? 'Fallback session'
                      : 'Live session'
                    : 'Fresh session'}
                </span>
              </div>

              <div className="mt-4 space-y-3">
                <div className="rounded-[24px] border border-[#e7dde2] bg-white/85 p-4">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#8a8087]">
                    Seed the draft
                  </p>
                  <p className="mt-2 text-sm leading-6 text-[#5e5662]">
                    Start with the smallest useful improvement request. The session grows from that
                    brief and stays inspectable in summary, config, and preview modes.
                  </p>
                  <div className="mt-4 grid gap-2 sm:grid-cols-2">
                    {IMPROVEMENT_EXAMPLES.map((example) => (
                      <button
                        key={example}
                        type="button"
                        onClick={() => setComposer(example)}
                        className="rounded-[18px] border border-[#e4d8de] bg-[#fbf7f8] px-3 py-3 text-left text-xs leading-5 text-[#625967] transition hover:border-[#d4c4cc] hover:bg-white"
                      >
                        {example}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="rounded-[24px] border border-[#eadfce] bg-[#fffaf3] p-4">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#93816d]">
                    Truthful limits
                  </p>
                  <p className="mt-2 text-sm leading-6 text-[#685d50]">
                    This surface starts a fresh builder-backed draft today. It does not yet reopen an
                    already-saved workspace config directly into the improver session.
                  </p>
                </div>
              </div>
            </div>

            <div
              ref={conversationRef}
              className="flex-1 space-y-4 overflow-y-auto px-5 py-5"
            >
              {sessionHydrating ? (
                <EmptyWorkspaceCard
                  title="Restoring your last improver draft"
                  body="If a prior builder-backed improver session exists in this browser session, it will reappear here automatically."
                />
              ) : null}

              {!sessionHydrating && !session?.session_id ? (
                <ConversationMessage
                  role="assistant"
                  title="Improver"
                  body="Describe the update you want. I will evolve the draft, keep the config inspectable, and let you test the behavior before you save."
                />
              ) : null}

              {(session?.messages ?? []).map((message) => (
                <ConversationMessage
                  key={message.message_id}
                  role={message.role}
                  title={message.role === 'user' ? 'Request' : 'Improver'}
                  body={message.content}
                />
              ))}

              {error ? (
                <InlineNotice tone="error" title="Something needs attention">
                  {error}
                </InlineNotice>
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
                  className="min-h-[110px] w-full resize-none bg-transparent px-3 py-3 text-sm leading-6 text-[#211d24] outline-none placeholder:text-[#9b929a]"
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' && !event.shiftKey) {
                      event.preventDefault();
                      void handleSendRequest();
                    }
                  }}
                />
                <div className="flex flex-col gap-3 border-t border-[#f0e8eb] px-3 pt-3 sm:flex-row sm:items-center sm:justify-between">
                  <p className="text-xs leading-5 text-[#817781]">
                    Ask for routing changes, new tools, policy refinements, tone updates, or safer behavior.
                  </p>
                  <button
                    type="button"
                    onClick={() => void handleSendRequest()}
                    disabled={!composer.trim() || busy}
                    className="inline-flex items-center justify-center gap-2 rounded-full bg-[#2a242d] px-4 py-2.5 text-sm font-medium text-white transition hover:bg-[#1f1a22] disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    <Send className="h-4 w-4" />
                    {requestPending ? 'Updating draft...' : 'Send request'}
                  </button>
                </div>
              </div>
            </div>
          </section>

          <section className="flex min-h-[760px] flex-col overflow-hidden rounded-[30px] border border-white/70 bg-[#fffdfb]/92 shadow-[0_12px_30px_rgba(83,63,79,0.08)]">
            <div className="border-b border-[#ede4e8] px-5 py-5">
              <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#8a8087]">
                    Current draft
                  </p>
                  <h2 className="mt-2 text-xl font-semibold tracking-[-0.02em] text-[#1f1b23]">
                    Inspect the draft from three angles
                  </h2>
                  <p className="mt-2 max-w-xl text-sm leading-6 text-[#625967]">
                    Summary keeps the draft readable, Config keeps it trustworthy, and Preview
                    validates the behavior against the same builder session.
                  </p>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  {session?.session_id ? (
                    <button
                      type="button"
                      onClick={() => void handleSaveDraft()}
                      disabled={busy}
                      className="inline-flex items-center gap-2 rounded-full border border-[#ded5db] bg-white px-3.5 py-2 text-sm font-medium text-[#4d4550] transition hover:bg-[#faf7f8] disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      <CheckCircle2 className="h-4 w-4" />
                      {savePending ? 'Saving...' : 'Save draft'}
                    </button>
                  ) : null}
                  <button
                    type="button"
                    onClick={() => void handleContinueToEval()}
                    disabled={!session?.session_id || busy}
                    className="inline-flex items-center gap-2 rounded-full border border-[#ecd8dc] bg-[#fbf3f4] px-3.5 py-2 text-sm font-medium text-[#7b5663] transition hover:bg-[#f8eaed] disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    Continue to Eval
                    <ArrowRight className="h-4 w-4" />
                  </button>
                </div>
              </div>

              <div className="mt-4 inline-flex rounded-full border border-[#e5dbe0] bg-[#f8f4f6] p-1">
                {INSPECTOR_MODES.map((mode) => (
                  <button
                    key={mode.id}
                    type="button"
                    role="tab"
                    aria-selected={inspectorMode === mode.id}
                    onClick={() => setInspectorMode(mode.id)}
                    className={classNames(
                      'rounded-full px-4 py-2 text-sm font-medium transition',
                      inspectorMode === mode.id
                        ? 'bg-white text-[#1f1b23] shadow-sm'
                        : 'text-[#7f747f] hover:text-[#3a333d]'
                    )}
                  >
                    {mode.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex-1 overflow-y-auto px-5 py-5">
              {inspectorMode === 'summary' ? (
                <SummaryMode
                  session={session}
                  latestUserRequest={latestUserRequest}
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
                />
              ) : null}

              {inspectorMode === 'preview' ? (
                <PreviewMode
                  session={session}
                  previewMessage={previewMessage}
                  previewPending={previewPending}
                  previewResult={previewResult}
                  onPreviewMessageChange={setPreviewMessage}
                  onRunPreview={() => void handleRunPreview()}
                />
              ) : null}
            </div>

            <div className="border-t border-[#ede4e8] bg-[#fffaf7] px-5 py-4">
              {saveResult ? (
                <InlineNotice tone="success" title="Saved to workspace">
                  {saveResult.config_path}
                </InlineNotice>
              ) : session?.mock_mode && session.mock_reason ? (
                <InlineNotice tone="warning" title="Preview mode">
                  {session.mock_reason}
                </InlineNotice>
              ) : (
                <p className="text-xs leading-5 text-[#847986]">
                  Save the draft when the summary feels right, the config looks trustworthy, and the
                  preview behavior matches the intent.
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
}: {
  session: BuilderSessionPayload | null;
  latestUserRequest: string;
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

  return (
    <div className="space-y-4">
      <div className="rounded-[26px] border border-[#e9dee4] bg-[#fbf7f4] p-5">
        <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
          <div className="min-w-0">
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#8a8087]">
              Agent card
            </p>
            <h3 className="mt-2 text-2xl font-semibold tracking-[-0.03em] text-[#1f1b23]">
              {config.agent_name}
            </h3>
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
          <SummaryPill label={`${session.stats.tool_count} tool${session.stats.tool_count === 1 ? '' : 's'}`} />
          <SummaryPill label={`${session.stats.policy_count} policy${session.stats.policy_count === 1 ? '' : 'ies'}`} />
          <SummaryPill label={`${session.stats.routing_rule_count} route${session.stats.routing_rule_count === 1 ? '' : 's'}`} />
          <SummaryPill label={session.evals ? `${session.evals.case_count} draft evals` : 'No eval draft yet'} />
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.1fr)_minmax(280px,0.9fr)]">
        <SummaryPanel eyebrow="Latest request" title="What changed most recently">
          <p className="text-sm leading-6 text-[#554d59]">{latestUserRequest}</p>
        </SummaryPanel>

        <SummaryPanel eyebrow="Trust cues" title="Why this draft is inspectable">
          <ul className="space-y-2 text-sm leading-6 text-[#554d59]">
            <li>Each request updates the same builder session.</li>
            <li>The raw config stays viewable in YAML or JSON.</li>
            <li>The preview mode exercises the current draft directly.</li>
          </ul>
        </SummaryPanel>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <SummaryListPanel
          eyebrow="Tools"
          title={`${config.tools.length} active capability${config.tools.length === 1 ? '' : 'ies'}`}
          items={config.tools.map((tool) => `${tool.name}: ${tool.description}`)}
        />
        <SummaryListPanel
          eyebrow="Routing"
          title={`${config.routing_rules.length} decision path${config.routing_rules.length === 1 ? '' : 's'}`}
          items={config.routing_rules.map((rule) => `${rule.intent}: ${rule.description}`)}
        />
        <SummaryListPanel
          eyebrow="Policies"
          title={`${config.policies.length} operating guardrail${config.policies.length === 1 ? '' : 's'}`}
          items={config.policies.map((policy) => `${policy.name}: ${policy.description}`)}
        />
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
}: {
  config: BuilderConfig | null;
  activeFormat: ConfigFormat;
  content: string;
  onFormatChange: (format: ConfigFormat) => void;
  onCopy: () => void;
  onDownload: () => void;
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
  onPreviewMessageChange,
  onRunPreview,
}: {
  session: BuilderSessionPayload | null;
  previewMessage: string;
  previewPending: boolean;
  previewResult: BuildPreviewResult | null;
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
            {session.mock_mode ? 'Builder fallback mode' : 'Builder live mode'}
          </span>
        </div>
      </div>

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
          className="mt-3 min-h-[128px] w-full resize-none rounded-[22px] border border-[#e5dbe0] bg-[#fcfaf9] px-4 py-3 text-sm leading-6 text-[#211d24] outline-none transition focus:border-[#d2c0c7] focus:ring-4 focus:ring-[#f3e8ec]"
        />

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={onRunPreview}
            disabled={!previewMessage.trim() || previewPending}
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
    <div className={classNames('rounded-[22px] border px-4 py-3 text-sm', toneClasses)}>
      <p className="font-semibold">{title}</p>
      <div className="mt-1 leading-6">{children}</div>
    </div>
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
          {result.mock_reasons.join(' ')}
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

function builderConfigToYaml(config: BuilderConfig): string {
  const lines: string[] = [
    `agent_name: ${config.agent_name}`,
    `model: ${config.model}`,
    '',
    'system_prompt: |',
    ...config.system_prompt.split('\n').map((line) => `  ${line}`),
    '',
    'tools:',
  ];

  for (const tool of config.tools) {
    lines.push(`  - name: ${tool.name}`);
    lines.push(`    description: ${tool.description}`);
    lines.push(`    when_to_use: ${JSON.stringify(tool.when_to_use)}`);
  }

  lines.push('', 'routing_rules:');
  for (const rule of config.routing_rules) {
    lines.push(`  - name: ${rule.name}`);
    lines.push(`    intent: ${rule.intent}`);
    lines.push(`    description: ${JSON.stringify(rule.description)}`);
  }

  lines.push('', 'policies:');
  for (const policy of config.policies) {
    lines.push(`  - name: ${policy.name}`);
    lines.push(`    description: ${JSON.stringify(policy.description)}`);
  }

  lines.push('', 'eval_criteria:');
  for (const criterion of config.eval_criteria) {
    lines.push(`  - name: ${criterion.name}`);
    lines.push(`    description: ${JSON.stringify(criterion.description)}`);
  }

  lines.push('', 'metadata:');
  const metadataEntries = Object.entries(config.metadata ?? {});
  if (metadataEntries.length === 0) {
    lines.push('  {}');
  } else {
    for (const [key, value] of metadataEntries) {
      lines.push(`  ${key}: ${JSON.stringify(value)}`);
    }
  }

  return lines.join('\n');
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

function readStoredSessionId(): string | null {
  try {
    return window.sessionStorage.getItem(SESSION_STORAGE_KEY);
  } catch {
    return null;
  }
}

function persistSessionId(sessionId: string): void {
  try {
    window.sessionStorage.setItem(SESSION_STORAGE_KEY, sessionId);
  } catch {
    // Ignore storage availability failures.
  }
}

function clearStoredSessionId(): void {
  try {
    window.sessionStorage.removeItem(SESSION_STORAGE_KEY);
  } catch {
    // Ignore storage availability failures.
  }
}
