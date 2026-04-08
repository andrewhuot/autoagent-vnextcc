import { useState } from 'react';
import { Rocket, Cloud, Brain, ExternalLink, AlertCircle, Check } from 'lucide-react';
import { useAdkDeploy, useAdkDiff } from '../lib/api';
import { PageHeader } from '../components/PageHeader';
import { ExportReadiness } from '../components/ExportReadiness';
import { toastError, toastSuccess } from '../lib/toast';

export function AdkDeploy() {
  const [agentPath, setAgentPath] = useState('');
  const [target, setTarget] = useState<'cloud-run' | 'vertex-ai'>('cloud-run');
  const [projectId, setProjectId] = useState('');
  const [region, setRegion] = useState('us-central1');
  const [showPreview, setShowPreview] = useState(false);
  const [configPath, setConfigPath] = useState('');
  const [snapshotPath, setSnapshotPath] = useState('');

  const deployMutation = useAdkDeploy();
  const { data: diffData, isLoading: diffLoading } = useAdkDiff(configPath, snapshotPath);

  function handleDeploy() {
    if (!agentPath.trim() || !projectId.trim()) {
      toastError('Validation error', 'Agent path and project ID are required');
      return;
    }

    deployMutation.mutate(
      { path: agentPath, target, project: projectId, region },
      {
        onSuccess: (result) => {
          toastSuccess('Deploy successful', `Deployed to ${result.target}`);
        },
        onError: (err) => toastError('Deploy failed', err.message),
      }
    );
  }

  function handleShowPreview() {
    if (!configPath.trim() || !snapshotPath.trim()) {
      toastError('Validation error', 'Config and snapshot paths are required for preview');
      return;
    }
    setShowPreview(true);
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Deploy ADK Agent"
        description="Deploy your ADK agent to Google Cloud Run or Vertex AI"
      />

      {/* Agent config */}
      <div className="bg-gray-800 rounded-lg border border-gray-700 p-4 space-y-3">
        <h3 className="text-sm font-medium text-gray-200">Agent Configuration</h3>
        <div className="space-y-2">
          <input
            type="text"
            placeholder="Agent path (e.g., /path/to/adk/agent)"
            value={agentPath}
            onChange={(e) => setAgentPath(e.target.value)}
            className="w-full bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm text-gray-200 focus:border-blue-500 focus:outline-none"
          />
          <div className="grid grid-cols-2 gap-2">
            <input
              type="text"
              placeholder="GCP Project ID"
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
              className="bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm text-gray-200 focus:border-blue-500 focus:outline-none"
            />
            <select
              value={region}
              onChange={(e) => setRegion(e.target.value)}
              className="bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm text-gray-200 focus:border-blue-500 focus:outline-none"
            >
              <option value="us-central1">us-central1</option>
              <option value="us-east1">us-east1</option>
              <option value="us-west1">us-west1</option>
              <option value="europe-west1">europe-west1</option>
              <option value="asia-east1">asia-east1</option>
            </select>
          </div>
        </div>
      </div>

      {/* Deployment target */}
      <div className="bg-gray-800 rounded-lg border border-gray-700 p-4 space-y-3">
        <h3 className="text-sm font-medium text-gray-200">Deployment Target</h3>
        <div className="flex gap-3">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="radio"
              value="cloud-run"
              checked={target === 'cloud-run'}
              onChange={(e) => setTarget(e.target.value as 'cloud-run')}
              className="text-blue-600"
            />
            <Cloud className="w-4 h-4 text-gray-400" />
            <span className="text-sm text-gray-200">Cloud Run</span>
          </label>
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="radio"
              value="vertex-ai"
              checked={target === 'vertex-ai'}
              onChange={(e) => setTarget(e.target.value as 'vertex-ai')}
              className="text-blue-600"
            />
            <Brain className="w-4 h-4 text-gray-400" />
            <span className="text-sm text-gray-200">Vertex AI</span>
          </label>
        </div>
        <p className="text-xs text-gray-400">
          {target === 'cloud-run'
            ? 'Deploy as a containerized service on Google Cloud Run'
            : 'Deploy as a managed agent on Vertex AI Agent Builder'}
        </p>
      </div>

      {/* Preview changes */}
      <div className="bg-gray-800 rounded-lg border border-gray-700 p-4 space-y-3">
        <h3 className="text-sm font-medium text-gray-200">Preview Changes (Optional)</h3>
        <div className="grid grid-cols-2 gap-2">
          <input
            type="text"
            placeholder="Config path"
            value={configPath}
            onChange={(e) => setConfigPath(e.target.value)}
            className="bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm text-gray-200 focus:border-blue-500 focus:outline-none"
          />
          <input
            type="text"
            placeholder="Snapshot path"
            value={snapshotPath}
            onChange={(e) => setSnapshotPath(e.target.value)}
            className="bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm text-gray-200 focus:border-blue-500 focus:outline-none"
          />
        </div>
        <button
          onClick={handleShowPreview}
          disabled={!configPath.trim() || !snapshotPath.trim()}
          className="px-4 py-1.5 bg-gray-600 text-white text-sm rounded hover:bg-gray-500 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          Show Diff
        </button>
        {showPreview && diffLoading && (
          <p className="text-xs text-gray-400">Loading diff...</p>
        )}
        {showPreview && diffData && (
          <div className="space-y-2">
            <div className="text-xs text-gray-400">
              {diffData.changes.length} changes detected
            </div>
            <div className="bg-gray-900 border border-gray-700 rounded p-3 text-xs text-gray-300 overflow-x-auto max-h-64 overflow-y-auto">
              {diffData.changes.map((change, idx) => (
                <div key={idx} className="mb-1">
                  <span className={change.action === 'added' ? 'text-green-400' : change.action === 'removed' ? 'text-red-400' : 'text-yellow-400'}>
                    {change.action}
                  </span>
                  {' '}{change.file} → {change.field}
                </div>
              ))}
            </div>
            {diffData.diff && (
              <pre className="bg-gray-900 border border-gray-700 rounded p-3 text-xs text-gray-300 overflow-x-auto max-h-64 overflow-y-auto">
                {diffData.diff}
              </pre>
            )}
          </div>
        )}
      </div>

      {/* Export readiness */}
      <ExportReadiness
        adapter="ADK"
        exportMatrix={null}
        changeCount={showPreview && diffData ? diffData.changes.length : undefined}
        exportAttempted={showPreview && !!diffData}
      />

      {/* Deploy button */}
      <div className="bg-gray-800 rounded-lg border border-gray-700 p-4 space-y-3">
        <button
          onClick={handleDeploy}
          disabled={!agentPath.trim() || !projectId.trim() || deployMutation.isPending}
          className="w-full px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
        >
          <Rocket className="w-4 h-4" />
          {deployMutation.isPending ? 'Deploying...' : 'Deploy to ' + (target === 'cloud-run' ? 'Cloud Run' : 'Vertex AI')}
        </button>
        {deployMutation.data && (
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-green-400">
              <Check className="w-4 h-4" />
              <span className="text-sm">Deploy successful: {deployMutation.data.status}</span>
            </div>
            <div className="text-sm text-gray-300 space-y-1">
              <p><span className="text-gray-500">Target:</span> {deployMutation.data.target}</p>
              {deployMutation.data.url && (
                <p>
                  <span className="text-gray-500">URL:</span>{' '}
                  <a
                    href={deployMutation.data.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-400 hover:text-blue-300 inline-flex items-center gap-1"
                  >
                    {deployMutation.data.url}
                    <ExternalLink className="w-3 h-3" />
                  </a>
                </p>
              )}
            </div>
          </div>
        )}
        {deployMutation.isError && (
          <div className="flex items-center gap-2 text-red-400 text-sm">
            <AlertCircle className="w-4 h-4" />
            Deploy failed. Check configuration and credentials.
          </div>
        )}
      </div>
    </div>
  );
}
