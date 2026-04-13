import {
  Activity,
  Bot,
  Database,
  FolderGit2,
  PlugZap,
  TerminalSquare,
  Wrench,
} from 'lucide-react';
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { PageHeader } from '../components/PageHeader';
import {
  useSaveProviderKeys,
  useSetRuntimeMode,
  useSetupOverview,
  useTestProviderKey,
} from '../lib/api';
import { toastError, toastSuccess } from '../lib/toast';
import { classNames } from '../lib/utils';

type RuntimeMode = 'mock' | 'auto' | 'live';

interface FeedbackState {
  tone: 'success' | 'error' | 'info' | 'warning';
  title: string;
  message: string;
  recoveryHint?: string;
}

interface SetupActionPlan {
  title: string;
  description: string;
  bullets: string[];
  ctaLabel: string;
  ctaHref: string;
}

const KEY_FIELDS = [
  {
    provider: 'google' as const,
    envName: 'GOOGLE_API_KEY',
    label: 'Google API Key',
    requestField: 'google_api_key' as const,
    helper: 'Gemini and Vertex-backed generation for AgentLab build and eval flows.',
  },
  {
    provider: 'openai' as const,
    envName: 'OPENAI_API_KEY',
    label: 'OpenAI API Key',
    requestField: 'openai_api_key' as const,
    helper: 'Use OpenAI models for live routing, build generation, and eval execution.',
  },
  {
    provider: 'anthropic' as const,
    envName: 'ANTHROPIC_API_KEY',
    label: 'Anthropic API Key',
    requestField: 'anthropic_api_key' as const,
    helper: 'Use Anthropic models for live generation, refinement, and evaluation.',
  },
];

function normalizeMode(value: string | null | undefined): RuntimeMode {
  if (value === 'auto' || value === 'live') {
    return value;
  }
  return 'mock';
}

function isRateLimitedMessage(message: string): boolean {
  const normalized = message.toLowerCase();
  return normalized.includes('429') || normalized.includes('rate limit');
}

function buildFeedbackState(
  tone: FeedbackState['tone'],
  title: string,
  message: string,
  recoveryHint?: string
): FeedbackState {
  return { tone, title, message, recoveryHint };
}

function getSetupActionPlan({
  workspaceFound,
  hasWorkingProvider,
  effectiveMode,
  feedback,
}: {
  workspaceFound: boolean;
  hasWorkingProvider: boolean;
  effectiveMode: RuntimeMode;
  feedback: FeedbackState | null;
}): SetupActionPlan {
  if (feedback?.tone === 'warning') {
    return {
      title: feedback.title,
      description: feedback.recoveryHint ?? 'Keep working in Build with simulated previews while the limit clears.',
      bullets: [
        'The key is saved and live mode is selected; the provider just needs time to recover.',
        'Retry the provider test later or switch to auto mode if you want AgentLab to fall back gracefully.',
      ],
      ctaLabel: 'Open Build',
      ctaHref: '/build',
    };
  }

  if (!workspaceFound) {
    return {
      title: 'Create the workspace first',
      description: 'Initialize the workspace in the CLI, then return here to wire in your first live provider.',
      bullets: [
        'Run `agentlab init` in your project directory.',
        'Once the workspace exists, save and test at least one provider key.',
      ],
      ctaLabel: 'Open CLI Guide',
      ctaHref: '/cli',
    };
  }

  if (!hasWorkingProvider) {
    return {
      title: 'Unlock live or mixed previews',
      description: 'Add one provider key to enable live validation. You can still draft in Build while Setup is incomplete.',
      bullets: [
        'Save and test one provider key on this page.',
        'Use Build in the meantime if you want to start shaping the agent with simulated previews.',
      ],
      ctaLabel: 'Open Build',
      ctaHref: '/build',
    };
  }

  if (effectiveMode !== 'live') {
    return {
      title: 'You are ready to keep moving',
      description: 'A provider is available. Use Build to shape the draft, then switch between live and auto as needed while you validate behavior.',
      bullets: [
        'Generate the first draft in Build.',
        'Use Save & Run Eval once the draft behavior looks right.',
      ],
      ctaLabel: 'Open Build',
      ctaHref: '/build',
    };
  }

  return {
    title: 'Setup is ready',
    description: 'Move into Build, create the first draft, and carry it directly into Eval Runs when it looks right.',
    bullets: [
      'Use Build to create or refine the draft.',
      'Save the draft before you start running evals so the next step stays deterministic.',
    ],
    ctaLabel: 'Open Build',
    ctaHref: '/build',
  };
}

