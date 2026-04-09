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
  tone: 'success' | 'error' | 'info';
  message: string;
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
  const isMutating =
    saveProviderKeys.isPending || testProviderKey.isPending || setRuntimeMode.isPending;

  if (isLoading) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Setup"
          description="Workspace initialization, doctor checks, mode readiness, and MCP client status."
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
          description="Workspace initialization, doctor checks, mode readiness, and MCP client status."
        />
        <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Unable to load setup status right now.
        </div>
      </div>
    );
  }

  async function handleModeChange(nextMode: RuntimeMode) {
    if (nextMode === 'live' && !hasConfiguredKey) {
      const message = 'Add an API key above to enable live mode';
      setFeedback({ tone: 'error', message });
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
      setFeedback({ tone: 'success', message });
      toastSuccess('Mode updated', message);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unable to switch mode right now.';
      setFeedback({ tone: 'error', message });
      toastError('Mode update failed', message);
    }
  }

  async function handleTestConnection(provider: 'openai' | 'anthropic' | 'google', envName: string, label: string) {
    const enteredKey = draftKeys[envName].trim();
    const currentStatus = apiKeyStatusByName[envName];
    if (!enteredKey && !currentStatus?.configured) {
      const message = `Paste a ${label} or save one first.`;
      setFeedback({ tone: 'error', message });
      toastError('Missing API key', message);
      return;
    }

    try {
      const result = await testProviderKey.mutateAsync({
        provider,
        api_key: enteredKey || undefined,
      });
      setFeedback({ tone: 'success', message: result.message });
      toastSuccess('Connection verified', result.message);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Invalid API key.';
      setFeedback({ tone: 'error', message });
      toastError('Invalid API key', message);
    }
  }

  async function handleSaveAndTest(field: (typeof KEY_FIELDS)[number]) {
    const enteredKey = draftKeys[field.envName].trim();
    if (!enteredKey) {
      const message = `Paste a ${field.label} before saving.`;
      setFeedback({ tone: 'error', message });
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
      setFeedback({ tone: 'success', message });
      toastSuccess('Setup updated', message);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Invalid API key.';
      setFeedback({ tone: 'error', message });
      toastError('Invalid API key', message);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Setup"
        description="Workspace initialization, doctor checks, mode readiness, and MCP client status."
        actions={
          <div className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-600">
            {data.workspace.found ? 'Workspace Detected' : 'Initialization Required'}
          </div>
        }
      />

      <section className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
        <Card
          icon={<FolderGit2 className="h-4 w-4 text-sky-700" />}
          title="Workspace"
          description="Mirror the CLI init/status flow in the UI before any build or optimize work starts."
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
          description="Save provider credentials, validate them, and switch this workspace out of mock mode without restarting the server."
        >
          <MetricPill
            label="Effective Mode"
            value={data.doctor.effective_mode.toUpperCase()}
            tone={data.doctor.effective_mode === 'live' ? 'good' : 'warn'}
          />
          <MetricPill label="Preferred Mode" value={data.doctor.preferred_mode.toUpperCase()} tone="neutral" />
          <MetricPill label="Mode Source" value={data.doctor.mode_source} tone="neutral" />
          {feedback ? (
            <div
              className={classNames(
                'rounded-2xl border px-4 py-3 text-sm',
                feedback.tone === 'success' && 'border-emerald-200 bg-emerald-50 text-emerald-900',
                feedback.tone === 'error' && 'border-red-200 bg-red-50 text-red-800',
                feedback.tone === 'info' && 'border-sky-200 bg-sky-50 text-sky-800'
              )}
            >
              {feedback.message}
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
                  Save a valid provider key, then AgentLab will switch this workspace into live mode immediately.
                </p>
              </div>
              <span className="rounded-full bg-white px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                Stored in `.agentlab/.env`
              </span>
            </div>
            <div className="mt-4 space-y-3">
              {KEY_FIELDS.map((field) => {
                const status = apiKeyStatusByName[field.envName];
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
                      </div>
                      <StatusTag configured={status?.configured === true} />
                    </div>
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
          title="Doctor Findings"
          description="The same readiness checks operators run in the CLI, condensed into one view."
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
          description="Confirm the local persistence layers the CLI and UI now share."
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
          title="MCP Clients"
          description="Track whether AgentLab has been wired into the local MCP-aware tools."
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
          description="Use the same commands from the alignment report without leaving the UI context."
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
              <span className="font-medium text-slate-900">Onboarding Rule</span>
            </div>
            Get to a clean `Setup` page first, then move into `Build`, `Eval`, and `Optimize`. This mirrors the CLI product model and keeps the UI honest.
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

function StatusTag({ configured }: { configured: boolean }) {
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
