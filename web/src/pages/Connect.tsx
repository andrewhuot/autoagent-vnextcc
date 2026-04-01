import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowUpRight,
  Bot,
  Check,
  ChevronDown,
  ChevronUp,
  Cloud,
  FileJson,
  Globe,
  Network,
  Plug2,
} from 'lucide-react';

import { PageHeader } from '../components/PageHeader';
import { useConnectImport } from '../lib/api';
import { getSidebarMode, SIDEBAR_MODE_EVENT, type SidebarMode } from '../lib/navigation';
import { toastError, toastSuccess } from '../lib/toast';
import type {
  ConnectAdapter,
  ConnectImportRequest,
  ConnectImportResult,
  ConnectRuntimeMode,
} from '../lib/types';

interface GoogleImportOption {
  href: string;
  title: string;
  description: string;
  icon: typeof Cloud;
  eyebrow: string;
  cta: string;
  gradientClassName: string;
}

interface ConnectSourceOption {
  adapter: ConnectAdapter;
  label: string;
  description: string;
  icon: typeof Bot;
  fieldLabel: string;
  placeholder: string;
  helpText: string;
}

const GOOGLE_IMPORT_OPTIONS: GoogleImportOption[] = [
  {
    href: '/cx/studio',
    title: 'Import from CX Agent Studio',
    description: 'Import an existing Dialogflow CX agent.',
    icon: Cloud,
    eyebrow: 'Google Cloud',
    cta: 'Open CX Studio',
    gradientClassName: 'from-sky-50 via-white to-emerald-50',
  },
  {
    href: '/adk/import',
    title: 'Import from Google ADK',
    description: 'Import an Agent Development Kit project.',
    icon: Network,
    eyebrow: 'Google ADK',
    cta: 'Open ADK Import',
    gradientClassName: 'from-emerald-50 via-white to-sky-50',
  },
];

const CONNECT_SOURCES: ConnectSourceOption[] = [
  {
    adapter: 'openai-agents',
    label: 'OpenAI Agents',
    description: 'Scan a Python project for Agent() definitions, tools, handoffs, and guardrails.',
    icon: Bot,
    fieldLabel: 'Project path',
    placeholder: '/path/to/openai-agents/project',
    helpText: 'Point at the root of the Python project that defines your OpenAI Agents runtime.',
  },
  {
    adapter: 'anthropic',
    label: 'Anthropic Claude',
    description: 'Import Anthropic SDK prompts, tools, MCP references, and session patterns.',
    icon: Plug2,
    fieldLabel: 'Project path',
    placeholder: '/path/to/anthropic/project',
    helpText: 'Point at the project directory that contains Anthropic SDK code or MCP configuration.',
  },
  {
    adapter: 'http',
    label: 'HTTP Webhook',
    description: 'Wrap an existing agent API behind a lightweight AgentLab adapter workspace.',
    icon: Globe,
    fieldLabel: 'Runtime URL',
    placeholder: 'https://agent.example.com',
    helpText: 'Use the primary webhook or REST endpoint that fronts the runtime you want to connect.',
  },
  {
    adapter: 'transcript',
    label: 'Transcript Import',
    description: 'Turn JSONL conversations into an imported runtime spec with starter eval fixtures.',
    icon: FileJson,
    fieldLabel: 'Transcript file',
    placeholder: '/path/to/conversations.jsonl',
    helpText: 'Provide a JSONL export of prior conversations so AgentLab can build starter eval cases.',
  },
];

const RUNTIME_MODE_OPTIONS: Array<{ value: ConnectRuntimeMode; label: string; help: string }> = [
  {
    value: 'mock',
    label: 'Mock',
    help: 'Create the workspace in safe demo mode first.',
  },
  {
    value: 'live',
    label: 'Live',
    help: 'Prepare the workspace for real runtime execution immediately.',
  },
  {
    value: 'auto',
    label: 'Auto',
    help: 'Let AgentLab choose the runtime mode from the imported source.',
  },
];

function GoogleCloudMark() {
  return (
    <div className="flex items-center gap-1.5" aria-hidden="true">
      <span className="h-2.5 w-2.5 rounded-full bg-sky-500" />
      <span className="h-2.5 w-2.5 rounded-full bg-emerald-500" />
      <span className="h-2.5 w-2.5 rounded-full bg-amber-400" />
      <span className="h-2.5 w-2.5 rounded-full bg-rose-500" />
    </div>
  );
}