export function Setup() {
  const { data, isLoading, isError } = useSetupOverview();
  const saveProviderKeys = useSaveProviderKeys();
  const testProviderKey = useTestProviderKey();
  const setRuntimeMode = useSetRuntimeMode();
  const [feedback, setFeedback] = useState<FeedbackState | null>(null);
  const [modePreference, setModePreference] = useState<RuntimeMode>('mock');
  const [draftKeys, setDraftKeys] = useState<Record<string, string>>({
    GOOGLE_API_KEY: '',
    OPENAI_API_KEY: '',
    ANTHROPIC_API_KEY: '',
  });

  useEffect(() => {
    if (!data) {
      return;
    }
    setModePreference(normalizeMode(data.doctor.preferred_mode));
  }, [data]);

  const apiKeyStatusByName = useMemo(
    () =>
      Object.fromEntries(
        ((data?.doctor.api_keys || [])).map((item) => [item.name, item])
      ),
    [data?.doctor.api_keys]
  );
  const hasConfiguredKey = (data?.doctor.api_keys || []).some((item) => item.configured);
  const hasWorkingProvider =
    hasConfiguredKey || modePreference === 'live' || feedback?.tone === 'success' || feedback?.tone === 'warning';
  const actionPlan = getSetupActionPlan({
    workspaceFound: data?.workspace.found ?? false,
    hasWorkingProvider,
    effectiveMode: modePreference,
    feedback,
  });
  const isMutating =
    saveProviderKeys.isPending || testProviderKey.isPending || setRuntimeMode.isPending;

  if (isLoading) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Setup"
          description="Connect your providers and get ready to build."
        />
        <div className="grid gap-4 lg:grid-cols-2">
          {Array.from({ length: 4 }).map((_, index) => (
            <div key={index} className="h-48 animate-pulse rounded-2xl border border-gray-200 bg-white" />
          ))}
        </div>
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Setup"
          description="Connect your providers and get ready to build."
        />
        <section className="rounded-[28px] border border-amber-200 bg-[linear-gradient(180deg,rgba(255,251,235,0.95),rgba(255,255,255,1))] px-5 py-5 shadow-sm shadow-amber-100/80">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div className="min-w-0">
              <span className="inline-flex rounded-full border border-amber-300 bg-white px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-amber-800">
                Frontend-only mode
              </span>
              <h3 className="mt-3 text-lg font-semibold text-slate-900">Setup is waiting for the AgentLab backend</h3>
              <p className="mt-2 max-w-3xl text-sm leading-relaxed text-slate-700">
                You can still draft in Build while the backend reconnects, then return here for live checks and provider setup.
              </p>
            </div>
            <div className="flex shrink-0 flex-wrap gap-2">
              <button
                type="button"
                onClick={() => window.location.reload()}
                className="rounded-xl border border-amber-300 bg-white px-4 py-2.5 text-sm font-semibold text-amber-900 transition hover:bg-amber-50"
              >
                Retry Setup
              </button>
              <Link
                to="/build"
                className="rounded-xl border border-sky-200 bg-sky-50 px-4 py-2.5 text-sm font-semibold text-sky-700 transition hover:bg-sky-100"
              >
                Open Build
              </Link>
            </div>
          </div>

          <div className="mt-5 grid gap-3 lg:grid-cols-[1.1fr_0.9fr]">
            <div className="rounded-2xl border border-amber-200 bg-white/90 px-4 py-4">
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-amber-700">Recovery plan</p>
              <div className="mt-3 space-y-2 text-sm leading-6 text-slate-700">
                <p>1. Start or restart the backend so Setup can reload workspace and provider status.</p>
                <p>2. Keep moving in Build if you want to shape the first draft before live services return.</p>
                <p>3. Come back here to validate keys, switch modes, and unlock live checks.</p>
              </div>
            </div>

            <div className="rounded-2xl border border-slate-200 bg-white/90 px-4 py-4">
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">Helpful command</p>
              <code className="mt-3 block rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 font-mono text-sm text-slate-700">
                agentlab server
              </code>
              <p className="mt-3 text-sm leading-6 text-slate-600">
                Once the backend responds again, reload this page and continue with provider setup.
              </p>
            </div>
          </div>
        </section>
      </div>
    );
  }

  async function handleModeChange(nextMode: RuntimeMode) {
    if (nextMode === 'live' && !hasConfiguredKey) {
      const message = 'Add an API key above to enable live mode';
      setFeedback(buildFeedbackState('error', 'Live mode unavailable', message));
      toastError('Live mode unavailable', message);
      return;
    }

    try {
      const result = await setRuntimeMode.mutateAsync({ mode: nextMode });
      setModePreference(normalizeMode(result.preferred_mode));
      const message =
        nextMode === 'live'
          ? 'Mode switched to live.'
          : nextMode === 'auto'
            ? 'Mode switched to auto.'
            : 'Mode switched to mock.';
      setFeedback(buildFeedbackState('success', 'Mode updated', message));
      toastSuccess('Mode updated', message);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unable to switch mode right now.';
      setFeedback(buildFeedbackState('error', 'Could not change modes', message));
      toastError('Mode update failed', message);
    }
  }

  async function handleTestConnection(provider: 'openai' | 'anthropic' | 'google', envName: string, label: string) {
    const enteredKey = draftKeys[envName].trim();
    const currentStatus = apiKeyStatusByName[envName];
    if (!enteredKey && !currentStatus?.configured) {
      const message = `Paste a ${label} or save one first.`;
      setFeedback(buildFeedbackState('error', 'Missing API key', message));
      toastError('Missing API key', message);
      return;
    }

    try {
      const result = await testProviderKey.mutateAsync({
        provider,
        api_key: enteredKey || undefined,
      });
      const feedbackState = isRateLimitedMessage(result.message)
        ? buildFeedbackState(
            'warning',
            'Provider is rate-limiting requests',
            result.message,
            'Keep working in Build with simulated previews while the limit clears.'
          )
        : buildFeedbackState('success', 'Connection verified', result.message);
      setFeedback(feedbackState);
      toastSuccess('Connection verified', result.message);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Invalid API key.';
      setFeedback(buildFeedbackState('error', 'Could not verify provider', message));
      toastError('Invalid API key', message);
    }
  }

  async function handleSaveAndTest(field: (typeof KEY_FIELDS)[number]) {
    const enteredKey = draftKeys[field.envName].trim();
    if (!enteredKey) {
      const message = `Paste a ${field.label} before saving.`;
      setFeedback(buildFeedbackState('error', 'Missing API key', message));
      toastError('Missing API key', message);
      return;
    }

    try {
      const validation = await testProviderKey.mutateAsync({
        provider: field.provider,
        api_key: enteredKey,
      });
      await saveProviderKeys.mutateAsync({
        [field.requestField]: enteredKey,
      });
      const nextMode = modePreference === 'mock' ? 'live' : modePreference;
      const result = await setRuntimeMode.mutateAsync({ mode: nextMode });
      setModePreference(normalizeMode(result.preferred_mode));
      setDraftKeys((current) => ({ ...current, [field.envName]: '' }));
      const baseMessage =
        nextMode === 'live'
          ? 'API key saved. Mode switched to live.'
          : `API key saved. Mode switched to ${nextMode}.`;
      const message =
        validation.message && validation.message !== 'Key valid.'
          ? `${baseMessage} Provider warning: ${validation.message}`
          : baseMessage;
      const feedbackState = isRateLimitedMessage(validation.message)
        ? buildFeedbackState(
            'warning',
            'Provider is rate-limiting requests',
            message,
            'Keep working in Build with simulated previews while the limit clears.'
          )
        : buildFeedbackState('success', 'Provider ready', message);
      setFeedback(feedbackState);
      toastSuccess('Setup updated', message);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Invalid API key.';
      setFeedback(buildFeedbackState('error', 'Could not save provider key', message));
      toastError('Invalid API key', message);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Setup"
        description="Connect your providers and get ready to build."
        actions={
          <div className={classNames(
            'rounded-full border px-3 py-1 text-xs font-medium',
            data.workspace.found
              ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
              : 'border-amber-200 bg-amber-50 text-amber-700'
          )}>
            {data.workspace.found ? 'Workspace ready' : 'Workspace not initialized'}
          </div>
        }
      />

      {/* Getting started guidance - surface the most important next step */}
      <section className="rounded-[28px] border border-sky-100 bg-[linear-gradient(180deg,rgba(240,249,255,0.9),rgba(255,255,255,1))] px-5 py-5 shadow-sm shadow-sky-100/60">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-sky-700">Getting started</p>
            <p className="mt-2 text-sm leading-relaxed text-sky-950">
              {!data.workspace.found
                ? 'Run `agentlab init` in your terminal to create a workspace, then add an API key below.'
                : !hasWorkingProvider
                  ? 'Add at least one API key to unlock live mode, then head to Build.'
                  : modePreference === 'live'
                    ? 'You\'re all set. Head to Build to create your first agent.'
                    : 'API key saved. Switch to live mode below, then head to Build.'}
            </p>
          </div>
          <div className="shrink-0 rounded-full border border-sky-200 bg-white px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-sky-700">
            {!data.workspace.found ? 'Step 1 of 3' : !hasWorkingProvider ? 'Step 2 of 3' : modePreference === 'live' ? 'Complete' : 'Step 3 of 3'}
          </div>
        </div>
      </section>

      <section className="rounded-[28px] border border-slate-200 bg-white px-5 py-5 shadow-sm shadow-slate-100/70">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-sky-700">What to do next</p>
            <h3 className="mt-2 text-lg font-semibold text-slate-900">{actionPlan.title}</h3>
            <p className="mt-1 text-sm leading-relaxed text-slate-600">{actionPlan.description}</p>
          </div>
          <Link
            to={actionPlan.ctaHref}
            className="inline-flex shrink-0 items-center justify-center rounded-xl border border-sky-200 bg-sky-50 px-4 py-2.5 text-sm font-semibold text-sky-700 transition hover:bg-sky-100"
          >
            {actionPlan.ctaLabel}
          </Link>
        </div>
        <div className="mt-4 grid gap-2 md:grid-cols-2">
          {actionPlan.bullets.map((bullet) => (
            <div key={bullet} className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
              {bullet}
            </div>
          ))}
        </div>
      </section>

      <section className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
        <Card
          icon={<FolderGit2 className="h-4 w-4 text-sky-700" />}
          title="Workspace"
          description="Your workspace stores agent configs, eval results, and runtime settings."
        >
          <KeyValue label="Detected" value={data.workspace.found ? 'Yes' : 'No'} />
          <KeyValue label="Label" value={data.workspace.label ?? 'Not initialized'} />
          <KeyValue label="Path" value={data.workspace.path ?? 'Run `agentlab init` to create a workspace'} />
          <KeyValue
            label="Runtime Config"
            value={data.workspace.runtime_config_path}
          />
          <KeyValue
            label="Active Config"
            value={
              data.workspace.active_config_version !== null
                ? `v${String(data.workspace.active_config_version).padStart(3, '0')}`
                : 'None'
            }
          />
        </Card>

        <Card
          icon={<Bot className="h-4 w-4 text-emerald-700" />}
          title="API Keys & Mode"
          description="Add a provider key to unlock live agent generation. AgentLab works in mock mode until a valid key is saved."
        >
          <MetricPill
            label="Current Mode"
            value={modePreference.toUpperCase()}
            tone={modePreference === 'live' ? 'good' : 'warn'}
          />
          {feedback ? (
            <div
              className={classNames(
                'rounded-2xl border px-4 py-3 text-sm',
                feedback.tone === 'success' && 'border-emerald-200 bg-emerald-50 text-emerald-900',
                feedback.tone === 'error' && 'border-red-200 bg-red-50 text-red-800',
                feedback.tone === 'info' && 'border-sky-200 bg-sky-50 text-sky-800',
                feedback.tone === 'warning' && 'border-amber-200 bg-amber-50 text-amber-900'
              )}
            >
              {feedback.tone === 'warning' ? null : <p className="font-semibold">{feedback.title}</p>}
              <p className="mt-1">{feedback.message}</p>
              {feedback.recoveryHint && feedback.tone !== 'warning' ? (
                <p className="mt-2 text-xs leading-5">{feedback.recoveryHint}</p>
              ) : null}
            </div>
          ) : null}
          <div className="grid gap-2 sm:grid-cols-3">
            {(['mock', 'auto', 'live'] as RuntimeMode[]).map((mode) => (
              <button
                key={mode}
                type="button"
                onClick={() => void handleModeChange(mode)}
                disabled={isMutating}
                aria-pressed={modePreference === mode}
                className={classNames(
                  'rounded-2xl border px-4 py-3 text-left text-sm font-medium transition',
                  modePreference === mode
                    ? 'border-slate-900 bg-slate-900 text-white'
                    : 'border-slate-200 bg-white text-slate-700 hover:border-slate-300 hover:bg-slate-50',
                  isMutating && 'cursor-not-allowed opacity-70'
                )}
              >
                {mode === 'mock' ? 'Mock mode' : mode === 'auto' ? 'Auto mode' : 'Live mode'}
              </button>
            ))}
          </div>
          <p className="rounded-2xl bg-slate-50 px-4 py-3 text-sm leading-6 text-slate-600">
            {data.doctor.message}
          </p>
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h4 className="text-sm font-semibold text-slate-900">API Keys</h4>
                <p className="mt-1 text-xs leading-5 text-slate-600">
                  Paste a provider key and hit Save & Test. AgentLab will validate it and switch to live mode automatically.
                </p>
              </div>
              <span className="rounded-full bg-white px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                Stored in `.agentlab/.env`
              </span>
            </div>
            <div className="mt-4 space-y-3">
              {KEY_FIELDS.map((field) => {
                const status = apiKeyStatusByName[field.envName];
                const detectedFromEnv =
                  status?.configured === true && status.source === 'environment';
                const statusLabel = status?.configured
                  ? status.source === 'workspace'
                    ? `Saved in workspace: ${status.masked_value}`
                    : `Detected from environment: ${status.masked_value}`
                  : 'Not configured yet.';

                return (
                  <div key={field.envName} className="rounded-2xl border border-slate-200 bg-white p-4">
                    <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                      <div className="min-w-0">
                        <label htmlFor={field.envName} className="text-sm font-semibold text-slate-900">
                          {field.label}
                        </label>
                        <p className="mt-1 text-xs leading-5 text-slate-600">{field.helper}</p>
                        <p className="mt-2 text-xs font-medium text-slate-500">{statusLabel}</p>
                        {detectedFromEnv ? (
                          <p className="mt-1 text-xs leading-5 text-emerald-700">
                            Using <code className="rounded bg-emerald-50 px-1 py-0.5 font-mono">${field.envName}</code> from shell env.
                          </p>
                        ) : null}
                      </div>
                      <StatusTag
                        configured={status?.configured === true}
                        detectedFromEnv={detectedFromEnv}
                      />
                    </div>
                    {detectedFromEnv ? null : (
                      <div className="mt-3 flex flex-col gap-3 xl:flex-row">
                        <input
                          id={field.envName}
                          type="password"
                          value={draftKeys[field.envName]}
                          onChange={(event) =>
                            setDraftKeys((current) => ({
                              ...current,
                              [field.envName]: event.target.value,
                            }))
                          }
                          placeholder={status?.masked_value ? `Saved: ${status.masked_value}` : `Paste ${field.label}`}
                          autoComplete="off"
                          className="min-w-0 flex-1 rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-900 shadow-sm outline-none transition placeholder:text-slate-400 focus:border-slate-900 focus:ring-2 focus:ring-slate-900/10"
                        />
                        <div className="flex flex-wrap gap-2">
                          <button
                            type="button"
                            onClick={() => void handleTestConnection(field.provider, field.envName, field.label)}
                            disabled={isMutating}
                            aria-label={`Test ${field.label} connection`}
                            className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
                          >
                            Test Connection
                          </button>
                          <button
                            type="button"
                            onClick={() => void handleSaveAndTest(field)}
                            disabled={isMutating}
                            aria-label={`Save & Test ${field.label}`}
                            className="rounded-xl bg-slate-900 px-3 py-2 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
                          >
                            Save & Test
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
          <div className="space-y-2">
            {data.doctor.providers.map((provider) => (
              <div
                key={`${provider.provider}-${provider.model}`}
                className="flex items-center justify-between rounded-xl border border-slate-200 px-3 py-2 text-sm"
              >
                <div>
                  <p className="font-medium text-slate-900">
                    {provider.provider}:{provider.model}
                  </p>
                  <p className="text-xs text-slate-500">{provider.api_key_env}</p>
                </div>
                <StatusTag configured={provider.configured} />
              </div>
            ))}
          </div>
        </Card>
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <Card
          icon={<Wrench className="h-4 w-4 text-amber-700" />}
          title="Readiness Checks"
          description="Issues that need attention before your workspace is fully operational."
        >
          {data.doctor.issues.length > 0 ? (
            <div className="space-y-2">
              {data.doctor.issues.map((issue) => (
                <div key={issue} className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                  {issue}
                </div>
              ))}
            </div>
          ) : (
            <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
              No blocking setup issues detected.
            </div>
          )}
        </Card>

        <Card
          icon={<Database className="h-4 w-4 text-violet-700" />}
          title="Data Stores"
          description="Local databases that store your eval results, configs, and agent history."
        >
          <div className="space-y-2">
            {data.doctor.data_stores.map((store) => (
              <div
                key={store.name}
                className="rounded-xl border border-slate-200 px-3 py-3"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm font-medium capitalize text-slate-900">
                      {store.name.replaceAll('_', ' ')}
                    </p>
                    <p className="mt-1 truncate font-mono text-xs text-slate-500">{store.path}</p>
                  </div>
                  <StatusTag configured={store.exists} />
                </div>
                <p className="mt-2 text-xs text-slate-500">
                  {store.row_count === null ? 'Not a SQLite store or not initialized yet.' : `${store.row_count} rows`}
                </p>
              </div>
            ))}
          </div>
        </Card>
      </section>

      <section className="grid gap-4 xl:grid-cols-[1fr_0.9fr]">
        <Card
          icon={<PlugZap className="h-4 w-4 text-fuchsia-700" />}
          title="Connected Tools"
          description="External tools and editors that can interact with AgentLab."
        >
          <div className="space-y-2">
            {data.mcp_clients.map((client) => (
              <div key={client.name} className="rounded-xl border border-slate-200 px-3 py-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-slate-900">{client.name}</p>
                    <p className="mt-1 truncate font-mono text-xs text-slate-500">{client.path}</p>
                  </div>
                  <StatusTag configured={client.configured} />
                </div>
              </div>
            ))}
          </div>
        </Card>

        <Card
          icon={<TerminalSquare className="h-4 w-4 text-slate-700" />}
          title="CLI Shortcuts"
          description="Handy terminal commands you can run alongside the UI."
        >
          <div className="space-y-2">
            {data.recommended_commands.map((command) => (
              <div key={command} className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 font-mono text-sm text-slate-700">
                {command}
              </div>
            ))}
          </div>
          <div className="mt-4 rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
            <div className="mb-2 flex items-center gap-2">
              <Activity className="h-4 w-4 text-slate-400" />
              <span className="font-medium text-slate-900">Recommended flow</span>
            </div>
            Finish Setup first, then move to Build, Eval, and Optimize in order.
          </div>
        </Card>
      </section>
    </div>
  );
}

function Card({
  icon,
  title,
  description,
  children,
}: {
  icon: ReactNode;
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-[28px] border border-slate-200 bg-white p-5 shadow-sm shadow-slate-100/70">
      <div className="mb-4 flex items-start gap-3">
        <div className="rounded-2xl bg-slate-100 p-2">{icon}</div>
        <div>
          <h3 className="text-base font-semibold text-slate-900">{title}</h3>
          <p className="mt-1 text-sm leading-6 text-slate-600">{description}</p>
        </div>
      </div>
      <div className="space-y-3">{children}</div>
    </section>
  );
}

function KeyValue({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-200 px-3 py-2">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">{label}</p>
      <p className="mt-2 break-all text-sm text-slate-800">{value}</p>
    </div>
  );
}

function StatusTag({
  configured,
  detectedFromEnv = false,
}: {
  configured: boolean;
  detectedFromEnv?: boolean;
}) {
  if (detectedFromEnv) {
    return (
      <span className="rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-medium text-emerald-800">
        Detected from environment
      </span>
    );
  }
  return (
    <span
      className={classNames(
        'rounded-full px-2.5 py-1 text-xs font-medium',
        configured ? 'bg-emerald-100 text-emerald-800' : 'bg-slate-100 text-slate-600'
      )}
    >
      {configured ? 'Ready' : 'Pending'}
    </span>
  );
}

function MetricPill({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: 'good' | 'warn' | 'neutral';
}) {
  return (
    <div
      className={classNames(
        'rounded-2xl border px-4 py-3',
        tone === 'good' && 'border-emerald-200 bg-emerald-50',
        tone === 'warn' && 'border-amber-200 bg-amber-50',
        tone === 'neutral' && 'border-slate-200 bg-slate-50'
      )}
    >
      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">{label}</p>
      <p className="mt-2 text-sm font-medium text-slate-900">{value}</p>
    </div>
  );
}
