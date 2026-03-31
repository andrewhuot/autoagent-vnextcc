import { startTransition, useEffect, useState } from 'react';
import {
  AlertTriangle,
  ArrowRightLeft,
  CheckCircle2,
  FileDiff,
  FolderSync,
  RefreshCw,
  ShieldCheck,
  UploadCloud,
} from 'lucide-react';
import {
  useConfigShow,
  useConfigs,
  useCxAgents,
  useCxAuth,
  useCxDiff,
  useCxExport,
  useCxImport,
  useCxSync,
} from '../lib/api';
import { PageHeader } from '../components/PageHeader';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { classNames } from '../lib/utils';
import { toastError, toastSuccess } from '../lib/toast';
import type { CxAgentSummary, CxExportResult, CxImportResult } from '../lib/types';

function agentIdFromName(agent: CxAgentSummary | null): string {
  return agent?.name.split('/').pop() || '';
}

function ResultPanel({
  title,
  count,
  tone,
  items,
}: {
  title: string;
  count: number;
  tone: 'neutral' | 'success' | 'warning';
  items: Array<{ label: string; detail: string }>;
}) {
  const toneClasses =
    tone === 'success'
      ? 'border-green-200 bg-green-50/70'
      : tone === 'warning'
        ? 'border-amber-200 bg-amber-50/70'
        : 'border-gray-200 bg-white';

  return (
    <div className={classNames('rounded-2xl border p-4', toneClasses)}>
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-900">{title}</h3>
        <span className="rounded-full border border-gray-200 bg-white px-2.5 py-1 text-xs font-medium text-gray-600">
          {count}
        </span>
      </div>
      {items.length === 0 ? (
        <p className="mt-4 text-sm text-gray-500">Nothing to show yet.</p>
      ) : (
        <div className="mt-4 space-y-2">
          {items.map((item) => (
            <div key={`${item.label}-${item.detail}`} className="rounded-xl border border-gray-200 bg-white px-3 py-2.5">
              <p className="text-sm font-medium text-gray-900">{item.label}</p>
              <p className="mt-1 text-xs leading-5 text-gray-500">{item.detail}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function CXStudio() {
  const [project, setProject] = useState('');
  const [location, setLocation] = useState('global');
  const [credentialsPath, setCredentialsPath] = useState('');
  const [selectedAgent, setSelectedAgent] = useState<CxAgentSummary | null>(null);
  const [configVersion, setConfigVersion] = useState('');
  const [snapshotPath, setSnapshotPath] = useState('');
  const [lastImport, setLastImport] = useState<CxImportResult | null>(null);
  const [lastResult, setLastResult] = useState<CxExportResult | null>(null);
  const [lastAction, setLastAction] = useState<'diff' | 'preview' | 'sync' | 'export' | null>(null);

  const authMutation = useCxAuth();
  const { data: agents, isLoading: agentsLoading, refetch: refetchAgents } = useCxAgents(
    project,
    location,
    credentialsPath || undefined
  );
  const importMutation = useCxImport();
  const exportMutation = useCxExport();
  const diffMutation = useCxDiff();
  const syncMutation = useCxSync();
  const { data: configs } = useConfigs();
  const selectedVersion = configVersion ? Number(configVersion) : null;
  const selectedConfig = useConfigShow(selectedVersion);

  useEffect(() => {
    if (!configVersion && configs && configs.length > 0) {
      setConfigVersion(String(configs[0].version));
    }
  }, [configVersion, configs]);

  const selectedAgentId = agentIdFromName(selectedAgent);
  const activeConfig = selectedConfig.data?.config;
  const workingMutation = importMutation.isPending || exportMutation.isPending || diffMutation.isPending || syncMutation.isPending;

  function handleAuthCheck() {
    authMutation.mutate(
      { credentials_path: credentialsPath || undefined },
      {
        onSuccess: (result) => {
          toastSuccess('Credentials verified', `${result.auth_type} authenticated${result.project_id ? ` for ${result.project_id}` : ''}`);
          if (!project && result.project_id) {
            startTransition(() => setProject(result.project_id || ''));
          }
        },
        onError: (error) => toastError('Authentication failed', error.message),
      }
    );
  }

  function handleImport() {
    if (!project || !selectedAgentId) return;
    importMutation.mutate(
      {
        project,
        location,
        agent_id: selectedAgentId,
        credentials_path: credentialsPath || undefined,
      },
      {
        onSuccess: (result) => {
          startTransition(() => {
            setLastImport(result);
            setSnapshotPath(result.snapshot_path);
          });
          toastSuccess('CX agent imported', `${result.agent_name} is now linked to a local workspace.`);
        },
        onError: (error) => toastError('Import failed', error.message),
      }
    );
  }

  function runDiffLikeAction(
    mode: 'diff' | 'preview' | 'sync' | 'export',
  ) {
    if (!project || !selectedAgentId || !snapshotPath || !activeConfig) return;

    const basePayload = {
      project,
      location,
      agent_id: selectedAgentId,
      config: activeConfig,
      snapshot_path: snapshotPath,
      credentials_path: credentialsPath || undefined,
    };

    if (mode === 'diff') {
      diffMutation.mutate(basePayload, {
        onSuccess: (result) => {
          setLastAction('diff');
          setLastResult(result);
          toastSuccess('Diff ready', `${result.changes.length} remote-facing change(s) computed.`);
        },
        onError: (error) => toastError('Diff failed', error.message),
      });
      return;
    }

    if (mode === 'preview' || mode === 'export') {
      exportMutation.mutate(
        {
          ...basePayload,
          dry_run: mode === 'preview',
        },
        {
          onSuccess: (result) => {
            setLastAction(mode);
            setLastResult(result);
            toastSuccess(
              mode === 'preview' ? 'Preview ready' : 'Export complete',
              mode === 'preview'
                ? `${result.changes.length} change(s) staged for review.`
                : result.pushed
                  ? `Updated ${result.resources_updated} CX resource(s).`
                  : 'No changes needed.'
            );
          },
          onError: (error) => toastError(mode === 'preview' ? 'Preview failed' : 'Export failed', error.message),
        }
      );
      return;
    }

    syncMutation.mutate(
      {
        ...basePayload,
        conflict_strategy: 'detect',
      },
      {
        onSuccess: (result) => {
          setLastAction('sync');
          setLastResult(result);
          if (result.conflicts.length > 0 && !result.pushed) {
            toastError('Sync blocked', `${result.conflicts.length} conflict(s) need review.`);
            return;
          }
          toastSuccess('Sync complete', `Synchronized ${result.resources_updated} resource(s).`);
        },
        onError: (error) => toastError('Sync failed', error.message),
      }
    );
  }

  const changeItems = (lastResult?.changes || []).map((change) => ({
    label: `${change.action.toUpperCase()} ${change.resource}`,
    detail: `${change.name || change.field || 'resource'}${change.field && change.name ? ` · ${change.field}` : ''}`,
  }));
  const conflictItems = (lastResult?.conflicts || []).map((conflict) => ({
    label: `${conflict.resource} · ${conflict.name}`,
    detail: `Field ${conflict.field} diverged locally and remotely since the last import.`,
  }));

  return (
    <div className="space-y-6">
      <PageHeader
        title="CX Studio"
        description="Authenticate to Google Cloud, browse CX agents, import them into AutoAgent workspaces, and review export/sync diffs before pushing changes."
      />

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)]">
        <div className="rounded-3xl border border-gray-200 bg-gradient-to-br from-slate-950 via-slate-900 to-slate-800 p-6 text-white shadow-sm">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-sky-200/80">
                Connection
              </p>
              <h2 className="mt-2 text-2xl font-semibold tracking-tight">
                Point AutoAgent at the exact CX workspace you want to govern.
              </h2>
              <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-300">
                This page keeps the live CX agent, the imported snapshot, and the active AutoAgent config in one place so you can see what will change before any write-back happens.
              </p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">Current mode</p>
              <p className="mt-2 text-sm font-medium text-white">
                {lastAction ? lastAction.toUpperCase() : 'READINESS'}
              </p>
            </div>
          </div>

          <div className="mt-6 grid gap-3 md:grid-cols-2">
            <label className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">Project</span>
              <input
                aria-label="GCP project ID"
                value={project}
                onChange={(event) => setProject(event.target.value)}
                placeholder="demo-project"
                className="mt-3 w-full bg-transparent text-sm text-white outline-none placeholder:text-slate-500"
              />
            </label>
            <label className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">Region</span>
              <input
                aria-label="Region"
                value={location}
                onChange={(event) => setLocation(event.target.value)}
                placeholder="us-central1"
                className="mt-3 w-full bg-transparent text-sm text-white outline-none placeholder:text-slate-500"
              />
            </label>
          </div>

          <label className="mt-3 block rounded-2xl border border-white/10 bg-white/5 p-4">
            <span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">Credentials path</span>
            <input
              aria-label="Credentials path"
              value={credentialsPath}
              onChange={(event) => setCredentialsPath(event.target.value)}
              placeholder="Optional service account JSON path"
              className="mt-3 w-full bg-transparent text-sm text-white outline-none placeholder:text-slate-500"
            />
          </label>

          <div className="mt-4 flex flex-wrap gap-2">
            <button
              onClick={handleAuthCheck}
              className="rounded-xl bg-sky-400 px-4 py-2 text-sm font-medium text-slate-950 transition hover:bg-sky-300"
            >
              <ShieldCheck className="mr-2 inline h-4 w-4" />
              Check auth
            </button>
            <button
              onClick={() => refetchAgents()}
              disabled={!project}
              className="rounded-xl border border-white/15 bg-white/5 px-4 py-2 text-sm font-medium text-white transition hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <RefreshCw className="mr-2 inline h-4 w-4" />
              Browse agents
            </button>
          </div>
        </div>

        <div className="grid gap-4 sm:grid-cols-3 xl:grid-cols-1">
          <div className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-500">Auth status</p>
            <p className="mt-3 text-lg font-semibold text-gray-900">
              {authMutation.data ? 'Verified' : 'Unchecked'}
            </p>
            <p className="mt-2 text-sm text-gray-500">
              {authMutation.data
                ? `${authMutation.data.auth_type} · ${authMutation.data.project_id || 'project unknown'}`
                : 'Validate credentials before listing or importing agents.'}
            </p>
          </div>
          <div className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-500">Selected agent</p>
            <p className="mt-3 text-lg font-semibold text-gray-900">{selectedAgent?.display_name || 'None selected'}</p>
            <p className="mt-2 text-sm text-gray-500">
              {selectedAgent?.description || 'Choose an agent from the browser to enable import and sync actions.'}
            </p>
          </div>
          <div className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-500">Linked snapshot</p>
            <p className="mt-3 truncate text-sm font-medium text-gray-900">{snapshotPath || 'No snapshot linked yet'}</p>
            <p className="mt-2 text-sm text-gray-500">
              {lastImport?.workspace_path
                ? `Workspace: ${lastImport.workspace_path}`
                : 'Import an agent or paste an existing snapshot path to unlock export and sync.'}
            </p>
          </div>
        </div>
      </section>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <div className="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-500">Agent browser</p>
              <h2 className="mt-1 text-lg font-semibold text-gray-900">Available CX agents</h2>
            </div>
            <button
              onClick={() => refetchAgents()}
              disabled={!project}
              className="rounded-xl border border-gray-200 bg-gray-50 px-3 py-2 text-xs font-medium text-gray-700 transition hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Refresh
            </button>
          </div>

          <div className="mt-4 space-y-2">
            {agentsLoading ? (
              <LoadingSkeleton rows={4} />
            ) : (agents || []).length === 0 ? (
              <div className="rounded-2xl border border-dashed border-gray-200 bg-gray-50 p-5 text-sm text-gray-500">
                Add a project above, check auth, and browse agents to populate this panel.
              </div>
            ) : (
              agents?.map((agent) => {
                const isActive = selectedAgent?.name === agent.name;
                return (
                  <button
                    key={agent.name}
                    onClick={() => startTransition(() => setSelectedAgent(agent))}
                    className={classNames(
                      'w-full rounded-2xl border px-4 py-3 text-left transition',
                      isActive
                        ? 'border-sky-300 bg-sky-50 shadow-sm'
                        : 'border-gray-200 bg-white hover:border-gray-300 hover:bg-gray-50'
                    )}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-sm font-semibold text-gray-900">{agent.display_name}</p>
                        <p className="mt-1 truncate text-xs text-gray-500">{agent.name}</p>
                      </div>
                      <span className="rounded-full border border-gray-200 bg-white px-2 py-1 text-[11px] font-medium text-gray-600">
                        {agent.default_language_code}
                      </span>
                    </div>
                    <p className="mt-2 text-sm leading-5 text-gray-600">{agent.description || 'No description provided.'}</p>
                  </button>
                );
              })
            )}
          </div>
        </div>

        <div className="space-y-4">
          <div className="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-500">Import wizard</p>
                <h2 className="mt-1 text-lg font-semibold text-gray-900">Create or refresh the linked workspace</h2>
              </div>
              <button
                onClick={handleImport}
                disabled={!selectedAgentId || !project || importMutation.isPending}
                className="rounded-xl bg-slate-950 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <UploadCloud className="mr-2 inline h-4 w-4" />
                {importMutation.isPending ? 'Importing…' : 'Import agent'}
              </button>
            </div>

            <div className="mt-4 rounded-2xl border border-gray-200 bg-gray-50 p-4 text-sm text-gray-600">
              Import writes a full AutoAgent workspace, stores a CX snapshot in `.autoagent/cx/`, and links the active config so export, diff, and sync can stay incremental.
            </div>

            {lastImport && (
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <div className="rounded-2xl border border-green-200 bg-green-50 p-4">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-green-700">Workspace</p>
                  <p className="mt-2 text-sm font-medium text-green-900">{lastImport.workspace_path || 'Created'}</p>
                </div>
                <div className="rounded-2xl border border-green-200 bg-green-50 p-4">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-green-700">Surfaces</p>
                  <p className="mt-2 text-sm font-medium text-green-900">{lastImport.surfaces_mapped.join(', ')}</p>
                </div>
              </div>
            )}
          </div>

          <div className="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-500">Export wizard</p>
                <h2 className="mt-1 text-lg font-semibold text-gray-900">Review local changes before write-back</h2>
              </div>
              <div className="rounded-full border border-gray-200 bg-gray-50 px-3 py-1 text-xs font-medium text-gray-600">
                Active config {configVersion ? `v${configVersion}` : 'unselected'}
              </div>
            </div>

            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <label className="rounded-2xl border border-gray-200 bg-gray-50 p-4">
                <span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-500">Config version</span>
                <select
                  aria-label="Config version"
                  value={configVersion}
                  onChange={(event) => setConfigVersion(event.target.value)}
                  className="mt-3 w-full bg-transparent text-sm text-gray-900 outline-none"
                >
                  <option value="">Select a config</option>
                  {(configs || []).map((config) => (
                    <option key={config.version} value={config.version}>
                      v{config.version} · {config.status}
                    </option>
                  ))}
                </select>
              </label>

              <label className="rounded-2xl border border-gray-200 bg-gray-50 p-4">
                <span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-500">Snapshot path</span>
                <input
                  aria-label="Snapshot path"
                  value={snapshotPath}
                  onChange={(event) => setSnapshotPath(event.target.value)}
                  placeholder=".autoagent/cx/snapshot.json"
                  className="mt-3 w-full bg-transparent text-sm text-gray-900 outline-none placeholder:text-gray-400"
                />
              </label>
            </div>

            <div className="mt-4 flex flex-wrap gap-2">
              <button
                onClick={() => runDiffLikeAction('diff')}
                disabled={!selectedAgentId || !snapshotPath || !activeConfig || workingMutation}
                className="rounded-xl border border-gray-200 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <FileDiff className="mr-2 inline h-4 w-4" />
                Diff vs remote
              </button>
              <button
                onClick={() => runDiffLikeAction('preview')}
                disabled={!selectedAgentId || !snapshotPath || !activeConfig || workingMutation}
                className="rounded-xl border border-gray-200 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <ArrowRightLeft className="mr-2 inline h-4 w-4" />
                Preview export
              </button>
              <button
                onClick={() => runDiffLikeAction('sync')}
                disabled={!selectedAgentId || !snapshotPath || !activeConfig || workingMutation}
                className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-2 text-sm font-medium text-amber-900 transition hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <FolderSync className="mr-2 inline h-4 w-4" />
                Sync safely
              </button>
              <button
                onClick={() => runDiffLikeAction('export')}
                disabled={!selectedAgentId || !snapshotPath || !activeConfig || workingMutation}
                className="rounded-xl bg-sky-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-sky-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <CheckCircle2 className="mr-2 inline h-4 w-4" />
                Push export
              </button>
            </div>
          </div>
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <ResultPanel
          title={lastAction === 'sync' ? 'Sync plan' : 'Planned changes'}
          count={changeItems.length}
          tone={lastResult?.pushed ? 'success' : 'neutral'}
          items={changeItems}
        />
        <ResultPanel
          title="Conflicts"
          count={conflictItems.length}
          tone={conflictItems.length > 0 ? 'warning' : 'neutral'}
          items={conflictItems}
        />
      </section>

      {selectedConfig.isLoading && (
        <div className="rounded-2xl border border-gray-200 bg-white p-4">
          <LoadingSkeleton rows={3} />
        </div>
      )}

      {lastResult?.conflicts?.length ? (
        <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
          <AlertTriangle className="mr-2 inline h-4 w-4" />
          Remote edits overlap with the local workspace. Review the conflict list before syncing or re-import to refresh the merge base.
        </div>
      ) : null}
    </div>
  );
}
