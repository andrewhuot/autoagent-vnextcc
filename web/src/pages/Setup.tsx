import {
  Activity,
  Bot,
  Database,
  FolderGit2,
  PlugZap,
  TerminalSquare,
  Wrench,
} from 'lucide-react';
import type { ReactNode } from 'react';
import { PageHeader } from '../components/PageHeader';
import { useSetupOverview } from '../lib/api';
import { classNames } from '../lib/utils';

export function Setup() {
  const { data, isLoading, isError } = useSetupOverview();

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
          <KeyValue label="Path" value={data.workspace.path ?? 'Run `autoagent init` to create a workspace'} />
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
          title="Mode"
          description="Surface the effective runtime mode and provider readiness exactly where operators expect it."
        >
          <MetricPill
            label="Effective Mode"
            value={data.doctor.effective_mode.toUpperCase()}
            tone={data.doctor.effective_mode === 'live' ? 'good' : 'warn'}
          />
          <MetricPill label="Preferred Mode" value={data.doctor.preferred_mode.toUpperCase()} tone="neutral" />
          <MetricPill label="Mode Source" value={data.doctor.mode_source} tone="neutral" />
          <p className="rounded-2xl bg-slate-50 px-4 py-3 text-sm leading-6 text-slate-600">
            {data.doctor.message}
          </p>
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

          <div className="grid gap-2 md:grid-cols-3">
            {data.doctor.api_keys.map((keyStatus) => (
              <div key={keyStatus.name} className="rounded-xl border border-slate-200 px-3 py-2">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">{keyStatus.name}</p>
                <p className="mt-2 text-sm font-medium text-slate-900">
                  {keyStatus.configured ? 'Configured' : 'Missing'}
                </p>
              </div>
            ))}
          </div>
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
          description="Track whether AutoAgent has been wired into the local MCP-aware tools."
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
