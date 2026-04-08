import { useEffect, useState } from 'react';
import { Code2, Copy, Check } from 'lucide-react';
import { useConfigShow, useConfigs, useCxDeploy, useCxExport, useCxWidget } from '../lib/api';
import { PageHeader } from '../components/PageHeader';
import { ExportReadiness } from '../components/ExportReadiness';
import { toastError, toastSuccess } from '../lib/toast';

export function CxDeploy() {
  // Deploy state
  const [project, setProject] = useState('');
  const [location, setLocation] = useState('global');
  const [agentId, setAgentId] = useState('');
  const [environment, setEnvironment] = useState('production');
  const [snapshotPath, setSnapshotPath] = useState('');
  const [configVersion, setConfigVersion] = useState('');

  // Widget state
  const [chatTitle, setChatTitle] = useState('Agent');
  const [primaryColor, setPrimaryColor] = useState('#1a73e8');
  const [copied, setCopied] = useState(false);

  const { data: configs } = useConfigs();
  const selectedVersion = configVersion ? Number(configVersion) : null;
  const selectedConfig = useConfigShow(selectedVersion);
  const deployMutation = useCxDeploy();
  const exportMutation = useCxExport();
  const widgetMutation = useCxWidget();

  useEffect(() => {
    if (!configVersion && configs && configs.length > 0) {
      setConfigVersion(String(configs[0].version));
    }
  }, [configVersion, configs]);

  function handleDeploy() {
    if (!project || !agentId) return;
    deployMutation.mutate(
      { project, location, agent_id: agentId, environment },
      {
        onSuccess: (result) => toastSuccess('Deploy successful', `Deployed to ${result.environment}`),
        onError: (err) => toastError('Deploy failed', err.message),
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

  return (
    <div className="space-y-6">
      <PageHeader
        title="CX Deploy & Widget"
        description="Deploy to CX Agent Studio environments and generate web widget embed code"
      />

      {/* Shared config */}
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
            type="text" placeholder="Agent ID" value={agentId}
            onChange={(e) => setAgentId(e.target.value)}
            className="bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm text-gray-200 focus:border-blue-500 focus:outline-none"
          />
        </div>
      </div>

      {/* Deploy section */}
      <div className="bg-gray-800 rounded-lg border border-gray-700 p-4 space-y-3">
        <h3 className="text-sm font-medium text-gray-200">Preview & Export to CX</h3>
        <p className="text-xs text-gray-400">
          Select the optimized AgentLab config + CX snapshot, preview exact changes, then push when ready.
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
            onClick={handlePreviewExport}
            disabled={!project || !agentId || !snapshotPath || !selectedConfig.data?.config || exportMutation.isPending}
            className="px-4 py-1.5 bg-gray-600 text-white text-sm rounded hover:bg-gray-500 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {exportMutation.isPending ? 'Previewing...' : 'Preview Export'}
          </button>
          <button
            onClick={handlePushExport}
            disabled={!project || !agentId || !snapshotPath || !selectedConfig.data?.config || exportMutation.isPending}
            className="px-4 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {exportMutation.isPending ? 'Pushing...' : 'Push to CX Agent Studio'}
          </button>
        </div>
        {exportMutation.data && (
          <div className="rounded border border-gray-700 bg-gray-900 p-3">
            <p className="text-xs text-gray-400 mb-2">Planned Changes ({exportMutation.data.changes.length})</p>
            {exportMutation.data.changes.length === 0 ? (
              <p className="text-sm text-gray-300">No changes detected.</p>
            ) : (
              <div className="space-y-1.5">
                {exportMutation.data.changes.map((change, index) => (
                  <p key={`${change.resource}-${change.action}-${index}`} className="text-xs text-gray-300">
                    {change.action.toUpperCase()} {change.resource}/{change.name || change.field || 'resource'}
                  </p>
                ))}
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
        changeCount={exportMutation.data ? exportMutation.data.changes.length : undefined}
        conflictCount={exportMutation.data ? exportMutation.data.conflicts.length : undefined}
        exportAttempted={!!exportMutation.data}
      />

      {/* Deploy section */}
      <div className="bg-gray-800 rounded-lg border border-gray-700 p-4 space-y-3">
        <h3 className="text-sm font-medium text-gray-200">Deploy to Environment</h3>
        <div className="flex gap-2">
          <select
            value={environment}
            onChange={(e) => setEnvironment(e.target.value)}
            className="bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm text-gray-200 focus:border-blue-500 focus:outline-none"
          >
            <option value="production">Production</option>
            <option value="staging">Staging</option>
            <option value="draft">Draft</option>
          </select>
          <button
            onClick={handleDeploy}
            disabled={!project || !agentId || deployMutation.isPending}
            className="px-4 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {deployMutation.isPending ? 'Deploying...' : 'Deploy'}
          </button>
        </div>
        {deployMutation.data && (
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