function buildPayload(
  adapter: ConnectAdapter,
  sourceValue: string,
  workspaceName: string,
  outputDir: string,
  runtimeMode: ConnectRuntimeMode
): ConnectImportRequest {
  const trimmedSource = sourceValue.trim();
  const payload: ConnectImportRequest = {
    adapter,
    runtime_mode: runtimeMode,
  };

  if (workspaceName.trim()) {
    payload.workspace_name = workspaceName.trim();
  }
  if (outputDir.trim()) {
    payload.output_dir = outputDir.trim();
  }

  if (adapter === 'http') {
    payload.url = trimmedSource;
  } else if (adapter === 'transcript') {
    payload.file = trimmedSource;
  } else {
    payload.path = trimmedSource;
  }

  return payload;
}

function summaryLabel(result: ConnectImportResult): string {
  return CONNECT_SOURCES.find((source) => source.adapter === result.adapter)?.label ?? result.adapter;
}

export function Connect() {
  const [step, setStep] = useState(1);
  const [sidebarMode, setSidebarMode] = useState<SidebarMode>(() => getSidebarMode());
  const [showSecondaryAdapters, setShowSecondaryAdapters] = useState(() => getSidebarMode() === 'pro');
  const [selectedAdapter, setSelectedAdapter] = useState<ConnectAdapter | null>(null);
  const [sourceValue, setSourceValue] = useState('');
  const [workspaceName, setWorkspaceName] = useState('');
  const [outputDir, setOutputDir] = useState('');
  const [runtimeMode, setRuntimeMode] = useState<ConnectRuntimeMode>('mock');

  const connectMutation = useConnectImport();
  const isProMode = sidebarMode === 'pro';
  const selectedSource = useMemo(
    () => CONNECT_SOURCES.find((source) => source.adapter === selectedAdapter) ?? null,
    [selectedAdapter]
  );

  useEffect(() => {
    const syncSidebarMode = () => setSidebarMode(getSidebarMode());

    window.addEventListener(SIDEBAR_MODE_EVENT, syncSidebarMode as EventListener);
    window.addEventListener('storage', syncSidebarMode);

    return () => {
      window.removeEventListener(SIDEBAR_MODE_EVENT, syncSidebarMode as EventListener);
      window.removeEventListener('storage', syncSidebarMode);
    };
  }, []);

  useEffect(() => {
    if (isProMode) {
      setShowSecondaryAdapters(true);
    }
  }, [isProMode]);

  function handleSelectAdapter(adapter: ConnectAdapter) {
    setStep(1);
    setSelectedAdapter(adapter);
    setShowSecondaryAdapters(true);
    setSourceValue('');
  }

  function handleSubmit() {
    if (!selectedAdapter || !sourceValue.trim()) {
      return;
    }

    const payload = buildPayload(
      selectedAdapter,
      sourceValue,
      workspaceName,
      outputDir,
      runtimeMode
    );

    connectMutation.mutate(payload, {
      onSuccess: (result) => {
        toastSuccess(
          'Workspace created',
          `Imported ${result.agent_name} from ${summaryLabel(result)} with ${result.eval_case_count} starter evals`
        );
        setStep(2);
      },
      onError: (error) => {
        toastError('Connect failed', error.message);
      },
    });
  }

  function handleReset() {
    setStep(1);
    setSelectedAdapter(null);
    setSourceValue('');
    setWorkspaceName('');
    setOutputDir('');
    setRuntimeMode('mock');
    setShowSecondaryAdapters(isProMode);
  }

  const importResult = connectMutation.data;
  const showProgress = Boolean(selectedSource) || (step === 2 && Boolean(importResult));
  const shouldShowAdapterGrid = isProMode || showSecondaryAdapters;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Connect Existing Runtime"
        description={
          isProMode
            ? 'Connect Google Cloud, OpenAI, Anthropic, webhook, and transcript runtimes into fresh AgentLab workspaces.'
            : 'Start with Google CX Agent Studio or Google ADK. Advanced adapters stay available when you need them.'
        }
      />

      {step === 1 && (
        <>
          <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex flex-col gap-4 border-b border-slate-100 pb-5 lg:flex-row lg:items-end lg:justify-between">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-500">
                  Google-first imports
                </p>
                <h3 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950">
                  Bring CX and ADK projects into AgentLab first.
                </h3>
                <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
                  These are the primary connection paths for this workspace. Use CX Studio for
                  Dialogflow CX governance, or start from Google ADK when you already have a local
                  project ready to import.
                </p>
              </div>
              <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
                  View mode
                </p>
                <p className="mt-2 text-sm font-medium text-slate-900">
                  {isProMode ? 'Pro surface' : 'Simple surface'}
                </p>
              </div>
            </div>

            <div className="mt-6 grid gap-4 lg:grid-cols-2">
              {GOOGLE_IMPORT_OPTIONS.map((option) => {
                const Icon = option.icon;
                return (
                  <Link
                    key={option.href}
                    to={option.href}
                    className={`group relative overflow-hidden rounded-3xl border border-slate-200 bg-gradient-to-br ${option.gradientClassName} p-6 shadow-sm transition duration-200 hover:-translate-y-0.5 hover:shadow-md`}
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div className="rounded-2xl border border-white/70 bg-white/90 p-3 text-sky-700 shadow-sm">
                        <Icon className="h-6 w-6" />
                      </div>
                      <div className="flex items-center gap-3">
                        <GoogleCloudMark />
                        <ArrowUpRight className="h-4 w-4 text-slate-500 transition group-hover:text-slate-900" />
                      </div>
                    </div>

                    <p className="mt-8 text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-500">
                      {option.eyebrow}
                    </p>
                    <h4 className="mt-2 text-xl font-semibold tracking-tight text-slate-950">
                      {option.title}
                    </h4>
                    <p className="mt-3 text-sm leading-6 text-slate-600">{option.description}</p>

                    <div className="mt-6 inline-flex items-center rounded-full border border-slate-200 bg-white/90 px-3 py-1.5 text-sm font-medium text-slate-900">
                      {option.cta}
                    </div>
                  </Link>
                );
              })}
            </div>
          </section>

          <section className="rounded-3xl border border-gray-200 bg-white shadow-sm">
            <div className="flex flex-col gap-4 px-5 py-5 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-gray-500">
                  Advanced adapters
                </p>
                <h3 className="mt-2 text-lg font-semibold tracking-tight text-gray-900">
                  {isProMode ? 'All adapter imports' : 'More adapters'}
                </h3>
                <p className="mt-1 text-sm leading-6 text-gray-600">
                  {isProMode
                    ? 'OpenAI, Anthropic, HTTP webhook, and transcript imports stay visible in Pro mode.'
                    : 'Use these only when you need to wrap an existing SDK runtime, webhook, or transcript archive.'}
                </p>
              </div>

              {!isProMode && (
                <button
                  type="button"
                  aria-expanded={showSecondaryAdapters}
                  onClick={() => setShowSecondaryAdapters((current) => !current)}
                  className="inline-flex items-center justify-center gap-2 rounded-full border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition hover:border-gray-400 hover:bg-gray-50"
                >
                  <span>More adapters</span>
                  {showSecondaryAdapters ? (
                    <ChevronUp className="h-4 w-4" />
                  ) : (
                    <ChevronDown className="h-4 w-4" />
                  )}
                </button>
              )}
            </div>

            {shouldShowAdapterGrid && (
              <div className="border-t border-gray-100 px-5 py-5">
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                  {CONNECT_SOURCES.map((source) => {
                    const Icon = source.icon;
                    const isSelected = source.adapter === selectedAdapter;
                    return (
                      <button
                        key={source.adapter}
                        type="button"
                        aria-label={source.label}
                        onClick={() => handleSelectAdapter(source.adapter)}
                        className={`rounded-2xl border p-4 text-left transition ${
                          isSelected
                            ? 'border-blue-300 bg-blue-50 shadow-sm'
                            : 'border-gray-200 bg-white hover:border-gray-300 hover:bg-gray-50'
                        }`}
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <p className="text-sm font-semibold text-gray-900">{source.label}</p>
                            <p className="mt-1 text-xs leading-relaxed text-gray-600">
                              {source.description}
                            </p>
                          </div>
                          <Icon className={`h-4 w-4 ${isSelected ? 'text-blue-700' : 'text-gray-500'}`} />
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </section>
        </>
      )}

      {showProgress && (
        <div className="flex items-center gap-2 text-sm">
          {[1, 2].map((currentStep) => (
            <div key={currentStep} className="flex items-center gap-2">
              <div
                className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-medium ${
                  step >= currentStep ? 'bg-blue-600 text-white' : 'bg-gray-200 text-gray-500'
                }`}
              >
                {step > currentStep ? <Check className="h-3.5 w-3.5" /> : currentStep}
              </div>
              <span className={step >= currentStep ? 'text-gray-900' : 'text-gray-500'}>
                {currentStep === 1 ? 'Adapter' : 'Workspace Ready'}
              </span>
            </div>
          ))}
        </div>
      )}

      {step === 1 && selectedSource && (
        <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="flex items-start gap-3">
            <div className="rounded-lg bg-blue-50 p-2 text-blue-700">
              <Network className="h-4 w-4" />
            </div>
            <div className="min-w-0 flex-1">
              <h3 className="text-sm font-semibold text-gray-900">{selectedSource.label} connection</h3>
              <p className="mt-1 text-sm text-gray-600">{selectedSource.helpText}</p>
            </div>
          </div>

          <div className="mt-5 grid gap-4 lg:grid-cols-2">
            <div className="lg:col-span-2">
              <label htmlFor="connect-source" className="mb-1 block text-xs text-gray-500">
                {selectedSource.fieldLabel}
              </label>
              <input
                id="connect-source"
                type="text"
                placeholder={selectedSource.placeholder}
                value={sourceValue}
                onChange={(event) => setSourceValue(event.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 focus:border-blue-500 focus:outline-none"
              />
            </div>

            <div>
              <label htmlFor="connect-workspace-name" className="mb-1 block text-xs text-gray-500">
                Workspace name
              </label>
              <input
                id="connect-workspace-name"
                type="text"
                placeholder="support-runtime"
                value={workspaceName}
                onChange={(event) => setWorkspaceName(event.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 focus:border-blue-500 focus:outline-none"
              />
            </div>

            <div>
              <label htmlFor="connect-output-dir" className="mb-1 block text-xs text-gray-500">
                Output directory
              </label>
              <input
                id="connect-output-dir"
                type="text"
                placeholder="."
                value={outputDir}
                onChange={(event) => setOutputDir(event.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 focus:border-blue-500 focus:outline-none"
              />
            </div>

            <div className="lg:col-span-2">
              <label htmlFor="connect-runtime-mode" className="mb-1 block text-xs text-gray-500">
                Runtime mode
              </label>
              <select
                id="connect-runtime-mode"
                value={runtimeMode}
                onChange={(event) => setRuntimeMode(event.target.value as ConnectRuntimeMode)}
                className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-blue-500 focus:outline-none"
              >
                {RUNTIME_MODE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label} - {option.help}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="mt-5 flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={handleSubmit}
              disabled={!sourceValue.trim() || connectMutation.isPending}
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {connectMutation.isPending ? 'Creating...' : 'Create workspace'}
            </button>
            <p className="text-xs text-gray-500">
              AgentLab will save the imported spec, adapter config, and starter eval fixtures together.
            </p>
          </div>
        </section>
      )}

      {step === 2 && importResult && (
        <section className="space-y-4 rounded-xl border border-green-200 bg-white p-5 shadow-sm">
          <div className="flex items-center gap-2 text-green-700">
            <Check className="h-5 w-5" />
            <h3 className="text-sm font-semibold">Workspace Ready</h3>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <div className="rounded-lg border border-gray-200 bg-gray-50 p-4">
              <p className="text-xs font-medium uppercase tracking-wide text-gray-500">Imported runtime</p>
              <p className="mt-2 text-sm text-gray-900">{importResult.agent_name}</p>
              <p className="mt-1 text-xs text-gray-600">{summaryLabel(importResult)}</p>
            </div>
            <div className="rounded-lg border border-gray-200 bg-gray-50 p-4">
              <p className="text-xs font-medium uppercase tracking-wide text-gray-500">Workspace path</p>
              <p className="mt-2 break-all text-sm text-gray-900">{importResult.workspace_path}</p>
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            <div className="rounded-lg border border-gray-200 p-4 text-sm text-gray-700">
              <p><span className="text-gray-500">Config:</span> {importResult.config_path}</p>
              <p><span className="text-gray-500">Starter evals:</span> {importResult.eval_path}</p>
              <p><span className="text-gray-500">Adapter config:</span> {importResult.adapter_config_path}</p>
              <p><span className="text-gray-500">Imported spec:</span> {importResult.spec_path}</p>
            </div>
            <div className="rounded-lg border border-gray-200 p-4 text-sm text-gray-700">
              <p><span className="text-gray-500">Tools:</span> {importResult.tool_count}</p>
              <p><span className="text-gray-500">Guardrails:</span> {importResult.guardrail_count}</p>
              <p><span className="text-gray-500">Traces:</span> {importResult.trace_count}</p>
              <p><span className="text-gray-500">Eval cases:</span> {importResult.eval_case_count}</p>
            </div>
          </div>

          {importResult.traces_path && (
            <div className="rounded-lg border border-blue-100 bg-blue-50 p-4 text-sm text-blue-900">
              Imported traces saved to {importResult.traces_path}
            </div>
          )}

          <div className="rounded-lg border border-green-100 bg-green-50 p-4">
            <p className="text-xs font-medium uppercase tracking-wide text-green-700">Next steps</p>
            <p className="mt-1 text-sm text-green-900">
              Run the starter eval suite first, then review the generated config before you begin optimization or deployment.
            </p>
          </div>

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={handleReset}
              className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 transition hover:bg-gray-100"
            >
              Connect another source
            </button>
            <Link
              to="/evals"
              className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-1.5 text-sm font-medium text-blue-700 transition hover:bg-blue-100"
            >
              Run evaluations
            </Link>
            <Link
              to="/configs"
              className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 transition hover:bg-gray-100"
            >
              Review configs
            </Link>
          </div>
        </section>
      )}
    </div>
  );
}
