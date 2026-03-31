import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Bot, Check, FileJson, Globe, Network, Plug2 } from 'lucide-react';

import { PageHeader } from '../components/PageHeader';
import { useConnectImport } from '../lib/api';
import { toastError, toastSuccess } from '../lib/toast';
import type {
  ConnectAdapter,
  ConnectImportRequest,
  ConnectImportResult,
  ConnectRuntimeMode,
} from '../lib/types';

interface ConnectSourceOption {
  adapter: ConnectAdapter;
  label: string;
  description: string;
  icon: typeof Bot;
}

const CONNECT_SOURCES: ConnectSourceOption[] = [
  {
    adapter: 'openai-agents',
    label: 'OpenAI Agents',
    description: 'Scan a Python project for Agent() definitions, tools, handoffs, and guardrails.',
    icon: Bot,
  },
  {
    adapter: 'anthropic',
    label: 'Anthropic',
    description: 'Import Anthropic SDK prompts, tools, MCP references, and session patterns.',
    icon: Plug2,
  },
  {
    adapter: 'http',
    label: 'HTTP',
    description: 'Wrap an existing agent API behind a lightweight AutoAgent adapter workspace.',
    icon: Globe,
  },
  {
    adapter: 'transcript',
    label: 'Transcript',
    description: 'Turn JSONL conversations into an imported runtime spec with starter eval fixtures.',
    icon: FileJson,
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
    help: 'Let AutoAgent choose the runtime mode from the imported source.',
  },
];

function sourceFieldLabel(adapter: ConnectAdapter): string {
  switch (adapter) {
    case 'openai-agents':
      return 'Project path';
    case 'anthropic':
      return 'Project path';
    case 'http':
      return 'Runtime URL';
    case 'transcript':
      return 'Transcript file';
  }
}

function sourcePlaceholder(adapter: ConnectAdapter): string {
  switch (adapter) {
    case 'openai-agents':
      return '/path/to/openai-agents/project';
    case 'anthropic':
      return '/path/to/anthropic/project';
    case 'http':
      return 'https://agent.example.com';
    case 'transcript':
      return '/path/to/conversations.jsonl';
  }
}

function sourceHelpText(adapter: ConnectAdapter): string {
  switch (adapter) {
    case 'openai-agents':
      return 'Point at the root of the Python project that defines your OpenAI Agents runtime.';
    case 'anthropic':
      return 'Point at the project directory that contains Anthropic SDK code or MCP configuration.';
    case 'http':
      return 'Use the primary webhook or REST endpoint that fronts the runtime you want to connect.';
    case 'transcript':
      return 'Provide a JSONL export of prior conversations so AutoAgent can build starter eval cases.';
  }
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
  const [selectedAdapter, setSelectedAdapter] = useState<ConnectAdapter>('openai-agents');
  const [sourceValue, setSourceValue] = useState('');
  const [workspaceName, setWorkspaceName] = useState('');
  const [outputDir, setOutputDir] = useState('');
  const [runtimeMode, setRuntimeMode] = useState<ConnectRuntimeMode>('mock');

  const connectMutation = useConnectImport();
  const selectedSource = useMemo(
    () => CONNECT_SOURCES.find((source) => source.adapter === selectedAdapter) ?? CONNECT_SOURCES[0],
    [selectedAdapter]
  );

  function handleSelectAdapter(adapter: ConnectAdapter) {
    setSelectedAdapter(adapter);
    setSourceValue('');
  }

  function handleSubmit() {
    if (!sourceValue.trim()) {
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
    setSelectedAdapter('openai-agents');
    setSourceValue('');
    setWorkspaceName('');
    setOutputDir('');
    setRuntimeMode('mock');
  }

  const importResult = connectMutation.data;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Connect Existing Runtime"
        description="Import an existing OpenAI Agents, Anthropic, HTTP, or transcript-based runtime into a fresh AutoAgent workspace."
      />

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
              {currentStep === 1 ? 'Source' : 'Workspace Ready'}
            </span>
          </div>
        ))}
      </div>

      {step === 1 && (
        <>
          <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            {CONNECT_SOURCES.map((source) => {
              const Icon = source.icon;
              const isSelected = source.adapter === selectedAdapter;
              return (
                <button
                  key={source.adapter}
                  type="button"
                  onClick={() => handleSelectAdapter(source.adapter)}
                  className={`rounded-xl border p-4 text-left transition ${
                    isSelected
                      ? 'border-blue-300 bg-blue-50 shadow-sm'
                      : 'border-gray-200 bg-white hover:border-gray-300 hover:bg-gray-50'
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-sm font-semibold text-gray-900">{source.label}</p>
                      <p className="mt-1 text-xs leading-relaxed text-gray-600">{source.description}</p>
                    </div>
                    <Icon className={`h-4 w-4 ${isSelected ? 'text-blue-700' : 'text-gray-500'}`} />
                  </div>
                </button>
              );
            })}
          </section>

          <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
            <div className="flex items-start gap-3">
              <div className="rounded-lg bg-blue-50 p-2 text-blue-700">
                <Network className="h-4 w-4" />
              </div>
              <div className="min-w-0 flex-1">
                <h3 className="text-sm font-semibold text-gray-900">{selectedSource.label} connection</h3>
                <p className="mt-1 text-sm text-gray-600">{sourceHelpText(selectedAdapter)}</p>
              </div>
            </div>

            <div className="mt-5 grid gap-4 lg:grid-cols-2">
              <div className="lg:col-span-2">
                <label htmlFor="connect-source" className="mb-1 block text-xs text-gray-500">
                  {sourceFieldLabel(selectedAdapter)}
                </label>
                <input
                  id="connect-source"
                  type="text"
                  placeholder={sourcePlaceholder(selectedAdapter)}
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
                AutoAgent will save the imported spec, adapter config, and starter eval fixtures together.
              </p>
            </div>
          </section>
        </>
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
