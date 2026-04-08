import { useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, Check, AlertCircle } from 'lucide-react';
import { useCxAgents, useCxImport } from '../lib/api';
import { PageHeader } from '../components/PageHeader';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { ReadinessReport } from '../components/ReadinessReport';
import { toastError, toastSuccess } from '../lib/toast';
import type { CxAgentSummary } from '../lib/types';

export function CxImport() {
  const [step, setStep] = useState(1);
  const [project, setProject] = useState('');
  const [location, setLocation] = useState('global');
  const [selectedAgent, setSelectedAgent] = useState<CxAgentSummary | null>(null);

  const { data: agents, isLoading: agentsLoading, isError, refetch } = useCxAgents(project, location);
  const importMutation = useCxImport();

  function handleFetchAgents() {
    if (!project.trim()) return;
    refetch();
    setStep(2);
  }

  function handleSelectAgent(agent: CxAgentSummary) {
    setSelectedAgent(agent);
    setStep(3);
  }

  function handleImport() {
    if (!selectedAgent) return;
    const agentId = selectedAgent.name.split('/').pop() || '';
    importMutation.mutate(
      { project, location, agent_id: agentId },
      {
        onSuccess: (result) => {
          toastSuccess('Import complete', `Imported ${result.agent_name} with ${result.test_cases_imported} test cases`);
          setStep(4);
        },
        onError: (err) => toastError('Import failed', err.message),
      }
    );
  }

  function handleReset() {
    setStep(1);
    setProject('');
    setLocation('global');
    setSelectedAgent(null);
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Import CX Agent"
        description="Import an agent from Google Cloud CX Agent Studio into AgentLab"
      />

      {/* Step indicators */}
      <div className="flex items-center gap-2 text-sm">
        {[1, 2, 3, 4].map((s) => (
          <div key={s} className="flex items-center gap-1">
            <div className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-medium ${
              step >= s ? 'bg-blue-600 text-white' : 'bg-gray-700 text-gray-400'
            }`}>
              {step > s ? <Check className="w-3 h-3" /> : s}
            </div>
            <span className={step >= s ? 'text-gray-900' : 'text-gray-500'}>
              {s === 1 ? 'Project' : s === 2 ? 'Select Agent' : s === 3 ? 'Preview' : 'Done'}
            </span>
            {s < 4 && <ArrowRight className="w-3 h-3 text-gray-600 mx-1" />}
          </div>
        ))}
      </div>

      {/* Step 1: Project */}
      {step >= 1 && step < 4 && (
        <div className="bg-white rounded-lg border border-gray-200 p-4 space-y-3">
          <h3 className="text-sm font-medium text-gray-900">GCP Project</h3>
          <div className="flex gap-2">
            <div className="flex-1">
              <label htmlFor="cx-project" className="mb-1 block text-xs text-gray-500">
                GCP project ID
              </label>
              <input
                id="cx-project"
                type="text"
                placeholder="my-gcp-project"
                value={project}
                onChange={(e) => setProject(e.target.value)}
                className="w-full bg-white border border-gray-300 rounded px-3 py-1.5 text-sm text-gray-900 focus:border-blue-500 focus:outline-none"
              />
            </div>
            <div className="w-32">
              <label htmlFor="cx-location" className="mb-1 block text-xs text-gray-500">
                Location
              </label>
              <input
                id="cx-location"
                type="text"
                placeholder="global"
                value={location}
                onChange={(e) => setLocation(e.target.value)}
                className="w-full bg-white border border-gray-300 rounded px-3 py-1.5 text-sm text-gray-900 focus:border-blue-500 focus:outline-none"
              />
            </div>
            <button
              onClick={handleFetchAgents}
              disabled={!project.trim()}
              className="self-end px-4 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              List Agents
            </button>
          </div>
        </div>
      )}

      {/* Step 2: Agent list */}
      {step === 2 && (
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <h3 className="text-sm font-medium text-gray-900 mb-3">Select Agent</h3>
          {agentsLoading && <LoadingSkeleton rows={3} />}
          {isError && (
            <div className="flex items-center gap-2 text-red-400 text-sm">
              <AlertCircle className="w-4 h-4" />
              Failed to fetch agents. Check project ID and credentials.
            </div>
          )}
          {agents && agents.length === 0 && (
            <p className="text-gray-400 text-sm">No agents found in this project.</p>
          )}
          {agents && agents.length > 0 && (
            <div className="space-y-1">
              {agents.map((agent) => (
                <button
                  key={agent.name}
                  onClick={() => handleSelectAgent(agent)}
                  className="w-full text-left px-3 py-2 rounded hover:bg-gray-50 transition-colors"
                >
                  <div className="text-sm font-medium text-gray-900">{agent.display_name}</div>
                  <div className="text-xs text-gray-400">{agent.description || 'No description'} · {agent.default_language_code}</div>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Step 3: Preview + confirm */}
      {step === 3 && selectedAgent && (
        <div className="bg-white rounded-lg border border-gray-200 p-4 space-y-3">
          <h3 className="text-sm font-medium text-gray-900">Import Preview</h3>
          <div className="text-sm text-gray-700 space-y-1">
            <p><span className="text-gray-500">Agent:</span> {selectedAgent.display_name}</p>
            <p><span className="text-gray-500">Language:</span> {selectedAgent.default_language_code}</p>
            <p><span className="text-gray-500">Description:</span> {selectedAgent.description || '—'}</p>
          </div>
          <p className="text-xs text-gray-400">
            This will fetch the agent's instructions, tools, examples, and test cases,
            then map them to AgentLab config format.
          </p>
          <div className="flex gap-2">
            <button
              onClick={() => setStep(2)}
              className="px-4 py-1.5 bg-gray-700 text-gray-900 text-sm rounded hover:bg-gray-100"
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

      {/* Step 4: Done */}
      {step === 4 && importMutation.data && (
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
              {importMutation.data.eval_path && (
                <p><span className="text-gray-500">Eval cases:</span> {importMutation.data.eval_path} ({importMutation.data.test_cases_imported} cases)</p>
              )}
              <p><span className="text-gray-500">Snapshot:</span> {importMutation.data.snapshot_path}</p>
              <p><span className="text-gray-500">Surfaces:</span> {importMutation.data.surfaces_mapped.join(', ')}</p>
            </div>
          </div>

          {/* Readiness report */}
          <ReadinessReport
            report={importMutation.data.portability ?? null}
            fallbackSurfaces={importMutation.data.surfaces_mapped}
            adapter="CX"
          />

          <div className="flex flex-wrap gap-2 pt-1">
            <button
              onClick={handleReset}
              className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 transition hover:bg-gray-100"
            >
              Import another agent
            </button>
            {!importMutation.data.portability && (
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
