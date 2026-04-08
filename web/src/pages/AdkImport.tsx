import { useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, Check, AlertCircle } from 'lucide-react';
import { useAdkStatus, useAdkImport } from '../lib/api';
import { PageHeader } from '../components/PageHeader';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { ReadinessReport } from '../components/ReadinessReport';
import { getImportPortabilityReport } from '../lib/portability';
import { toastError, toastSuccess } from '../lib/toast';

export function AdkImport() {
  const [step, setStep] = useState(1);
  const [agentPath, setAgentPath] = useState('');
  const [outputDir, setOutputDir] = useState('');

  const { data: statusData, isLoading: statusLoading, isError, refetch } = useAdkStatus(agentPath);
  const importMutation = useAdkImport();
  const portabilityReport = getImportPortabilityReport(importMutation.data);

  function handleParse() {
    if (!agentPath.trim()) return;
    refetch();
    setStep(2);
  }

  function handleImport() {
    if (!agentPath.trim()) return;
    importMutation.mutate(
      { path: agentPath, output_dir: outputDir || undefined },
      {
        onSuccess: (result) => {
          toastSuccess('Import complete', `Imported ${result.agent_name} with ${result.tools_imported} tools`);
          setStep(3);
        },
        onError: (err) => toastError('Import failed', err.message),
      }
    );
  }

  function handleReset() {
    setStep(1);
    setAgentPath('');
    setOutputDir('');
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Import ADK Agent"
        description="Import an agent from Google's Agent Developer Kit into AgentLab"
      />

      {/* Step indicators */}
      <div className="flex items-center gap-2 text-sm">
        {[1, 2, 3].map((s) => (
          <div key={s} className="flex items-center gap-1">
            <div className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-medium ${
              step >= s ? 'bg-blue-600 text-white' : 'bg-gray-200 text-gray-500'
            }`}>
              {step > s ? <Check className="w-3 h-3" /> : s}
            </div>
            <span className={step >= s ? 'text-gray-900' : 'text-gray-500'}>
              {s === 1 ? 'Agent Path' : s === 2 ? 'Preview' : 'Done'}
            </span>
            {s < 3 && <ArrowRight className="w-3 h-3 text-gray-400 mx-1" />}
          </div>
        ))}
      </div>

      {/* Step 1: Path input */}
      {step >= 1 && step < 3 && (
        <div className="bg-white rounded-lg border border-gray-200 p-4 space-y-3">
          <h3 className="text-sm font-medium text-gray-900">ADK Agent Directory</h3>
          <div className="flex gap-2">
            <div className="flex-1">
              <label htmlFor="adk-agent-path" className="mb-1 block text-xs text-gray-500">
                Agent directory
              </label>
              <input
                id="adk-agent-path"
                type="text"
                placeholder="/path/to/adk/agent"
                value={agentPath}
                onChange={(e) => setAgentPath(e.target.value)}
                className="w-full bg-white border border-gray-300 rounded px-3 py-1.5 text-sm text-gray-900 focus:border-blue-500 focus:outline-none"
              />
            </div>
            <div className="w-48">
              <label htmlFor="adk-output-dir" className="mb-1 block text-xs text-gray-500">
                Output directory
              </label>
              <input
                id="adk-output-dir"
                type="text"
                placeholder="Output dir (optional)"
                value={outputDir}
                onChange={(e) => setOutputDir(e.target.value)}
                className="w-full bg-white border border-gray-300 rounded px-3 py-1.5 text-sm text-gray-900 focus:border-blue-500 focus:outline-none"
              />
            </div>
            <button
              onClick={handleParse}
              disabled={!agentPath.trim()}
              className="self-end px-4 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Parse Agent
            </button>
          </div>
          <p className="text-xs text-gray-600">
            Path to the directory containing the ADK agent directory with agent.py and __init__.py
          </p>
        </div>
      )}

      {/* Step 2: Preview */}
      {step === 2 && (
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <h3 className="text-sm font-medium text-gray-900 mb-3">Agent Structure</h3>
          {statusLoading && <LoadingSkeleton rows={3} />}
          {isError && (
            <div className="flex items-center gap-2 text-red-600 text-sm">
              <AlertCircle className="w-4 h-4" />
              Failed to parse agent. Check path and ADK agent directory structure.
            </div>
          )}
          {statusData && (
            <div className="space-y-3">
              <div className="text-sm text-gray-700 space-y-1">
                <p><span className="text-gray-500">Name:</span> {statusData.agent.name}</p>
                <p><span className="text-gray-500">Model:</span> {statusData.agent.model}</p>
                <p><span className="text-gray-500">Tools:</span> {statusData.agent.tools.length} tools</p>
                <p><span className="text-gray-500">Sub-agents:</span> {statusData.agent.sub_agents.length} agents</p>
              </div>
              {statusData.agent.tools.length > 0 && (
                <div>
                  <p className="text-xs text-gray-500 mb-1">Tools:</p>
                  <ul className="text-xs text-gray-600 space-y-0.5 pl-4">
                    {statusData.agent.tools.map((tool, idx) => (
                      <li key={idx}>• {tool.name} - {tool.description}</li>
                    ))}
                  </ul>
                </div>
              )}
              {statusData.agent.sub_agents.length > 0 && (
                <div>
                  <p className="text-xs text-gray-500 mb-1">Sub-agents:</p>
                  <ul className="text-xs text-gray-600 space-y-0.5 pl-4">
                    {statusData.agent.sub_agents.map((sub, idx) => (
                      <li key={idx}>• {sub.name} ({sub.tools.length} tools)</li>
                    ))}
                  </ul>
                </div>
              )}
              <p className="text-xs text-gray-600 mt-3">
                This will map the ADK agent structure to AgentLab config format.
              </p>
              <div className="flex gap-2 mt-3">
                <button
                  onClick={() => setStep(1)}
                  className="px-4 py-1.5 bg-gray-100 text-gray-700 text-sm rounded hover:bg-gray-200"
                >
                  Back
                </button>
                <button
                  onClick={handleImport}
                  disabled={importMutation.isPending}
                  className="px-4 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-500 disabled:opacity-50"
                >
                  {importMutation.isPending ? 'Importing...' : 'Import Agent'}
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Step 3: Done */}
      {step === 3 && importMutation.data && (
        <div className="space-y-4">
          {/* Import summary */}
          <div className="bg-white rounded-lg border border-green-200 p-4 space-y-2">
            <div className="flex items-center gap-2 text-green-700">
              <Check className="w-5 h-5" />
              <h3 className="text-sm font-medium">Import Complete</h3>
            </div>
            <div className="text-sm text-gray-700 space-y-1">
              <p><span className="text-gray-500">Agent:</span> {importMutation.data.agent_name}</p>
              <p><span className="text-gray-500">Config:</span> {importMutation.data.config_path}</p>
              <p><span className="text-gray-500">Snapshot:</span> {importMutation.data.snapshot_path}</p>
              <p><span className="text-gray-500">Tools imported:</span> {importMutation.data.tools_imported}</p>
              <p><span className="text-gray-500">Surfaces mapped:</span> {importMutation.data.surfaces_mapped.join(', ')}</p>
            </div>
          </div>

          {/* Readiness report */}
          <ReadinessReport
            report={portabilityReport}
            fallbackSurfaces={importMutation.data.surfaces_mapped}
            fallbackToolsCount={importMutation.data.tools_imported}
            adapter="ADK"
          />

          <div className="flex flex-wrap gap-2 pt-1">
            <button
              onClick={handleReset}
              className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 transition hover:bg-gray-100"
            >
              Import another agent
            </button>
            {!portabilityReport && (
              <>
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
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
