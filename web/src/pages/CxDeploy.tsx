import { useEffect, useState } from 'react';
import { Code2, Copy, Check, AlertTriangle, ShieldCheck, RotateCcw, Rocket, Ban } from 'lucide-react';
import {
  useConfigShow,
  useConfigs,
  useCxDeploy,
  useCxExport,
  useCxPreflight,
  useCxPromote,
  useCxRollback,
  useCxDeployStatus,
  useCxWidget,
} from '../lib/api';
import type { CxCanaryState, CxPreflightResult } from '../lib/types';
import { PageHeader } from '../components/PageHeader';
import { ExportReadiness } from '../components/ExportReadiness';
import { toastError, toastSuccess } from '../lib/toast';

export function CxDeploy() {
  // Deploy state
  const [project, setProject] = useState('');
  const [location, setLocation] = useState('global');
  const [appId, setAppId] = useState('');
  const [agentId, setAgentId] = useState('');
  const [environment, setEnvironment] = useState('production');
  const [strategy, setStrategy] = useState<'immediate' | 'canary'>('canary');
  const [trafficPct, setTrafficPct] = useState(10);
  const [snapshotPath, setSnapshotPath] = useState('');
  const [configVersion, setConfigVersion] = useState('');
  const [canaryState, setCanaryState] = useState<CxCanaryState | null>(null);
  const [preflightResult, setPreflightResult] = useState<CxPreflightResult | null>(null);

  // Widget state
  const [chatTitle, setChatTitle] = useState('Agent');
  const [primaryColor, setPrimaryColor] = useState('#1a73e8');
  const [copied, setCopied] = useState(false);

  const { data: configs } = useConfigs();
  const selectedVersion = configVersion ? Number(configVersion) : null;
  const selectedConfig = useConfigShow(selectedVersion);
  const preflightMutation = useCxPreflight();
  const deployMutation = useCxDeploy();
  const promoteMutation = useCxPromote();
  const rollbackMutation = useCxRollback();
  const exportMutation = useCxExport();
  const widgetMutation = useCxWidget();
  const deployStatus = useCxDeployStatus(project, location, appId, agentId);

  useEffect(() => {
    if (!configVersion && configs && configs.length > 0) {
      setConfigVersion(String(configs[0].version));
    }
  }, [configVersion, configs]);

  function handlePreflight() {
    if (!selectedConfig.data?.config) return;
    const matrix = exportMutation.data?.export_matrix
      ? {
          ready_surfaces: exportMutation.data.export_matrix.ready_surfaces,
          lossy_surfaces: exportMutation.data.export_matrix.lossy_surfaces,
          blocked_surfaces: exportMutation.data.export_matrix.blocked_surfaces,
        }
      : null;
    preflightMutation.mutate(
      {
        config: selectedConfig.data.config,
        export_matrix: matrix,
        fail_on_lossy_surfaces: true,
        fail_on_blocked_surfaces: true,
      },
      {
        onSuccess: (result) => {
          setPreflightResult(result);
          if (result.passed) {
            toastSuccess('Preflight passed', `${result.warnings.length} warning(s)`);
          } else {
            toastError('Preflight failed', `${result.errors.length} error(s) must be resolved`);
          }
        },
        onError: (err) => toastError('Preflight failed', err.message),
      }
    );
  }

  function handleDeploy() {
    if (!project || !appId || !agentId) return;
    deployMutation.mutate(
      { project, location, app_id: appId, agent_id: agentId, environment, strategy, traffic_pct: trafficPct },
      {
        onSuccess: (result) => {
          if (result.canary) {
            setCanaryState(result.canary);
          }
          toastSuccess(
            strategy === 'canary' ? 'Canary deployed' : 'Deploy successful',
            strategy === 'canary'
              ? `${trafficPct}% traffic routed to canary in ${result.environment}`
              : `Deployed to ${result.environment}`
          );
        },
        onError: (err) => toastError('Deploy failed', err.message),
      }
    );
  }

  function handlePromote() {
    if (!project || !appId || !agentId || !canaryState) return;
    promoteMutation.mutate(
      { project, location, app_id: appId, agent_id: agentId, canary: canaryState },
      {
        onSuccess: (result) => {
          if (result.canary) setCanaryState(result.canary);
          toastSuccess('Canary promoted', 'Full traffic now on new version');
        },
        onError: (err) => toastError('Promote failed', err.message),
      }
    );
  }

  function handleRollback() {
    if (!project || !appId || !agentId || !canaryState) return;
    rollbackMutation.mutate(
      { project, location, app_id: appId, agent_id: agentId, canary: canaryState },
      {
        onSuccess: (result) => {
          if (result.canary) setCanaryState(result.canary);
          toastSuccess('Rolled back', 'Reverted to previous version');
        },
        onError: (err) => toastError('Rollback failed', err.message),
      }
    );
  }

  function handlePreviewExport() {
    if (!project || !agentId || !snapshotPath || !selectedConfig.data?.config) return;
    exportMutation.mutate(
      {
        project,
        location,
        agent_id: agentId,
        config: selectedConfig.data.config,
        snapshot_path: snapshotPath,
        dry_run: true,
      },
      {
        onSuccess: (result) => toastSuccess('Preview ready', `${result.changes.length} change(s) identified.`),
        onError: (err) => toastError('Preview failed', err.message),
      }
    );
  }

  function handlePushExport() {
    if (!project || !agentId || !snapshotPath || !selectedConfig.data?.config) return;

    // Block push if preflight hasn't passed
    if (!preflightResult?.passed) {
      toastError('Push blocked', 'Run preflight validation and resolve errors before pushing.');
      return;
    }

    exportMutation.mutate(
      {
        project,
        location,
        agent_id: agentId,
        config: selectedConfig.data.config,
        snapshot_path: snapshotPath,
        dry_run: false,
      },
      {
        onSuccess: (result) =>
          toastSuccess('Export completed', result.pushed ? `Updated ${result.resources_updated} resource(s).` : 'No changes pushed.'),
        onError: (err) => toastError('Export failed', err.message),
      }
    );
  }

  function handleGenerateWidget() {
    if (!project || !agentId) return;
    widgetMutation.mutate(
      { project_id: project, agent_id: agentId, location, chat_title: chatTitle, primary_color: primaryColor },
      {
        onSuccess: () => toastSuccess('Widget generated', 'HTML ready to copy'),
        onError: (err) => toastError('Widget generation failed', err.message),
      }
    );
  }

  function handleCopyHtml() {
    if (widgetMutation.data?.html) {
      navigator.clipboard.writeText(widgetMutation.data.html);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }

  const hasBlockedChanges = exportMutation.data?.changes.some((c) => c.safety === 'blocked');

  return (
    <div className="space-y-6">
      <PageHeader
        title="CX Deploy & Widget"
        description="Deploy to CX Agent Studio environments with preflight validation, canary controls, and web widget generation"
      />

      {/* Agent Reference */}
      <div className="bg-gray-800 rounded-lg border border-gray-700 p-4 space-y-3">
        <h3 className="text-sm font-medium text-gray-200">Agent Reference</h3>
        <div className="grid grid-cols-3 gap-2">
          <input
            type="text" placeholder="GCP Project ID" value={project}
            onChange={(e) => setProject(e.target.value)}
            className="bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm text-gray-200 focus:border-blue-500 focus:outline-none"
          />
          <input
            type="text" placeholder="Location" value={location}
            onChange={(e) => setLocation(e.target.value)}
            className="bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm text-gray-200 focus:border-blue-500 focus:outline-none"
          />
          <input
            type="text" placeholder="App ID" value={appId}
            onChange={(e) => setAppId(e.target.value)}
            className="bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm text-gray-200 focus:border-blue-500 focus:outline-none"
          />
        </div>
        <div className="grid grid-cols-1 gap-2">
          <input
            type="text" placeholder="Agent ID" value={agentId}
            onChange={(e) => setAgentId(e.target.value)}
            className="bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm text-gray-200 focus:border-blue-500 focus:outline-none"
          />
        </div>
      </div>

      {/* Environment Status */}
      {deployStatus.data && deployStatus.data.deployments.length > 0 && (
        <div className="bg-gray-800 rounded-lg border border-gray-700 p-4 space-y-2" data-testid="environment-status">
          <h3 className="text-sm font-medium text-gray-200">Current Environment Versions</h3>
          <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
            {deployStatus.data.deployments.map((dep) => (
              <div key={dep.name} className="rounded border border-gray-600 bg-gray-900 p-2">
                <p className="text-xs font-medium text-gray-200">{dep.name}</p>
                <p className="text-xs text-gray-400">{dep.description || 'No description'}</p>
                <p className="text-xs text-gray-500 mt-1">
                  {dep.versions.length} version(s)
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Preview & Export */}
      <div className="bg-gray-800 rounded-lg border border-gray-700 p-4 space-y-3">
        <h3 className="text-sm font-medium text-gray-200">Preview & Export to CX</h3>
        <p className="text-xs text-gray-400">
          Select the optimized AgentLab config + CX snapshot, run preflight validation, preview exact changes, then push when ready.
        </p>
        <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
          <select
            value={configVersion}
            onChange={(e) => setConfigVersion(e.target.value)}
            className="bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm text-gray-200 focus:border-blue-500 focus:outline-none"
          >
            <option value="">Select config version</option>
            {(configs || []).map((config) => (
              <option key={config.version} value={config.version}>
                v{config.version} · {config.status}
              </option>
            ))}
          </select>
          <input
            type="text"
            placeholder="Snapshot path from CX import"
            value={snapshotPath}
            onChange={(e) => setSnapshotPath(e.target.value)}
            className="bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm text-gray-200 focus:border-blue-500 focus:outline-none md:col-span-2"
          />
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={handlePreflight}
            disabled={!selectedConfig.data?.config || preflightMutation.isPending}
            className="px-4 py-1.5 bg-yellow-600 text-white text-sm rounded hover:bg-yellow-500 disabled:opacity-50 disabled:cursor-not-allowed"
            data-testid="preflight-btn"
          >
            <ShieldCheck className="w-4 h-4 inline mr-1" />
            {preflightMutation.isPending ? 'Checking...' : 'Run Preflight'}
          </button>
          <button
            onClick={handlePreviewExport}
            disabled={!project || !agentId || !snapshotPath || !selectedConfig.data?.config || exportMutation.isPending}
            className="px-4 py-1.5 bg-gray-600 text-white text-sm rounded hover:bg-gray-500 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {exportMutation.isPending ? 'Previewing...' : 'Preview Export'}
          </button>
          <button
            onClick={handlePushExport}
            disabled={
              !project || !agentId || !snapshotPath || !selectedConfig.data?.config ||
              exportMutation.isPending || !preflightResult?.passed
            }
            className="px-4 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {exportMutation.isPending ? 'Pushing...' : 'Push to CX Agent Studio'}
          </button>
        </div>

        {/* Preflight result */}
        {preflightResult && (
          <div
            className={`rounded border p-3 ${
              preflightResult.passed
                ? 'border-green-700 bg-green-900/30'
                : 'border-red-700 bg-red-900/30'
            }`}
            data-testid="preflight-result"
          >
            <p className={`text-xs font-medium ${preflightResult.passed ? 'text-green-400' : 'text-red-400'}`}>
              {preflightResult.passed ? 'Preflight passed' : 'Preflight failed — resolve errors before pushing'}
            </p>
            {preflightResult.errors.length > 0 && (
              <ul className="mt-1 space-y-0.5">
                {preflightResult.errors.map((err, i) => (
                  <li key={i} className="text-xs text-red-300 flex items-start gap-1">
                    <Ban className="w-3 h-3 mt-0.5 shrink-0" /> {err}
                  </li>
                ))}
              </ul>
            )}
            {preflightResult.warnings.length > 0 && (
              <ul className="mt-1 space-y-0.5">
                {preflightResult.warnings.map((warn, i) => (
                  <li key={i} className="text-xs text-yellow-300 flex items-start gap-1">
                    <AlertTriangle className="w-3 h-3 mt-0.5 shrink-0" /> {warn}
                  </li>
                ))}
              </ul>
            )}
            {(preflightResult.safe_surfaces.length > 0 || preflightResult.blocked_surfaces.length > 0) && (
              <div className="mt-2 flex flex-wrap gap-1">
                {preflightResult.safe_surfaces.map((s) => (
                  <span key={s} className="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium bg-green-900 text-green-300">
                    {s}
                  </span>
                ))}
                {preflightResult.lossy_surfaces.map((s) => (
                  <span key={s} className="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium bg-amber-900 text-amber-300">
                    {s}
                  </span>
                ))}
                {preflightResult.blocked_surfaces.map((s) => (
                  <span key={s} className="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium bg-red-900 text-red-300">
                    {s}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Planned changes with safety classification */}
        {exportMutation.data && (
          <div className="rounded border border-gray-700 bg-gray-900 p-3">
            <p className="text-xs text-gray-400 mb-2">Planned Changes ({exportMutation.data.changes.length})</p>
            {hasBlockedChanges && (
              <p className="text-xs text-red-400 mb-2 flex items-center gap-1">
                <Ban className="w-3 h-3" />
                Some changes are blocked and will not be pushed to CX. Only safe and lossy changes will be applied.
              </p>
            )}
            {exportMutation.data.changes.length === 0 ? (
              <p className="text-sm text-gray-300">No changes detected.</p>
            ) : (
              <div className="space-y-1.5">
                {exportMutation.data.changes.map((change, index) => {
                  const safety = change.safety || 'safe';
                  const safetyColor = safety === 'safe' ? 'text-green-400' : safety === 'lossy' ? 'text-amber-400' : 'text-red-400';
                  return (
                    <div key={`${change.resource}-${change.action}-${index}`} className="flex items-center gap-2 text-xs">
                      <span className={`uppercase font-mono text-[10px] w-14 ${safetyColor}`}>[{safety}]</span>
                      <span className="text-gray-300">
                        {change.action.toUpperCase()} {change.resource}/{change.name || change.field || 'resource'}
                      </span>
                      {change.rationale && <span className="text-gray-500">— {change.rationale}</span>}
                    </div>
                  );
                })}
              </div>
            )}
            {exportMutation.data.pushed && (
              <p className="mt-2 text-xs text-green-400">Pushed {exportMutation.data.resources_updated} resource(s).</p>
            )}
          </div>
        )}
      </div>

      {/* Export readiness */}
      <ExportReadiness
        adapter="CX"
        exportMatrix={exportMutation.data?.export_matrix ?? null}
        changes={exportMutation.data?.changes}
        changeCount={exportMutation.data ? exportMutation.data.changes.length : undefined}
        conflictCount={exportMutation.data ? exportMutation.data.conflicts.length : undefined}
        exportAttempted={!!exportMutation.data}
      />

      {/* Deploy section with canary controls */}
      <div className="bg-gray-800 rounded-lg border border-gray-700 p-4 space-y-3">
        <h3 className="text-sm font-medium text-gray-200">Deploy to Environment</h3>
        <div className="flex gap-2 flex-wrap">
          <select
            value={environment}
            onChange={(e) => setEnvironment(e.target.value)}
            className="bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm text-gray-200 focus:border-blue-500 focus:outline-none"
          >
            <option value="production">Production</option>
            <option value="staging">Staging</option>
            <option value="draft">Draft</option>
          </select>
          <select
            value={strategy}
            onChange={(e) => setStrategy(e.target.value as 'immediate' | 'canary')}
            className="bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm text-gray-200 focus:border-blue-500 focus:outline-none"
            data-testid="strategy-select"
          >
            <option value="canary">Canary (recommended)</option>
            <option value="immediate">Immediate (full traffic)</option>
          </select>
          {strategy === 'canary' && (
            <div className="flex items-center gap-1">
              <input
                type="number"
                min={1}
                max={50}
                value={trafficPct}
                onChange={(e) => setTrafficPct(Number(e.target.value))}
                className="w-16 bg-gray-900 border border-gray-600 rounded px-2 py-1.5 text-sm text-gray-200 focus:border-blue-500 focus:outline-none"
              />
              <span className="text-xs text-gray-400">% traffic</span>
            </div>
          )}
          <button
            onClick={handleDeploy}
            disabled={!project || !appId || !agentId || deployMutation.isPending}
            className="px-4 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
            data-testid="deploy-btn"
          >
            <Rocket className="w-4 h-4 inline mr-1" />
            {deployMutation.isPending ? 'Deploying...' : strategy === 'canary' ? 'Deploy Canary' : 'Deploy'}
          </button>
        </div>

        {/* Canary controls */}
        {canaryState && (canaryState.phase === 'canary' || canaryState.phase === 'promoted') && (
          <div className="rounded border border-blue-700 bg-blue-900/30 p-3 space-y-2" data-testid="canary-controls">
            <div className="flex items-center justify-between">
              <p className="text-xs font-medium text-blue-300">
                Canary: {canaryState.deployed_version} at {canaryState.traffic_pct}% traffic ({canaryState.phase})
              </p>
              <div className="flex gap-2">
                {canaryState.phase === 'canary' && (
                  <button
                    onClick={handlePromote}
                    disabled={promoteMutation.isPending}
                    className="px-3 py-1 bg-green-600 text-white text-xs rounded hover:bg-green-500 disabled:opacity-50"
                    data-testid="promote-btn"
                  >
                    <Check className="w-3 h-3 inline mr-1" />
                    {promoteMutation.isPending ? 'Promoting...' : 'Promote to 100%'}
                  </button>
                )}
                <button
                  onClick={handleRollback}
                  disabled={rollbackMutation.isPending}
                  className="px-3 py-1 bg-red-600 text-white text-xs rounded hover:bg-red-500 disabled:opacity-50"
                  data-testid="rollback-btn"
                >
                  <RotateCcw className="w-3 h-3 inline mr-1" />
                  {rollbackMutation.isPending ? 'Rolling back...' : 'Rollback'}
                </button>
              </div>
            </div>
            {canaryState.previous_version && (
              <p className="text-xs text-gray-400">Previous version: {canaryState.previous_version}</p>
            )}
          </div>
        )}

        {canaryState?.phase === 'rolled_back' && (
          <div className="rounded border border-amber-700 bg-amber-900/30 p-2">
            <p className="text-xs text-amber-300">
              Rolled back to {canaryState.deployed_version} at {canaryState.rolled_back_at || 'just now'}
            </p>
          </div>
        )}

        {deployMutation.data && !canaryState && (
          <div className="text-sm text-green-400 flex items-center gap-1">
            <Check className="w-4 h-4" />
            Deployed to {deployMutation.data.environment}: {deployMutation.data.status}
          </div>
        )}
      </div>

      {/* Widget section */}
      <div className="bg-gray-800 rounded-lg border border-gray-700 p-4 space-y-3">
        <h3 className="text-sm font-medium text-gray-200">Web Widget</h3>
        <div className="flex gap-2">
          <input
            type="text" placeholder="Chat title" value={chatTitle}
            onChange={(e) => setChatTitle(e.target.value)}
            className="flex-1 bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm text-gray-200 focus:border-blue-500 focus:outline-none"
          />
          <input
            type="color" value={primaryColor}
            onChange={(e) => setPrimaryColor(e.target.value)}
            className="w-10 h-8 bg-gray-900 border border-gray-600 rounded cursor-pointer"
          />
          <button
            onClick={handleGenerateWidget}
            disabled={!project || !agentId || widgetMutation.isPending}
            className="px-4 py-1.5 bg-gray-600 text-white text-sm rounded hover:bg-gray-500 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Code2 className="w-4 h-4 inline mr-1" />
            {widgetMutation.isPending ? 'Generating...' : 'Generate'}
          </button>
        </div>
        {widgetMutation.data && (
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs text-gray-400">Widget HTML</span>
              <button onClick={handleCopyHtml} className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1">
                {copied ? <><Check className="w-3 h-3" /> Copied</> : <><Copy className="w-3 h-3" /> Copy HTML</>}
              </button>
            </div>
            <pre className="bg-gray-900 border border-gray-700 rounded p-3 text-xs text-gray-300 overflow-x-auto max-h-64 overflow-y-auto">
              {widgetMutation.data.html}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}
